# Live demo: 10-year CONUS precipitation from GDEX, computed on casper

Run-of-show for demonstrating the uxarray MCP server against data that never
leaves NSF NCAR. Every number below was measured on 2026-09-11 against endpoint
`ucar-uxarray-yac` (casper02).

---

## The claim being demonstrated

> Point an LLM at an HPC endpoint, name the files in English, get a publication-shaped
> map back — and be able to say afterwards exactly which function ran, on which host,
> under which PBS job, over which 14,600 time steps.

Three properties the audience should walk away with:

1. **The data never moves.** 10 files x ~3.75 GB = ~37 GB of 6-hourly CAM output stays
   on the GDEX filesystem. What crosses the wire is a ~110 KB PNG and a JSON record.
2. **The compute is where the data is.** uxarray runs on a casper worker via Globus
   Compute. The laptop has no uxarray-scale memory and never needs it.
3. **Every answer is auditable.** Each call returns `_provenance`: tool name, argument
   list, execution venue, remote hostname, PBS job id, operation id.

---

## Before the audience arrives

### 1. Restart the MCP server

The `temporal_mean` plot type was added this session. A server process started
before that edit will not expose it.

```
# in the client (Claude Code / Claude Desktop): restart the session so the
# uxarray MCP server re-registers its tool list
```

Confirm with a trivial call that `plot_dataset` accepts `plot_type="temporal_mean"`.

### 1b. Config prerequisites (both of these were wrong; both are demo-fatal)

In `~/.config/uxarray-mcp/config.yaml`, under `hpc.endpoints.ucar-uxarray-yac`:

```yaml
    ucar-uxarray-yac:
      endpoint_id: 79bf66fc-0507-42d0-a6bc-81628e9f1d77
      path_prefixes:
      - /glade/
      - /gdex/          # was missing — data lives here, not under /glade/
      timeout_seconds: 2400   # was 300 — the 10-year run takes 464 s
```

- **Timeout.** At 300 s the ten-year call raises
  `RuntimeError: Remote execution of temporal_mean_map timed out after 300 seconds`
  *after* the worker has already been doing the work. Now fixed to 2400.
- **Path prefix.** Only `/glade/` was listed. The GDEX data paths start `/gdex/`,
  match no prefix, and route to `default_endpoint`, which is **`chrysalis`** — the
  wrong machine, which cannot see these files at all. Now fixed.

**Still your call:** `default_endpoint` remains `chrysalis`. With the `/gdex/`
prefix added, path-based routing now sends this dataset to casper correctly, and
the demo prompts also name `endpoint="ucar-uxarray-yac"` explicitly, so it is
belt-and-braces. Switch the default only if you want *every* unqualified call
going to NCAR during the demo.

Harmless warning you will see and can ignore:

```
Environment differences detected between local SDK and endpoint ...
    SDK: Python 3.12.10/Dill 0.3.9
    Workers: Python 3.11.12/Dill 0.3.9
```

