"""Run the tool-retrieval eval (BM25 over the full tool surface).

Builds a document per tool from (name + docstring + parameter names), indexes
them with a small BM25 implementation, and scores the labeled prompts.

The BM25 implementation is intentionally a self-contained ~40 lines so this
eval has no new dependencies. Production retrieval would use a real BM25
library (or, better, embeddings) — but to answer "is naive text matching
enough?" the implementation choice barely matters.
"""

from __future__ import annotations

import inspect
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

from evals.tool_retrieval.prompts import PROMPTS

# Stopwords kept tiny — we want the technical terms to do the work.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "he",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "that",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
        "i",
        "me",
        "my",
        "this",
        "these",
        "those",
        "any",
        "or",
        "if",
        "do",
        "have",
        "you",
        "your",
        "all",
        "each",
    }
)


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


def build_corpus() -> list[tuple[str, list[str], str]]:
    """For each public tool, return (name, tokens, raw_text)."""
    from uxarray_mcp import tools as tools_mod

    docs: list[tuple[str, list[str], str]] = []
    for name in tools_mod.__all__:
        fn = getattr(tools_mod, name, None)
        if fn is None or not callable(fn):
            continue
        doc = inspect.getdoc(fn) or ""
        try:
            params = ", ".join(inspect.signature(fn).parameters.keys())
        except (TypeError, ValueError):
            params = ""
        # Split CamelCase / snake_case into terms so 'calculate_zonal_mean'
        # contributes 'calculate', 'zonal', 'mean'.
        name_terms = re.sub(r"[_]+", " ", name)
        text = f"{name_terms} {name_terms} {doc} {params}"
        docs.append((name, _tokenize(text), text))
    return docs


def bm25_score(
    query: list[str],
    doc: list[str],
    df: Counter,
    n_docs: int,
    avgdl: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not doc:
        return 0.0
    score = 0.0
    dl = len(doc)
    tf = Counter(doc)
    for term in query:
        n_t = df.get(term, 0)
        if n_t == 0:
            continue
        idf = math.log((n_docs - n_t + 0.5) / (n_t + 0.5) + 1.0)
        f = tf[term]
        denom = f + k1 * (1.0 - b + b * dl / avgdl)
        score += idf * f * (k1 + 1.0) / denom
    return score


def rank(
    query_str: str, corpus: list[tuple[str, list[str], str]], df: Counter, avgdl: float
) -> list[tuple[str, float]]:
    q = _tokenize(query_str)
    n = len(corpus)
    scored = [(name, bm25_score(q, toks, df, n, avgdl)) for name, toks, _ in corpus]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def main() -> int:
    corpus = build_corpus()
    n_docs = len(corpus)
    avgdl = sum(len(toks) for _, toks, _ in corpus) / n_docs if n_docs else 0.0
    df: Counter = Counter()
    for _, toks, _ in corpus:
        for term in set(toks):
            df[term] += 1

    available = {name for name, _, _ in corpus}
    results = []
    print(f"Indexed {n_docs} tools. Avg doc length = {avgdl:.1f} tokens.\n")
    print(f"{'prompt':55s} {'expected':28s} {'top1':6s} {'rank':5s}")
    print("-" * 100)

    top1 = top3 = top5 = 0
    ranks = []
    missing_expected = []

    for prompt, expected in PROMPTS:
        if expected not in available:
            missing_expected.append(expected)
            continue
        ranked = rank(prompt, corpus, df, avgdl)
        names = [n for n, _ in ranked]
        try:
            r = names.index(expected) + 1
        except ValueError:
            r = n_docs + 1
        ranks.append(r)
        if r == 1:
            top1 += 1
        if r <= 3:
            top3 += 1
        if r <= 5:
            top5 += 1
        results.append(
            {
                "prompt": prompt,
                "expected": expected,
                "rank": r,
                "top1": names[0] if names else None,
                "top3": names[:3],
            }
        )
        print(
            f"{prompt[:54]:55s} {expected[:27]:28s} "
            f"{'✓' if names[0] == expected else '✗':6s} {r:<5d}"
        )

    n = len(results)
    summary = {
        "indexed_tools": n_docs,
        "prompts_scored": n,
        "missing_expected_tools": missing_expected,
        "top1_accuracy": round(top1 / n, 3) if n else None,
        "top3_accuracy": round(top3 / n, 3) if n else None,
        "top5_accuracy": round(top5 / n, 3) if n else None,
        "mean_rank": round(sum(ranks) / n, 2) if n else None,
        "median_rank": sorted(ranks)[n // 2] if n else None,
        "worst_rank": max(ranks) if n else None,
    }
    print()
    print("SUMMARY")
    for k, v in summary.items():
        print(f"  {k:30s} {v}")

    if summary["top1_accuracy"] is not None:
        if summary["top1_accuracy"] >= 0.9:
            print("\nPASS — top-1 ≥ 90%. Deferred-full tool pool is safe with BM25.")
        elif summary["top3_accuracy"] and summary["top3_accuracy"] >= 0.95:
            print(
                "\nPARTIAL — top-1 below 90% but top-3 ≥ 95%. "
                "Show the AI a 3-candidate shortlist."
            )
        else:
            print(
                "\nFAIL — top-1 < 90% and top-3 < 95%. "
                "Keep the surface small, or switch to embedding-based retrieval."
            )

    out_dir = Path(__file__).resolve().parent.parent / "results"
    out_dir.mkdir(exist_ok=True)
    ts = int(time.time())
    out_path = out_dir / f"retrieval_{ts}.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
