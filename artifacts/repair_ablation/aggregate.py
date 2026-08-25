"""Aggregate the repair-naming ablation from evals/results/multi_turn_*.json."""
import json, glob, re, collections, sys

BADNAME = re.compile(r"Unsupported analysis operation '([^']+)'")

def load():
    recs = []
    for f in sorted(glob.glob('evals/results/multi_turn_*.json')):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for rep in d.get('reports', []):
            mid = rep.get('model_id', '')
            if '#' not in mid:
                continue
            model, arm = mid.split('#', 1)
            recs.append((model.replace('argo:', ''), arm, rep, f))
    return recs

def stats(rep):
    s = rep['summary']
    bad, allerr, guesses = 0, 0, []
    for run in rep['runs']:
        for e in run.get('errors', []):
            allerr += 1
            m = BADNAME.search(e)
            if m:
                bad += 1
                guesses.append(m.group(1))
    return dict(
        badname=bad, allerr=allerr, guesses=guesses,
        calls=s['mean_calls'], chained=s['chained'], tasks=s['tasks'],
        recovered=s['recovered'], fault_tasks=s['fault_tasks'],
        finished=s['finished'],
        invented=s['handles_invented'], dropped=s['handles_dropped'],
        overrides=s['overrides_used'],
    )

recs = load()
by = collections.defaultdict(dict)
for model, arm, rep, f in recs:
    by[model][arm] = stats(rep)

arms = sorted({a for m in by.values() for a in m})
print('arms found:', arms)
print()
hdr = f"{'model':22s}" + ''.join(f"{a:>28s}" for a in arms)
print(hdr)
print(f"{'':22s}" + ''.join(f"{'bad/all  calls chain rec':>28s}" for a in arms))
tot = {a: collections.Counter() for a in arms}
for model in sorted(by):
    line = f"{model:22s}"
    for a in arms:
        s = by[model].get(a)
        if not s:
            line += f"{'-':>28s}"; continue
        line += f"{s['badname']:>8d}/{s['allerr']:<4d}{s['calls']:>6.1f}{s['chained']:>4d}/{s['tasks']}{s['recovered']:>4d}/{s['fault_tasks']}"
        for k in ('badname','allerr','chained','tasks','recovered','fault_tasks','finished'):
            tot[a][k] += s[k]
        tot[a]['calls_sum'] += s['calls']; tot[a]['n'] += 1
    print(line)
print()
for a in arms:
    t = tot[a]
    if not t['n']: continue
    print(f"{a:10s} n={t['n']}  badname={t['badname']}  allerr={t['allerr']}  "
          f"mean_calls={t['calls_sum']/t['n']:.2f}  chained={t['chained']}/{t['tasks']}  "
          f"recovered={t['recovered']}/{t['fault_tasks']}  finished={t['finished']}/{t['tasks']}")
print()
# guess-loop distribution
for a in arms:
    dist = collections.Counter()
    runs_with_bad = 0
    for model in by:
        s = by[model].get(a)
        if not s: continue
        # per-report; recompute per-run
    for model, arm, rep, f in recs:
        if arm != a: continue
        for run in rep['runs']:
            g = [BADNAME.search(e).group(1) for e in run.get('errors', []) if BADNAME.search(e)]
            if g:
                runs_with_bad += 1
                dist[len(set(g))] += 1
    print(f"{a:10s} runs_with_badname={runs_with_bad}  distinct-guesses-per-run histogram={dict(sorted(dist.items()))}  max={max(dist) if dist else 0}")