Serialization works across this pair. If someone in the room asks: the submitter
must be 3.12 for the serializer (globus/globus-compute#2139); the worker being 3.11
has not caused a failure in any run here.

### 2. Confirm the endpoint is warm

```
Check the status of the ucar-uxarray-yac endpoint with a worker probe.
```

Expected: `status: active`, node `casperNN`. If it reports `registered` only, the
manager is up but no worker is allocated yet — the first real call will sit in the
PBS queue. **Do one throwaway call before the audience arrives** so the worker is
already allocated; this is the difference between a 30 s demo and a 4-minute one.

### 3. Resolve the ensemble member (OPEN ITEM)

Orhan asked for **member #10**. Under
`/gdex/data/d651007/` only `...cesm-ihesp-hires1.0.30-1920-2005.002` and `.003`
exist for the 6-hourly atm stream. **All numbers in this document were measured on
`.002`.** Before the demo, run on casper:

```bash
ls -d /gdex/data/d651007/*/atm/proc/tseries/hour_6 | sed 's#/gdex/data/d651007/##;s#/atm.*##'
```

If a member #10 case name exists, substitute it in the prompts below; nothing else
changes. If it does not, say so on the slide — "this is member 002, the 010 stream
is not staged in the 6-hourly tier" is a perfectly good thing to say out loud, and
it is exactly the kind of fact the provenance record makes checkable.

### 4. Pre-bake the 10-year map

Run Act III once beforehand and keep the PNG. See the timing note in Act III.

---

## Act I — "what can this thing do with my data?" (~20 s)

**Say:** "I have not told it anything about this dataset. It is going to look at the
mesh and tell me which operations are even legal on it."

**Paste:**

```
Using the uxarray MCP server against the ucar-uxarray-yac endpoint, tell me what
I can do with this mesh:

  grid: /glade/p/cesmdata/cseg/inputdata/share/scripgrids/ne120np4_pentagons_100310.nc

Run get_capabilities remotely — the file is on the NCAR filesystem, not on my
laptop. Report the topology and which MCP operations apply.
```

**What comes back:** 777,602 faces / 780,456 nodes / 2,329,471 edges, SCRIP format,
and the applicable-tool list.

**Talking points while it runs:**

- This is a spectral-element ne120 mesh. The grid file presents GLL nodes as face
  centers, which is a quirk of how SE grids get written to SCRIP — uxarray reads it
  as 777,602 "faces" and everything downstream is consistent.
- ~0.25 degree. 777k cells is where the "just load it in xarray on your laptop"
  workflow starts to hurt.

---

## Act II — one year, live (~50-80 s)

**Say:** "Now the real question. One year first, so you can watch it happen."

**Paste:**

```
Compute the time-mean of PRECT over CONUS for 1979 and plot it.

  grid:  /glade/p/cesmdata/cseg/inputdata/share/scripgrids/ne120np4_pentagons_100310.nc
  data:  /gdex/data/d651007/b.e13.BHISTC5.ne120_t12.cesm-ihesp-hires1.0.30-1920-2005.002/atm/proc/tseries/hour_6/b.e13.BHISTC5.ne120_t12.cesm-ihesp-hires1.0.30-1920-2005.002.cam.h2.PRECT.1979010100-1980010100.nc

Use plot_dataset with plot_type="temporal_mean", use_remote=True,
endpoint="ucar-uxarray-yac". Subset to CONUS with lon_bounds=[-125,-67] and
lat_bounds=[24,50]. PRECT is in m/s — convert to mm/day with
scale_factor=86400000 and units_label="mm/day". Use cmap="YlGnBu",
width=1000, height=560, and draw coastlines. Then show me the provenance block.
```

**Measured:** 29.1 s calling the compute function directly; 51.4 s and 77.5 s through
the full MCP front door on two separate runs. 1,460 time steps (365 x 4, no-leap).

**Talking points while it runs:**

- 1,460 time steps of a 777k-cell field are being reduced on the worker. The mean is
  computed *after* the bounding-box subset, so only 23,510 cells — 3.02% of the mesh —
  are ever carried through the reduction.
- The `-125..-67` is not a typo. uxarray normalizes longitudes to −180..180, so the
  CONUS box is negative, not 235..293. Getting this wrong used to return an empty
  selection silently; the server now refuses with a message that names the convention.

**Then read the provenance out loud:**

```
tool:             remote_temporal_mean_map
execution_venue:  hpc:ucar-uxarray-yac
remote_hostname:  casper02
operation_id:     op_01417508a9d9
n_time_steps:     1460
n_face_subset:    23510 of 777602  (3.02%)
```

---

## Act III — ten years (7.7 min)

**Do not run this in silence.** 464 s is a long time in front of a room.

Two ways to play it, pick one:

**(a) Kick it off and talk over it.** Paste the prompt, then spend the eight minutes
on the architecture: function-by-value serialization, why no endpoint redeploy was
needed, the provenance record, the per-operation remote-support boundary. Come back
to the map when it lands. This is the honest version and it demos the real cost.

**(b) Show the pre-baked artifact.** Run it before the session, show the PNG and its
provenance JSON, and say "this took 7.7 minutes on one casper worker, here is the
record." Then run Act II live so they still see a live call.

**Paste:**

```
Same thing, but the full ten-year average: 1979 through 1988 inclusive, ten annual
files from the same directory (…PRECT.1979010100-1980010100.nc through
…PRECT.1988010100-1989010100.nc). Same CONUS box, same mm/day conversion, same
colormap and size, coastlines on. Report wall-clock, the number of time steps that
went into the mean, and the full provenance block.
```

**Measured (direct to casper, 2026-09-11):**

| quantity | value |
|---|---|
| wall clock | 464.4 s (7.7 min) |
| files read | 10 |
| time steps in the mean | 14,600 |
| time span | 1979-01-01 00:00 → 1988-12-31 18:00 |
| faces after subset | 23,510 of 777,602 (3.02%) |
| mean PRECT | 2.232 mm/day |
| min / max | 0.111 / 8.584 mm/day |
| non-finite cells | 0 |
| PNG returned | 112,475 bytes |
| PBS job | 5890924.casper-pbs |

**The science check — say this while pointing at the map:**

- Dry Great Basin and Desert Southwest.
- Wet Pacific Northwest and Sierra crest.
- Wet Gulf Coast, Southeast, and a clear Appalachian ridge signal.
- Maximum offshore over the Gulf Stream.
- 2.23 mm/day CONUS-average is the right order for a historical CESM run.

That the field registers correctly against the drawn coastlines is itself the
regression test — a longitude-convention bug would put the Sierra in Kansas.

---

## Numbers for the slide

### Wall clock

| what | time |
|---|---|
| capability query (Act I) | ~20 s |
| 1 year, direct compute function | 29.1 s |
| 1 year, full MCP front door | 51.4 s / 77.5 s |
| 10 years, full chain | 464.4 s |
| cold worker penalty (PBS queue) | add 1-4 min if not pre-warmed |

Per-year marginal cost is ~46 s, so the 10-year run is dominated by I/O over the
~37 GB of source data, not by the mesh operation.

### Bytes over the wire

| direction | payload |
|---|---|
| laptop → casper | the serialized function + arguments, a few KB |
| casper → laptop | 112 KB PNG (base64: ~150 KB) + ~3 KB JSON |
| what stayed put | ~37 GB of 6-hourly CAM output |

**This ratio is the demo.** ~37 GB read, ~115 KB returned — a factor of ~320,000.

### Token cost (approximate, per request)

| item | tokens |
|---|---|
| uxarray MCP tool schema, 31 tools | ~10,600 on *every* request |
| returned map, 1000x560 | ~750 image tokens |
| returned metadata + provenance JSON | ~750 |
| the prompt you paste | ~200 |

Honest framing for the room: the tool schema dominates. The interesting per-call
cost is small; the standing cost of having 31 tools registered is not. This is a
real argument for the front-door design — `run_analysis` and `plot_dataset` cover
most of the surface, and a narrower registered tool list would cut the standing
cost several-fold.

---

## Provenance: the part to linger on

Every call returns `_provenance`. Show the raw block on screen:

```json
"_provenance": {
  "tool": "remote_temporal_mean_map",
  "inputs": {"args": ["<grid path>", "[<10 data paths>]", "PRECT", ...]},
  "execution_venue": "hpc:ucar-uxarray-yac",
  "remote_hostname": "casper02",
  "remote_pbs_job_id": "5890924.casper-pbs",
  "operation_id": "op_..."
}
```

Alongside it, the result carries the reduction record itself:

```json
"reduced_dims": {"time": {"kind": "time", "how": "mean", "size": 14600}},
"subset_applied": true,
"lon_bounds": [-125.0, -67.0], "lat_bounds": [24.0, 50.0],
"n_face_total": 777602, "n_face_subset": 23510,
"value_stats": {"min": 0.111, "mean": 2.232, "max": 8.584, "n_nonfinite": 0}
```

The point to make: **a picture cannot tell you what was averaged away.** The PNG
alone cannot say whether you got one time step or 14,600, whether a level index was
silently taken, or whether the box selected anything. `reduced_dims`,
`n_face_subset` and `n_nonfinite` say it in the same response, so a wrong plot is
falsifiable rather than merely pretty.

Earlier remote calls available to cite as additional evidence:
`calculate_zonal_mean` → `op_37acf617bf97`; `plot_dataset(variable)` →
`op_51ce6b5bdb70`; both on PBS job `5890924.casper-pbs`.

---

## If something breaks live

| symptom | say this | do this |
|---|---|---|
| call hangs >2 min | "we are in the PBS queue — the worker is being allocated" | wait, or fall back to the pre-baked artifact |
| "timed out after 300 seconds" | config regression — the endpoint timeout is back at its default | the work may still be finishing on the worker; note the task id and move on |
| result comes back but paths look unreadable | routed to the wrong endpoint | check `execution_venue` in provenance — it must say `hpc:ucar-uxarray-yac` |
| `status: offline` | "endpoint manager is down" | ssh, `globus-compute-endpoint start ucar-uxarray-yac` |
| "does not support use_remote=True yet" | "remote support is per-operation, not global — that one still runs locally" | pick a different operation; do not retry |
| box selects no faces | "longitude convention — uxarray uses −180..180" | this is the guard working; use negative lon |
| `plot_type="variable"` refuses the box | "that plot type draws the whole mesh; it now refuses a box rather than silently ignoring it" | use `temporal_mean` |

The last two are worth *deliberately* triggering if the audience is technical. A tool
that refuses loudly is a better demo than one that always succeeds.

---

## What changed in the server to make this work

Worth one slide if the audience is uxarray developers:

- `remote_temporal_mean_map` in `remote/compute_functions.py` — new worker function:
  multi-file open, bbox subset before the reduction, time-mean, unit scaling,
  choropleth, Natural Earth geography overlay drawn from the worker's cartopy cache.
- `temporal_mean_map_remote` action in `remote/agent.py`, `temporal_mean_map`
  wrapper in `tools/remote_tools.py`.
- `plot_dataset` in `tools/frontdoor.py` gained `plot_type="temporal_mean"` plus
  `data_paths`, `scale_factor`, `units_label`, `region_name`.
- `plot_type="variable"` now **raises** on `lon_bounds`/`lat_bounds` instead of
  dropping them silently. That was a real bug: it returned a global map and nothing
  in the response said the box had been ignored.

**No endpoint redeploy was required.** Globus Compute's `AllCodeStrategies`
serializes function code by value (`remote/agent.py:200`), so a new worker function
ships with the task. This is a good thirty seconds of the talk — it is why iterating
on remote analysis code is cheap.
