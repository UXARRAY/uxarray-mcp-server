"""Emit the exact numbers and LaTeX rows used in the repair-naming ablation."""
import json, glob, re, collections

BADOP = re.compile(r"Unsupported analysis operation '([^']+)'")
BADARG = re.compile(r"unexpected keyword argument '([^']+)'")
MISSARG = re.compile(r"missing \d+ required positional argument")
REQ = re.compile(r"'(\w+)' requires (\w+)\.")

MODELS = ["claude-4.5-sonnet", "gemini-2.5-flash", "gemini-2.5-pro", "gpt-4.1-mini",
          "gpt-4o", "gpt-5", "gpt-5-mini", "o4-mini"]

def load():
    out = collections.defaultdict(list)   # arm -> [(model, report)]
    for f in sorted(glob.glob("evals/results/multi_turn_*.json")):
        try: d = json.load(open(f))
        except Exception: continue
        for rep in d.get("reports", []):
            mid = rep.get("model_id", "")
            if "#" not in mid: continue
            model, arm = mid.split("#", 1)
            out[arm].append((model.replace("argo:", ""), rep))
    return out

def classify(e):
    if BADOP.search(e): return "bad_operation"
    if BADARG.search(e): return "bad_argument"
    if MISSARG.search(e): return "missing_arg"
    if REQ.search(e): return "requires_path"
    if "not found" in e: return "not_found"
    return "other"

arms = load()
norm = {"bare": "bare", "repair": "repair", "repair2": "repair", "handles": "handles"}

agg = collections.defaultdict(lambda: dict(
    runs=0, reps=0, badop=0, allerr=0, calls=0.0, chained=0, tasks=0,
    recovered=0, faults=0, finished=0, affected=0, distinct=collections.Counter(),
    cats=collections.Counter()))
permodel = collections.defaultdict(lambda: collections.defaultdict(
    lambda: dict(badop=0, allerr=0, calls=[], chained=0, tasks=0, n=0)))

for arm_raw, entries in arms.items():
    arm = norm.get(arm_raw, arm_raw)
    for model, rep in entries:
        s = rep["summary"]
        a = agg[arm]; a["reps"] += 1
        a["calls"] += s["mean_calls"]; a["chained"] += s["chained"]; a["tasks"] += s["tasks"]
        a["recovered"] += s["recovered"]; a["faults"] += s["fault_tasks"]; a["finished"] += s["finished"]
        pm = permodel[model][arm]
        pm["n"] += 1; pm["calls"].append(s["mean_calls"])
        pm["chained"] += s["chained"]; pm["tasks"] += s["tasks"]
        for run in rep["runs"]:
            a["runs"] += 1
            g = [BADOP.search(e).group(1) for e in run.get("errors", []) if BADOP.search(e)]
            if g:
                a["affected"] += 1
                a["distinct"][len(set(g))] += 1
            for e in run.get("errors", []):
                a["allerr"] += 1; pm["allerr"] += 1
                a["cats"][classify(e)] += 1
                if BADOP.search(e):
                    a["badop"] += 1; pm["badop"] += 1

order = [a for a in ("bare", "repair", "handles") if a in agg]
print("=" * 78)
for arm in order:
    a = agg[arm]
    dd = dict(sorted(a["distinct"].items()))
    print(f"[{arm}] reps={a['reps']} runs={a['runs']}")
    print(f"   bad-op errors {a['badop']}  ({a['badop']/a['runs']:.2f}/run)   all errors {a['allerr']} ({a['allerr']/a['runs']:.2f}/run)")
    print(f"   runs w/ bad op {a['affected']}/{a['runs']} = {100*a['affected']/a['runs']:.1f}%")
    print(f"   distinct-guesses-per-affected-run {dd}  max={max(a['distinct']) if a['distinct'] else 0}")
    print(f"   mean calls {a['calls']/a['reps']:.2f}  chained {a['chained']}/{a['tasks']}  "
          f"recovered {a['recovered']}/{a['faults']}  finished {a['finished']}/{a['tasks']}")
    tot = sum(a["cats"].values())
    print("   taxonomy: " + "  ".join(f"{k}={v}({100*v/tot:.0f}%)" for k, v in a["cats"].most_common()))
    print()

print("=" * 78)
print("LATEX per-model rows (bad-op errors per run, bare -> repair):")
for m in MODELS:
    cells = []
    for arm in order:
        pm = permodel[m].get(arm)
        if not pm or not pm["n"]: cells.append("--"); continue
        cells.append(f"{pm['badop']/(5*pm['n']):.1f}")
    print(f"{m:20s} & " + " & ".join(cells) + r" \\")
