"""Compare lexical, dense, and hybrid retrieval over the same tool surface.

``evals/tool_retrieval/run.py`` measures BM25, and its aggregate score is
good. The interesting case is the one the aggregate hides: a request phrased
in vocabulary the tool description does not contain. Lexical matching has no
bridge to it, and no amount of tuning k1/b builds one.

This script scores three retrievers over the identical corpus and the
identical labeled prompts, so the difference attributable to the retriever
is isolated:

* **bm25**   -- the lexical baseline from ``run.py``
* **dense**  -- cosine similarity over embeddings of the same documents
* **hybrid** -- reciprocal rank fusion of the two

Configure the embedding endpoint exactly as ``evals/live_model.py``:

    EVAL_EMBED_MODEL   default argo:text-embedding-3-small
    EVAL_MODEL_BASE_URL / EVAL_MODEL_API_KEY

    uv run python -m evals.tool_retrieval.compare_retrievers
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from evals.tool_retrieval.prompts import PROMPTS
from evals.tool_retrieval.run import build_corpus, rank

_RRF_K = 60


def _embed(texts: list[str]) -> list[list[float]]:
    base = os.environ.get("EVAL_MODEL_BASE_URL", "http://localhost:44445/v1").rstrip("/")
    key = os.environ.get("EVAL_MODEL_API_KEY") or os.environ.get("ARGO_API_KEY") or "none"
    model = os.environ.get("EVAL_EMBED_MODEL", "argo:text-embedding-3-small")
    out: list[list[float]] = []
    # Batch to keep each request small and the failure blast radius local.
    for start in range(0, len(texts), 32):
        chunk = texts[start : start + 32]
        request = urllib.request.Request(
            f"{base}/embeddings",
            data=json.dumps({"model": model, "input": chunk}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read())
        rows = sorted(payload["data"], key=lambda r: r["index"])
        out.extend(r["embedding"] for r in rows)
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0.0 or nb == 0.0 else num / (na * nb)


def _rank_of(ordering: list[str], expected: str) -> int:
    return ordering.index(expected) + 1 if expected in ordering else 10**6


def _metrics(ranks: list[int]) -> dict[str, Any]:
    n = len(ranks)
    return {
        "top1": round(sum(r == 1 for r in ranks) / n, 3),
        "top3": round(sum(r <= 3 for r in ranks) / n, 3),
        "top5": round(sum(r <= 5 for r in ranks) / n, 3),
        "mrr": round(sum(1.0 / r for r in ranks) / n, 3),
        "mean_rank": round(sum(ranks) / n, 2),
        "worst_rank": max(ranks),
    }


def main() -> int:
    corpus = build_corpus()
    names = [name for name, _, _ in corpus]
    df: Counter = Counter()
    for _, tokens, _ in corpus:
        df.update(set(tokens))
    avgdl = sum(len(t) for _, t, _ in corpus) / len(corpus)

    print(f"Embedding {len(corpus)} tool documents ...")
    doc_vectors = _embed([text for _, _, text in corpus])
    print(f"Embedding {len(PROMPTS)} queries ...")
    query_vectors = _embed([p for p, _ in PROMPTS])

    per_query: list[dict[str, Any]] = []
    ranks: dict[str, list[int]] = {"bm25": [], "dense": [], "hybrid": []}

    for i, (prompt, expected) in enumerate(PROMPTS):
        lexical = [n for n, _ in rank(prompt, corpus, df, avgdl)]
        scored = sorted(
            ((names[j], _cosine(query_vectors[i], doc_vectors[j])) for j in range(len(names))),
            key=lambda x: x[1],
            reverse=True,
        )
        dense = [n for n, _ in scored]

        lex_pos = {n: r for r, n in enumerate(lexical, 1)}
        den_pos = {n: r for r, n in enumerate(dense, 1)}
        fused = sorted(
            names,
            key=lambda n: -(
                1.0 / (_RRF_K + lex_pos.get(n, 10**6))
                + 1.0 / (_RRF_K + den_pos.get(n, 10**6))
            ),
        )

        row = {
            "prompt": prompt,
            "expected": expected,
            "bm25_rank": _rank_of(lexical, expected),
            "dense_rank": _rank_of(dense, expected),
            "hybrid_rank": _rank_of(fused, expected),
        }
        per_query.append(row)
        ranks["bm25"].append(row["bm25_rank"])
        ranks["dense"].append(row["dense_rank"])
        ranks["hybrid"].append(row["hybrid_rank"])

    summary = {name: _metrics(values) for name, values in ranks.items()}
    summary["indexed_tools"] = len(corpus)
    summary["prompts_scored"] = len(PROMPTS)
    summary["embedding_model"] = os.environ.get(
        "EVAL_EMBED_MODEL", "argo:text-embedding-3-small"
    )

    header = f"{'retriever':<10}{'top1':>7}{'top3':>7}{'MRR':>7}{'mean':>7}{'worst':>7}"
    print("\n" + header)
    print("-" * len(header))
    for name in ("bm25", "dense", "hybrid"):
        m = summary[name]
        print(
            f"{name:<10}{m['top1']:>7}{m['top3']:>7}{m['mrr']:>7}"
            f"{m['mean_rank']:>7}{m['worst_rank']:>7}"
        )

    print("\nQueries where the retrievers disagree most:")
    for row in sorted(per_query, key=lambda r: r["bm25_rank"] - r["hybrid_rank"], reverse=True)[:5]:
        print(
            f"  bm25={row['bm25_rank']:<4} dense={row['dense_rank']:<4} "
            f"hybrid={row['hybrid_rank']:<4} {row['expected']}  \"{row['prompt'][:58]}\""
        )

    out_dir = Path(__file__).resolve().parent.parent / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"retrieval_compare_{int(time.time())}.json"
    out_path.write_text(
        json.dumps({"summary": summary, "results": per_query}, indent=2)
    )
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
