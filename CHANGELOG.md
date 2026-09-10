# Changelog

All notable changes are recorded here. Dates are ISO 8601 (UTC). The project
uses Semantic Versioning for public releases.

## Unreleased
### Fixed
- `inspect_variable` reported statistics over an unstated subset of a
  variable. `sst` returned `mean: 80.5`; the same field with 145 of its 162
  faces masked returned `mean: 153.0` in the same shape, with nothing saying
  the number describes 17 faces. A fully masked field returned
  `min/max/mean: nan` — not valid JSON — after emitting three
  `RuntimeWarning: All-NaN slice encountered` on stderr the caller never
  sees. Statistics are now taken over a boolean index of the finite entries;
  a partly masked variable also reports `n_finite` and `n_total`, and a field
  with nothing finite reports `null` rather than `nan`. Integers and booleans
  carry no missing value to skip and keep the plain reductions with no extra
  keys, matching `summarize_array`.
- `mesh_coverage` never reached a result computed on HPC, so `MESH_NOT_GLOBAL`
  could not fire on any remote reply whatever the mesh. `AllCodeStrategies`
  ships one function's code and nothing else, so the worker has no
  `uxarray_mcp` to import; the measurement is now nested inside
  `remote_inspect_mesh` and `remote_calculate_area`, following the same
  worker-side inlining already used for `profile_coverage` and
  `source_coverage`. `tests/test_remote_mesh_coverage.py` compares the three
  copies key for key on a global mesh, a regional patch and a polar-hole grid,
  which is the only thing standing between them and drift.
- Every result computed on HPC failed its own response contract.
  `_run_on_hpc` stamps `tool=func.__name__`, so a worker reply arrived as
  `remote_calculate_area`; nothing declares a contract under that name, so
  `attach_provenance` skipped the required `operation` field and
  `validate_response("calculate_area", ...)` answered
  `{missing_fields: ["operation"], verdict: "malformed_envelope"}` for a reply
  whose science was fine — and an SDK validating `structuredContent` against
  the published schema rejects such a reply outright. The four `remote_*`
  functions now alias to the operations they answer, and `operation` names the
  contract rather than the venue, which is already in `_provenance`.
- `export` claimed success without checking anything. The three export
  functions contained no `stat`, `getsize` or `nbytes` call, so
  `status: "complete"` meant `to_csv` returned without raising, and
  `rows_written` was `len(frame)` read off the in-memory DataFrame. Measured
  on a 9-face dataset: CSV dropped all 8 attributes, including every unit,
  and wrote its one NaN as an empty field with no sentinel and no mention;
  single-variable NetCDF export dropped `salinity` and the CF `crs` container
  while leaving `sst` pointing at it, so the file references a coordinate
  reference system it does not contain. Exports now return an
  `export_fidelity` block measured on the written file — `bytes_written`,
  `rows_written` against `rows_expected`, `variables_dropped`,
  `attributes_dropped`, `missing_values` with `missing_written_as`,
  `dangling_grid_mapping` — and raise `EXPORT_ATTRIBUTES_DROPPED`,
  `EXPORT_MISSING_VALUES_UNMARKED`, `EXPORT_VARIABLES_DROPPED`,
  `EXPORT_DANGLING_GRID_MAPPING`, `EXPORT_ROW_COUNT_MISMATCH` or
  `EXPORT_EMPTY_FILE`. The file is still written and its path still returned;
  a lossy export is the export that was asked for, and only the silence was
  wrong. The datasets the exporters opened are now closed.
- Nothing in an area result said how much of the sphere it was summed over. A
  5-degree mesh spanning 0-40E/0-40N with `sphere_radius: 6371000.0` returned
  `total_area: 22936016715559.137 m^2` — 4.4967% of `4*pi*R^2` — with
  `scientific_status: complete`, `physically_interpretable: true`, no warning
  code, and a bare `postconditions: {status: not_evaluated, checks: []}`; the
  identical call on a global mesh returned 1.0000 of the sphere with the same
  status shape. `calculate_area` and `inspect_mesh` now both carry a
  `mesh_coverage` block: `sphere_fraction`, `closed`, `euler_characteristic`,
  `lon_extent`, `lat_extent`. A patch raises `MESH_NOT_GLOBAL` and drops to
  `warning` but stays interpretable, because its total is a real physical
  quantity and only the missing disclosure was wrong. The geometric and
  topological halves are reported separately and are allowed to disagree: a
  1-degree structured global grid stops half a cell short of each pole, so it
  reads `sphere_fraction: 0.999963` with `closed: false` and 720 boundary
  edges, which is honest on both counts and not a regional patch. Counting
  edge incidences is a Python loop — 1.43 s at 196,608 faces, 5.99 s at
  786,432 — so above 250,000 faces the topological half is skipped and
  `closed` comes back `null` with `topology_skipped` giving the reason,
  never `false`.
- An abstained postcondition now says why it abstained. The area identity
  holds only on a closed mesh, so a regional result came back
  `{status: not_evaluated, checks: []}` and the payload never distinguished
  that from a deployment running `verdict_policy: off`. The block now carries
  `not_evaluated_because` when the server can name a reason, read off
  `mesh_coverage` so naming it costs no second traversal of the mesh.
- The response contract described a payload the server does not send. It
  declared a top-level `physically_interpretable` boolean that no code path
  emits — every producer nests that verdict inside `scientific_status` — and
  did not declare `scientific_status` at all. Measured across four operations,
  0 of 4 results carried the declared field and 4 of 4 carried the block it
  lives in, so `validate_response` reported the server's own envelope
  (`outcome`, `scientific_status`, `preconditions`, `postconditions`,
  `recommended_next_steps`, `_provenance`) back as *extra* on every call. All
  six are now declared, optional because a refusal is a different shape, and
  the per-operation `outputSchema` reuses the front door's own definitions
  rather than restating them more weakly. `calculate_area` also declares
  `area_basis` and `calculate_zonal_mean` declares `profile_coverage`, the two
  blocks that say what the number rests on.
- Non-finite floats no longer reach the wire. JSON has no `NaN` or
  `Infinity`; `json.dumps` writes them as bare tokens unless told otherwise,
  and `structuredContent` never passed through `json.dumps` at all — the live
  dict went to pydantic. Measured: a zonal mean over a half-masked field
  returned 19 latitude bands, every one `NaN`, and
  `json.dumps(result, allow_nan=False)` raised `Out of range float values are
  not JSON compliant: nan`, so a strict decoder in any other language lost the
  whole response rather than those bands. Results are now sanitized at
  registration, the one point every tool passes through, and an undefined
  value is written as `null` — still reported, still the same length as
  `latitudes`, no longer poisoning everything around it. Called in-process,
  `run_analysis` still returns `NaN`, which is the honest value for a Python
  caller; the conversion belongs at the JSON boundary and a test pins it there.

- `calculate_area` returned steradians for every grid, including grids that
  declare an Earth radius. `Grid.sphere_radius` is a property reading
  `_ds.attrs.get("sphere_radius", 1.0)` and nothing in UXarray's area path
  consults it, so a 648-face global mesh summed to `12.566371` — `4*pi` — with
  `area_units: null` and no warning, and a file declaring
  `sphere_radius: 6371000.0` round-tripped and still summed to `12.566371`.
  The tool's own docstring promised `5.10064e14`, which it never returned.
  Areas are now scaled by `R^2` from an explicit `sphere_radius` argument or
  from the grid's declaration, and an `area_basis` block reports the radius,
  its source and whether it was applied. With neither source the call refuses
  instead of returning a number that is not an area. Measured after the fix:
  `510064487992182.1` against a `4*pi*R^2` reference of `510064471909788.25`,
  a relative residual of 3.15e-8.
- A grid-declared radius no longer implies metres. The file supplied a number,
  not a unit, so that path keeps `area_units: null`, warns
  `AREA_UNITS_UNDECLARED` and is not marked physically interpretable; only a
  caller-supplied `sphere_radius`, which is documented as metres, sets
  `area_units: "m^2"`.
- Spatial selections now say which rule chose the faces. The three operations
  do not agree: `subset_polygon` selects by face centre, `cross_section` by
  intersection, and `subset_bbox` keeps a face only when its whole spherical
  footprint fits inside the box. That last one is much stricter than the name
  suggests — measured on an 81-face mesh of 5-degree cells, a box of lon 5–15 /
  lat 5–15 holds six face centres and returns one face, and the surviving face
  spans latitude 7.5000–12.5115 because the great-circle edge bulges poleward
  of the nodes it joins. `subset_coverage` now carries `selection_rule`, and for
  `subset_bbox` also `n_face_centers_in_bounds`, so the gap between what a
  caller asked for and what the geometry allowed is visible. Dropping boundary
  faces happens on every bounding-box call, so it is reported and not warned
  about.
- A bounding box that lands on the mesh and still selects nothing was told to
  move onto the mesh, which is where it already was. A box narrower than one
  face returns nothing while sitting on top of the mesh — measured at lon 6–11 /
  lat 6–11, one face centre inside and zero faces returned. That case now gets
  its own repair: widen the box, or use `subset_polygon`, which selects by
  centre.
- Array summaries no longer report NaN for every statistic as soon as one
  value is missing. `summarize_array` called plain `min`/`max`/`mean`, which
  propagate NaN, so a field masked over half its faces returned `min`, `max`
  and `mean` all NaN while three faces held finite values — and land masks are
  ordinary in this data, so that was most fields. The statistics now skip
  non-finite entries, report `None` rather than NaN when nothing is finite, and
  add `n_finite`/`n_total` only when the two differ, so a complete field costs
  no extra bytes. An infinity counts as missing rather than as an extreme,
  since a maximum of `inf` is not a measurement.
- The same payloads were not valid JSON. `json.dumps` writes NaN as the bare
  token `NaN`, which no JSON parser is required to accept, so a strict client
  rejected the whole result rather than the one number: measured with
  `json.loads(..., parse_constant=...)`, which raised on `{"min": NaN}`.
- `temporal_mean` and `anomaly` now say how much time they averaged over.
  Measured on a 6-element, 12-step file: a variable missing at every step
  returned `outcome: complete`, `status: complete`, no warning codes and a
  full-length field of NaN; a one-step file returned a "temporal mean" that was
  the value and a "temporal anomaly" of exactly `0.0` at every element, which
  is what that operation returns for any data whatsoever; and a file holding 1,
  2 and 12 usable steps at different elements returned a single finite
  min/max/mean mixing all three. Results now carry a `temporal_coverage` block
  with `n_time`, `samples_min`/`samples_max`, `n_elements_with_value`,
  `n_series_with_data` and, under `groupby`, `n_bins` with
  `bin_occupancy_min`/`bin_occupancy_max`.
- An empty mean fails `temporal_coverage_nonzero` and returns the refusal
  payload with no number; a single-step baseline fails
  `anomaly_baseline_multisample` on `anomaly` alone. A single-step
  `temporal_mean` only warns, because the value it returns was measured and
  only the word "mean" is wrong. `TEMPORAL_SAMPLES_RAGGED` fires on elements
  averaged over different numbers of steps, excluding elements that never held
  data so a land-masked field stays quiet, and `TEMPORAL_BINS_SINGLE_SAMPLE`
  fires when a `groupby` bin holds one step — a monthly climatology built from
  three months is three single observations.
- `subset_bbox`, `subset_polygon` and `cross_section` now refuse a selection
  that kept no faces. A bounding box at 160-170W / 70-80S applied to a mesh
  covering 0-40E / 0-40N returned `outcome: complete`, `status: complete`, no
  warning codes, a `subset_grid` of `n_face: 0`, a `variable_summary` of
  `shape: [0]`, a persisted artifact and a recommended-next-steps list telling
  the caller to plot it. `subset_polygon` did the same with
  `selected_face_count: 0`.
- All three report a `subset_coverage` block with `n_face_source`,
  `n_face_retained` and `source_extent`. There is no partial warning: keeping
  fewer faces is what a subset is for, and a code that fires on every
  successful call teaches callers to ignore it. The refusal names the argument
  the caller controls and quotes the longitude and latitude the mesh spans,
  because "nothing selected" does not say where to put the box.
- `cross_section` no longer surfaces UXarray's `No intersections found at
  lat=...` as a raw error. That message says the line found nothing without
  saying where a line would find something, so it becomes the same refusal
  with the mesh extent attached. Any other `ValueError` still propagates.
- `zonal_anomaly` now says how much of the anomaly field the band means
  actually defined, and refuses when they defined none of it. The anomaly is
  a per-face field rather than a binned profile, so the bin coverage added for
  `calculate_zonal_mean` did not apply and the loss stayed invisible: a band
  mean is undefined as soon as one face in the band is missing, and every face
  in that band comes back NaN including faces that carried a value. Measured on
  a 90-face regional mesh, one missing value per latitude band emptied all 90
  faces while 85 of them held data, and the result was `outcome: complete`,
  `status: complete`, no warning codes, and `stats` of `{min: null, max: null,
  mean: null, std: null}`. The partial case was quieter still — 30 faces with
  data, 18 anomalies returned, 12 measurable faces dropped, and finite
  min/max/mean/std computed from the survivors.
- Results now carry an `anomaly_coverage` block with `n_face`,
  `n_face_with_data`, `n_face_with_anomaly`, `n_face_data_lost` and `cause`.
  `ANOMALY_COVERAGE_PARTIAL` fires on lost faces rather than on empty ones, so
  an ordinary land-masked field does not warn on every call; a face that had
  data and no anomaly is a deduction from `value - band_mean`, not a guess.
  Zero coverage fails `anomaly_coverage_nonzero` and returns the refusal
  payload with no number. The repair names the missing values rather than
  `lat_spec` when faces did carry data, because no choice of bands can avoid a
  gap that is in every band; when nothing was measurable it names the variable
  and the time/level slice instead.
- The `file://` links returned for large figures are now fetchable. A figure at
  or above the inline payload limit is written to the artifact store and handed
  back as an MCP `resource_link`, which is the right trade — base64 inflates the
  bytes by a third and a multi-hundred-kilobyte PNG costs far more of the
  caller's context than the picture is worth. But the link went out over a
  server advertising no `resources` capability and serving neither
  `resources/list` nor `resources/read`: measured on the core profile, the
  capability was `None` and the handler table held no resource method at all.
  A client that followed the link the way the spec says to got
  `METHOD_NOT_FOUND`; one that did not follow up lost the figure. Over `sse` or
  `http` the path was never openable in the first place, since the client does
  not share a filesystem with the server. Both methods are now registered on
  both server construction paths, so the surface the tests exercise is the
  surface the CLI serves.
- Reading is confined to the artifact directory and the confinement is checked
  after `resolve()`, which collapses `..` and follows symlinks. A URI outside
  the store, a non-`file://` scheme, or a `file://` URI naming another host is
  refused rather than clamped: a caller asking for `/etc/passwd` is not making
  a repairable mistake.
- `resources/list` is paginated at 100 artifacts per page. The store is
  append-only in practice and unbounded in principle — 1258 files and 212 KB of
  listing JSON on one developer machine — so an unpaged listing would be the
  same swallow-the-context mistake the inline payload limit exists to prevent,
  arriving through the protocol instead of through a tool result. Paging
  resumes by artifact name rather than by offset, because tools write into the
  store and cleanup deletes from it while a client is paging, and an offset into
  a list that shrank silently steps over entries. A cursor the server did not
  issue is rejected rather than treated as "start over", which would look to the
  client like forward progress.
- The declared floor for PyYAML rises from 6.0 to 6.0.1. PyYAML 6.0 publishes
  no wheel for CPython 3.12 and its sdist fails to build against a modern
  Cython with `'build_ext' object has no attribute 'cython_sources'`, so the
  weekly `lowest-direct` job in the upstream-compatibility workflow had failed
  on install every run since 2026-08-10 — the floor we advertise as supported
  could not be installed at all on the Python CI uses. Ordinary CI never saw
  it, because it resolves to the newest PyYAML.
- The upstream-compatibility workflow now runs its test suite with
  `uv run --no-sync`. Both of its jobs install a specific set of versions —
  `uv pip install --upgrade` for the latest of each dependency, or
  `uv sync --resolution lowest-direct` for the declared floors — and then ran
  pytest through a bare `uv run`, which re-syncs the environment to `uv.lock`
  before executing and reverts the install. Measured: after
  `uv pip install --upgrade pyyaml==6.0.1`, a bare `uv run` reports `6.0.3`
  (the locked version) while `uv run --no-sync` reports `6.0.1`. Every green
  run of this workflow so far showed only that the lockfile passes its own
  suite, which is what the rest of CI already proves. The declared floors do
  pass on their own: 764 passed, 14 skipped against mcp 1.24.0,
  toolregistry-server 0.5.0, uxarray 2026.8.1, holoviews 1.19.0 and
  matplotlib 3.9.0.

- `docs/operating-an-endpoint.md` documented `authentication_policy` as a
  nested mapping with `allowed_identities` under it, in two separate blocks
  including the single-user quickstart. Following it fails endpoint startup
  with `(ClickException) 2 validation errors for BaseConfig.__init__ /
  authentication_policy.uuid / authentication_policy.str`: the field takes one
  Globus Auth policy UUID as a scalar, `high_assurance` is a separate
  top-level key, and `allowed_identities` is a property of the policy object
  in Globus Auth, not an endpoint config key. A single-user endpoint needs no
  policy at all, so the quickstart no longer suggests one. The two
  `config.yaml` files are now named apart where the confusion starts:
  `~/.globus_compute/uxarray/config.yaml` is the endpoint daemon's and holds
  no user UUID; `~/.config/uxarray-mcp/config.yaml` is the client's and is
  where `endpoint_id` goes.

### Changed
- Require `uxarray>=2026.9.0` (was `>=2026.8.1`), in `pyproject.toml` and the
  conda recipe. Every release below it answers `gradient`, `curl` and
  `divergence` with the wrong number: the Green-Gauss gradient divided by the
  primal face area while the contour integral walked the dual cell, inflating
  the result by `A_dual/A_primal` — roughly 4x on quads and 3x on hexagons —
  and `curl` and `divergence` separately dropped the `±u·tan(lat)/a` spherical
  metric terms (UXarray #1663). Both are fixed together in 2026.9.0, whose
  median ratio to the closed-form answer is within 0.5% across HEALPix z4-z6,
  ne30pg2 and QU480. This server exposes all three operations, so the floor is
  the only thing that stops it publishing those numbers. The suite passes
  unchanged against 2026.9.0: 1005 passed, 5 skipped.
- Require `mcp>=1.27` (was `>=1.24`), and drop the pre-1.27 registration path
  for the artifact resources. 1.27 removed `Server.add_request_handler`, so on
  the current SDK the old branch was dead code and only the
  `@server.list_resources()` / `@server.read_resource()` decorators registered
  anything; carrying both meant an install below the floor would serve no
  artifacts at all rather than fail at install time. The conda recipe said
  `mcp >=1.20,<2` where `pyproject.toml` said `>=1.24,<3`; both now say
  `>=1.27,<3`. `tests/test_artifact_resources.py` reads the SDK's own handler
  table — keyed by request type, unwrapping the `ServerResult` — instead of
  probing for whichever generation of the API was present.

### Added
- `tests/test_documented_snippets.py` parses every fenced `yaml` and `json`
  block in `README.md` and `docs/*.md`, so a config snippet that cannot load
  fails CI rather than a new user's first hour. It checks that the endpoint
  keys documented as scalars are written as scalars, that the client config
  path in the docs is the `USER_CONFIG_PATH` the code reads, and that the
  MCP client snippets invoke the console script that is actually installed.
  It found a second bad `authentication_policy` block on its first run.
- Setup sections for Codex CLI, opencode and Cursor in `README.md`, each with
  the config file that client reads and the shape it expects — `command`/`args`
  under `[mcp_servers.uxarray]` for Codex, an argv list under `mcp` for
  opencode, `mcpServers` for Cursor. The README previously named Claude and
  left every other MCP client a one-line stub.
- `scripts/measure_payload.py` says where a reply's bytes go, which
  `tests/test_payload_budget.py` can only pass or fail on. It shares the
  budget test's fixtures so a figure printed here and a budget asserted there
  describe the same payload, and reports per-key and per-category
  breakdowns plus the tool catalog. Pooled over five replies: 8199 bytes,
  28.9% answer, 26.2% provenance, 24.8% checks, 12.6% advice, 6.1% status.
  Token counts are printed only when `tiktoken` is installed, and the
  encoding is named; they are never estimated from a bytes-per-token
  constant, which moves with how much of a payload is JSON punctuation and
  would be wrong for every caller who does not share the guess.

## 0.3.1 — 2026-09-05
### Fixed
- `calculate_zonal_mean` and `azimuthal_mean` now count how many of their bins
  the mesh actually filled. A mesh spanning 0–40N asked for bands at −70 and
  −60 returned `[nan, nan]` as `outcome: complete`, `status: complete`, with no
  warning codes — a profile of the requested length is shaped exactly like an
  answer. A radial profile centred off the mesh did the same, and even an
  on-mesh centre left 4 of 6 rings empty without saying so. An entirely unfilled
  profile now refuses through the front door with a repair naming the argument
  that caller controls (`lat_spec`, or `center_lon`/`center_lat` and
  `outer_radius`); a partly filled one warns with `PROFILE_COVERAGE_PARTIAL`,
  since a regional mesh legitimately fills only the bands it spans. The count
  is taken from the returned profile rather than by re-deriving bin membership,
  which would duplicate UXarray's binning and could disagree with it — so the
  source field is checked too, and an empty bin is attributed to the bins
  missing the mesh only when the field itself is known to be complete. The
  `calculate_zonal_mean` payload budget rises from 2050 to 2250 bytes to carry
  the block and its repair text.
- `ensemble_mean` and `ensemble_spread` now check what the members declare
  before averaging them. A member in K and a member in degC returned `145.0`
  with `outcome: complete`, `preconditions: not_evaluated` and no warning
  codes — a number in neither scale, presented as an answer. Averaging across
  members is the same arithmetic as differencing two fields and fails the same
  way, so a declared unit disagreement now refuses through the same front-door
  gate, with `acknowledge` available as it is elsewhere. Undeclared units stay
  a warning (`ENSEMBLE_UNITS_UNDECLARED`), since a gap in metadata is not a
  contradiction. The mesh check is separate and deliberately weaker: members
  are opened as plain datasets with no grid path, so identity rests on
  whatever coordinates the files carry, and when they carry none the result
  says `ENSEMBLE_GRID_UNVERIFIED` rather than claiming agreement — two
  unrelated meshes with the same face count would otherwise pass. Both
  operations return a `member_evidence` block reporting the per-member units,
  the two three-valued verdicts, and whether the mesh was compared on
  coordinates or on dimensions alone.
- `remap_variable` and `regrid_dataset` now measure how much of the target
  mesh the source mesh actually reaches, as `remap_to_rectilinear` already
  did. Nearest-neighbour returns a value at every target point whether or not
  the source is anywhere near it, so a 1x1 degree source remapped onto a
  target ten degrees away came back `outcome: complete`, `preconditions:
  not_evaluated`, no coverage reported, and a full array of plausible numbers
  that were all extrapolation. Both operations now report `source_coverage`
  and refuse at zero coverage through the same front-door gate. The repair
  text is operation-aware: the two grid-to-grid operations are told to pass an
  overlapping `target_grid_path` and to check the longitude convention, rather
  than to adjust `target_lon`/`target_lat`, which their callers never pass.
  Coverage for an unstructured target pairs its coordinates instead of
  multiplying them out, because the cartesian product would invent points the
  target does not have. A grid that does not expose the coordinates leaves
  coverage unknown, which is reported as absent rather than as full.
- The monthly release job relocks `uv.lock` and closes the `Unreleased`
  changelog section under the new version. It bumped `pyproject.toml`,
  `__init__.py` and the conda recipe and committed only those, so every tag
  carried a lockfile still naming the previous release — invisible in CI,
  which never passes `--locked`, and an error for anyone who checks out the
  tag and runs `uv sync --locked`. The changelog had the matching gap: a
  release shipped with its own notes still filed as unreleased, so the
  published version had none and the next one inherited them. Stamping is
  idempotent, because the release job is retryable.
- The radius-scaling precondition on `curl` and `divergence` read whether
  scaling was *requested*, not whether it was *applied*. UXarray honours
  `scale_by_radius=True` as far as it can on a grid that declares no
  `sphere_radius`: it warns that the result is left on the unit sphere and
  returns it anyway. The request alone therefore satisfied the gate, so a
  vorticity per radian came back labelled s^-1 — carrying
  `SPHERE_RADIUS_UNAVAILABLE` and `physically_interpretable: false` beside the
  number, which is the warning-that-changes-nothing state #86 exists to end.
  The check now reads the applied flag, and its repair names the missing
  attribute instead of telling a caller to set a flag they already set.
- `gradient` was left out of the precondition gate entirely, though it takes
  the same derivative on the same sphere and the domain layer already recorded
  the same `SPHERE_RADIUS_UNAVAILABLE`. It is now gated on radius scaling like
  the other two. The component checks do not apply to it: a gradient is taken
  of one field, so distinctness, velocity units, and eastward/northward
  identity have nothing to read.
- The test suite can no longer report green against stand-ins. `conftest`
  substitutes `MagicMock` for uxarray so the pure-logic tests run on a bare
  checkout, but it did so on any `ImportError` — including one raised from
  *inside* a uxarray that is installed and broken, such as a moved optional
  import or a binary built against the wrong NumPy. A MagicMock returns a
  MagicMock for every attribute and call, so that run passes nearly everything
  it asserts and is indistinguishable from a real one. `importlib.util.
  find_spec` now separates "not installed" from "installed but broken", and
  `tests/test_suite_integrity.py` fails outright on a mocked run and on an
  installed uxarray below the floor declared in `pyproject.toml`.
- `scripts/chrysalis_endpoint.sh` prints the real uxarray import failure and
  refuses to start instead of sending stderr to `/dev/null` and echoing
  "check import". That message was the same whether uxarray was missing, built
  against the wrong NumPy, or shadowed by a stale `~/uxarray` checkout, and the
  endpoint started anyway — so the failure surfaced on the first submitted task
  rather than at the point it could be read and fixed.
- `compare_fields`, `calculate_bias`, `calculate_rmse` and
  `calculate_pattern_correlation` area-weight their metrics. They previously
  called `.mean()` over the face dimension, which answers "average over
  cells", not "average over the sphere" — the two differ whenever cell areas
  do. On a 10° lat-lon mesh (648 faces, largest cell 11.5× the smallest) with
  a +2 K tropical / −2 K polar difference, the old code reported a bias of
  −0.667 K where the area-weighted answer is +0.004 K: wrong magnitude and
  wrong sign. Results now carry an `area_weighting` block naming the face
  dimension and the max/min area ratio. When weighting is impossible — no
  grid supplied, a non-face-centered field, or unavailable face areas — the
  result says so through `scientific_status` with the
  `AREA_WEIGHTING_UNAVAILABLE` code rather than presenting a cell-count mean
  as a spatial one.

### Changed
- **Breaking:** the payload field `result_type` is now `outcome`. Its values
  are unchanged (`complete`, `input_required`). The SDK stamps a
  protocol-level `resultType` on every JSON-RPC result object, always
  `"complete"` because the call did return, so a refusal put two fields with
  the same name and contradicting values on one wire, separated only by
  camelCase. A client reading either one could reasonably conclude the other
  was wrong. The two are now distinguishable: `resultType` reports that the
  call returned, `outcome` reports which of the two payload shapes came back.
  The constants moved with it: `RESULT_TYPE_COMPLETE` and
  `RESULT_TYPE_INPUT_REQUIRED` are now `OUTCOME_COMPLETE` and
  `OUTCOME_INPUT_REQUIRED`.
- The `run_analysis` `outputSchema` now requires the scientific contract
  fields per result branch instead of promising almost nothing. A result with
  `outcome: "complete"` must carry `scientific_status`, `preconditions`
  and `postconditions`; a result with `outcome: "input_required"` must
  carry `refusal`, `input_requests` and `request_state`. Both shapes share one
  schema, so a flat `required` list could only hold their intersection --
  `outcome` alone -- which left a validating client unable to rely on
  anything else being there. The front door has always emitted these; the
  schema now says so, which is what makes a number and the judgment of whether
  it means anything travel together. The refusal fields are also declared as
  properties for the first time: the schema described them in prose and never
  named them.
- Require `uxarray>=2026.8.1` (was `>=2026.8.0`), in `pyproject.toml` and the
  conda recipe. 2026.8.0 matched structured-grid nodes in the lon/lat plane
  rather than in Cartesian space, so the `nlon+1` nodes at each pole and the
  two sides of the antimeridian were never identified with each other
  (UXarray #1690). A global grid therefore carried phantom nodes and was not
  a closed surface: on a 10° mesh, 703 nodes instead of 614 and `V - E + F`
  of 1 instead of 2; on 1°, 65341 instead of 64442. `inspect_mesh` reports
  `n_node` and `n_edge` straight from the grid, so it was returning those
  inflated counts — 190 rather than 146 on this project's own structured
  fixture, 23% high. Face areas are unaffected: the area ratio and the
  `4*pi` total are identical across the two releases, because the defect is
  in node identity rather than in the metric. Also picked up in 2026.8.1:
  Dask-backed data is no longer silently realized as NumPy inside the core
  routines (#1588), and `UxDataset.isel(..., ignore_grid=True)` no longer
  crashes (#1684).

### Added
- Conformance tests that drive the real front door and validate whatever comes
  back against the `outputSchema` the server publishes for it, for a completed
  analysis, a refusal, four single-dataset operations and a comparison. The one
  test that existed validated a hand-built dict, which proves the schema is
  well formed and cannot prove we honour it, because the fixture and the schema
  were written to match. Two negative cases assert the schema rejects a
  complete result with no `scientific_status` and a refusal with no repair
  path, so a branch condition that matched nothing would fail rather than pass
  everything. `jsonschema` is now a declared dev dependency for the same
  reason: it arrives transitively today, and a resolver change would have
  turned these checks into a green no-op.
- `inspect_mesh` has a regression test asserting Euler's formula on a global
  mesh. The whole suite passed unchanged against both 2026.8.0 and 2026.8.1
  — 710 passed, 4 skipped either way — because nothing asserted a node count
  on a grid that wraps the globe, so an open sphere and a closed one looked
  the same from here. `V - E + F == 2` is the cheap invariant that separates
  them.
- Comparisons declare a `units_comparable` precondition. `bias`, `rmse` and
  the difference field are all `a - b`, which is a physical quantity only
  when both sides are on the same scale; comparing a field in K against one
  in degC previously returned 273.15 with nothing to distinguish the unit
  offset from model error. Through `run_analysis` a declared, unresolvable
  disagreement now refuses with a repair, and the `acknowledge` token still
  returns the number for a caller who means it. Undeclared units are a gap in
  the metadata rather than a contradiction, so they warn (`UNITS_UNDECLARED`)
  instead of refusing — comparing two unlabeled anomaly fields is ordinary.
  `normalize_units` resolves a fixed synonym table (`K`/`kelvin`, `m/s`/
  `m s-1`) but does no unit algebra, so equivalent-but-unaliased spellings
  such as `mm day-1` against `kg m-2 s-1` refuse and say so in the repair.

## 0.3.0 — 2026-08-29

Everything below landed after 0.1.2; the 0.2.x releases were cut without
stamping a section here, so this heading closes that gap as well as naming
the current release.

### Changed
- `UXarrayApp.serve_mcp` constructs the MCP adapter itself so the
  `tools/list` cache hints reach the server. The inherited path
  (`App.serve` → `MCPAdapter.create_and_run`) builds the adapter internally
  and silently drops `list_tools_ttl_ms`/`list_tools_cache_scope`, so the CLI
  — the path users actually run — advertised the SDK default of `ttlMs=0`,
  i.e. immediately stale, re-listing the whole catalog every turn. The hints
  do reach the wire: `mcp` 2.1.1 has
  `MODERN_PROTOCOL_VERSIONS == ("2026-07-28",)` and `ListToolsResult`
  inherits `CacheableResult`, so any client on the modern transport sees
  them. Only the legacy `initialize` handshake caps earlier, at 2025-11-25,
  and there the SDK strips them harmlessly.
- Removed `attach_resource_link` and the `_resource_links` key it wrote. It
  had no production caller, and its docstring claimed the adapter reads that
  key, which was never true.
- Require `uxarray>=2026.8.0` (was `>=2026.7.0`), in `pyproject.toml` and the
  conda recipe. 2026.7.0 and earlier compute face areas with an incorrect
  Jacobian (UXarray #1646), so the floor now excludes versions that can return
  wrong areas rather than leaving it to chance. Measured on this project's
  HEALPix z2 and 162-face structured fixtures, face areas are bit-identical
  across the two releases — the Jacobian defect does not reach these grid
  types — but the floor is set on what a release can compute, not on what our
  fixtures happen to exercise.
- `recommended_next_steps` no longer interpolates the caller's own file paths
  into every suggestion. A four-step list used to repeat the same absolute
  path four times; on an MPAS QU480 mesh those echoed paths alone were 28% of
  an `inspect_mesh` result and 36% of an `inspect_variable` result, more bytes
  than every computed number in either reply. Steps now reference a
  caller-supplied value by parameter name (`plot_mesh(grid_path)`), spell out
  only values the server discovered (`plot_variable(grid_path, data_path,
  "temperature")`), and bracket what is still missing (`<data_path>`). Results
  shrank 18-34% and the computed answer went from 25-49% of a payload to
  39-61% (#83).

### Fixed
- `divergence` accepts and forwards `scale_by_radius`. UXarray's
  `UxDataArray.divergence` takes the flag exactly as `gradient` and `curl` do,
  but every layer here called it bare — `domain/vector_calc.py`,
  `remote/compute_functions.py`, the agent, and the `run_analysis` front door,
  which accepted the parameter and dropped it. A caller asking for
  unit-sphere divergence silently got radius-scaled output, and the result
  never disclosed which it was: no `scale_by_radius` key, no
  `physical_scaling_requested`/`applied` in `scientific_status`. Divergence
  now reports both, and — like `curl` — declares the `radius_scaling`
  precondition, so unscaled output is refused rather than returned as if
  physical. Same class of defect as #87.
- `time_index` no longer selects the vertical level. Every dimension that was
  not a face dimension was reduced with `time_index`, so on a field shaped
  `(time, lev, n_face)` a request for time step 3 silently returned level 3 as
  well — a plausible-looking number from the wrong slice, with nothing in the
  output saying so. The two selectors are now distinct: `time_index` reaches
  only time-like axes, `level_index` only vertical ones, and anything else
  (an ensemble member) takes index 0 because neither selector says anything
  about it. Classification lives in one place, `uxarray_mcp.domain.dims`, so
  the plotting, vector-calculus and zonal paths cannot drift on what counts
  as a time axis; the Globus Compute worker keeps hand-inlined copies because
  module-level helpers do not survive its serialization, and tests pin those
  copies to the local behavior.
- `level_index` is reachable from the tools that need it. It existed in the
  renderer but no tool accepted it, so every plot and profile of a
  multi-level field was pinned to level 0 with no way to ask for another. It
  is now accepted by `plot_dataset` (variable and zonal-mean),
  `run_analysis(calculate_zonal_mean | azimuthal_mean)`, and their remote
  equivalents. A vertical axis is also recognized by substring rather than an
  exact-name list, which had been missing the common real spellings —
  `n_level`, `nlev`, `num_levels` — including this project's own multi-level
  fixture.
- Results say which slice they show. `reduced_dims` names each collapsed
  dimension, the index used, and how many were available; `plot_variable`
  computed it and then dropped it on the way out, so a PNG of level 0 of a
  four-level field looked like the whole field. Length-1 axes are collapsed
  without being reported, since nothing is lost. `gradient`, `curl`,
  `divergence` and the remote `plot_zonal_mean` now report it too: all four
  must collapse every non-face axis before UXarray will compute at all, so
  their answers always describe one time and one level, and a derivative of
  one level of a forty-level field is not the field's derivative. The remote
  `plot_zonal_mean` worker had built the record and then omitted it from its
  payload, so the same call disclosed its slice locally and returned `{}`
  from HPC.
- A one-sided `vmin`/`vmax` takes its open end from the slice being drawn.
  The colour limit was computed from the full array before reduction, so a
  vmin-only plot of one time step of a six-step field was scaled by the
  maximum of all six.
- Plot tools now return MCP content blocks the adapter recognizes, so an
  image reaches the client as an image. `toolregistry-server` converts a tool
  result into MCP content only when it is a list of plain dicts carrying a
  known `type`; every plot returned `mcp.types` models, which fail that
  check, so the whole list was JSON-serialized into one `TextContent` holding
  Python `repr()` strings. There was no error and no warning — the figure
  simply stopped being a figure. Verified end to end through the shipped CLI
  over stdio: a `plot_dataset` call now yields `[ImageContent, TextContent]`
  with `image/png` and a 101 KB payload. The wire shape now lives in one
  module, `uxarray_mcp.content_blocks`, because two adapter asymmetries are
  easy to get wrong at a call site: an image carries its MIME type inside
  `source` while every other block carries it on the block, and a
  `resource_link` keeps only `uri`/`name`/`mimeType` — a title, description
  or byte count set on the block is dropped, so those now ride in the
  accompanying metadata instead.
- `zonal_anomaly` reports a malformed `lat_spec` as a `ValueError` naming the
  shapes it accepts. UXarray 2026.8.0 raises `TypeError` for this where earlier
  releases raised `ValueError` (UXarray #1652), which let the raw upstream
  error escape the analysis front door as an untyped traceback instead of a
  repairable message.
- Preserve the original remote worker exception when synchronous MCP tools run
  inside an event loop instead of masking it with a nested `asyncio.run` error.
- Route facility-only paths to the endpoint with the longest configured path
  prefix before using the default endpoint.
- `list_datasets` now accepts an explicit endpoint and uses the common remote
  execution path instead of silently selecting the configured default.
- Dataset validation can run on the selected endpoint. Composite and persisted
  workflows no longer attempt facility-only paths locally, and unavailable or
  failed validation blocks downstream statistics and variable plots.
- Remote variable metadata converts NumPy scalar attributes to JSON-safe Python
  values.

### Added
- `remap_to_rectilinear` refuses when source coverage is zero, using the same
  `input_required` payload as the vector preconditions. Every value in a
  zero-coverage remap is an extrapolation, so a warning beside the numbers was
  not enough. Partial coverage and a non-conservative method remain warnings.
- Analysis results carry a `postconditions` block that is explicit about not
  having checked. `calculate_area` verifies the closed-mesh identity
  `sum(face_areas) == 4*pi*R^2` and abstains with `not_evaluated` on open or
  regional meshes rather than reporting a verdict it cannot support.
- `run_analysis` accepts `verdict_policy` (`full`, `reference_only`, `off`,
  also readable from `UXARRAY_MCP_VERDICT_POLICY`) so a caller can ask for the
  reference and tolerance without the server's own verdict. An unrecognized
  policy is rejected before the computation runs.
- Two tools under a new `contract/` namespace: `describe_response_contract`
  declares the fields a named response shape requires, and `validate_response`
  checks a candidate payload against it. This makes "right answer, wrong
  envelope" separately detectable instead of scoring as a wrong answer.
- Physical test fixtures: a global mesh carrying a real Earth `sphere_radius`,
  a four-level field whose levels are far enough apart that a mis-selection is
  unmistakable, and a half-masked field where any mean other than 1.0 means
  NaNs were folded in. Every previous fixture sat on a unit sphere, where
  radius scaling is invisible.
- `evals/multi_turn/` measures what one-call benchmarks cannot: whether a run
  chains the calls a task requires, reuses minted handles instead of inventing
  or dropping them, and recovers from an injected mid-sequence fault. Two
  injected faults, a precondition refusal and an interrupted workflow, give the
  refusal machinery something to be validated against. Two scripted adapters
  bracket the score range so the harness runs offline.
- `curl` and `divergence` declare their preconditions as data and refuse
  instead of returning an unphysical number. The refusal is shaped after the
  MCP `2026-07-28` multi-round-trip request flow: `result_type:
  "input_required"`, an `elicitation/create` request, an opaque
  `request_state`, and the specific repair for each failed check. Passing
  `acknowledge` with the named token runs the operation anyway and labels the
  result `unverified` with `physically_interpretable: false`.
- Remote scientific results now distinguish submitter and worker Python
  versions through `remote_python_version`; the runtime envelope is extensible
  to hostname, Xarray, NumPy, and scheduler identifiers.
- Curl scientific status reports whether physical scaling was requested and
  actually applied. Missing radius metadata or unsupported worker APIs cannot
  appear as a complete physical result.
- A reproducible layered-readiness matrix exercises manager, worker, path,
  portable calculation, native workflow, venue, and worker provenance across
  named endpoints.

### Fixed
- Pin the MCP Python SDK to `<2` until toolregistry-server supports the renamed
  `MCPError` exception in SDK 2.x. Fresh installs previously resolved MCP 2.0,
  installed successfully, then failed when starting the stdio server.
- CI and release verification now perform a real clean-wheel MCP handshake:
  initialize the server, list tools, and call `get_capabilities` over stdio.
- Package metadata now enforces the documented UXarray 2026.7.0 minimum used by
  the vector-calculus fixes and scientific contracts.

### Breaking
- `gradient` and `curl` now default `scale_by_radius=True`, matching UXarray's
  public API. Pass `scale_by_radius=False` explicitly to preserve the previous
  MCP unit-sphere behavior. This default alignment requires a minor release.

### Added
- Vector-calculus results now include a machine-actionable
  `scientific_status` with `status`, `physically_interpretable`, stable warning
  codes, and warning text.
- `get_capabilities` now returns variable units, standard names, dimensions,
  and a `scientific_contracts.vector_calculus` block that separates structural
  applicability from semantic suitability.
- Persistent JSON and NetCDF artifacts are written atomically under a process
  lock so concurrent tool calls cannot expose partial result files.
- `gradient`, `curl`, and `divergence` (via `run_analysis` and the
  `calculate_gradient`/`calculate_curl`/`calculate_divergence` tools) now
  accept `time_index`/`level_index` to select a single time/level slice
  when the input variable(s) carry those extra dimensions. Previously these
  operations raised `Curl computation currently only supports
  1-dimensional data` on any real multi-level/multi-time model output
  (e.g. E3SM `U`/`V` shaped `(time, lev, n_face)`), forcing the caller to
  pre-slice the file out-of-band before calling the tool. Both parameters
  default to 0 and are ignored for variables that are already
  face-centered only, so existing calls are unaffected.

### Changed
- `calculate_gradient` and `calculate_curl` (local and remote) now capture
  UXarray's own `UserWarning`s raised during the actual computation --
  e.g. `scale_by_radius=True` silently falling back to unit-sphere output
  when the grid has no `sphere_radius` attribute -- and merge them into
  the tool's `component_warnings`/`_provenance.warnings`. Previously these
  warnings only reached a terminal's stderr and were invisible to an agent
  reading the tool's structured JSON result.

### Fixed
- `analyze_dataset` and `run_scientific_agent` now actually skip zonal
  statistics after failed validation; `analyze_dataset` also skips variable
  plotting and records the validation summary in provenance.
- `analyze_dataset` derives aggregate execution venue from completed stage
  provenance instead of labeling a fallback-local run as HPC solely because
  `use_remote=True` was requested.
- The monthly release workflow now uses supported Python 3.12 instead of Python
  3.13, which conflicts with the package's `requires-python` constraint.
- `calculate_area` (local and remote) silently defaulted `area_units` to
  `"m^2"` whenever a grid's `face_areas` carried no `units` attribute at
  all, fabricating a label the source file never provided. It now reports
  `None` in that case, so an absent unit is never confused with a genuine
  (even if stale) `"m^2"` label. Found while independently verifying a
  paper claim about which production meshes carry stale area-unit
  metadata: this server's own tool -- not just the meshes -- was inventing
  metadata, the exact class of silent failure this project exists to
  prevent.
- `run_analysis` and `plot_dataset` silently ignored `use_remote=True` for
  13 operations that have no remote implementation (`validate_dataset`,
  `subset_bbox`, `subset_polygon`, `cross_section`, `compare_fields`,
  `bias`, `rmse`, `pattern_correlation`, `temporal_mean`, `anomaly`,
  `ensemble_mean`, `ensemble_spread`, `export`, and
  `plot_dataset(plot_type="mesh_geo")`), running locally without saying so.
  On a facility-only path (one that doesn't exist on the caller's machine)
  this surfaced as a confusing local `FileNotFoundError` with no indication
  `use_remote` was ever honored. These now raise `ValueError` immediately
  instead. See `docs/tools.md#remote-execution` for the full list of which
  operations do and don't support remote execution today.

### Changed
- Bumped the `uxarray` floor to the new July release (`2026.7.0`), which
  fixes `curl(grad(f))` accuracy (residual now ~1e-13 with
  `scale_by_radius=True`, previously O(1) due to an upstream gradient/curl
  normalization bug) and adds Python 3.14 support, YAC v3.18 remapping, and
  one-file `open_dataset`.
- Rebuilt YAC on the Chrysalis (ANL/LCRC) endpoint from v3.17.0 to v3.18.0
  and updated `scripts/chrysalis_endpoint.sh` to point at the new
  self-contained `~/local/yac-3.18` prefix.

### Fixed
- `domain/mesh.load_dataset` and ~20 duplicated inline branches in
  `remote/compute_functions.py` crashed with `ValueError: cannot rename
  'node_lon'...` whenever a HEALPix or GIS (shapefile/GeoJSON) grid was
  combined with a *separate* data file (e.g.
  `run_analysis(operation="gradient", grid_path="healpix:4",
  data_path=...)`). The code treated the grid's minimal `to_xarray()`
  representation as a full UGRID file, which the generic reader rejects.
  Fixed by attaching the data directly to the already-loaded `Grid` object
  instead. Added regression tests in `tests/test_domain_mesh.py` covering
  both the local and remote code paths.

### Added
- `scripts/analytic_validation.py` — a checked-in, reproducible script that
  validates `gradient`/`curl`/`divergence` against four analytic
  vector-calculus identities (including the stringent
  `curl(grad(phi)) == 0`) through the same `run_analysis` tool path an
  agent uses, against a self-contained synthetic grid (no external mesh
  file required).

## 0.1.2 — 2026-07-05

### Added
- Guided science workflows as `prompt/` tools, each composing existing
  operations around a scientific question: `cyclone_structure` (storm radial
  structure), `eddy_activity` (departures from the zonal mean),
  `model_evaluation` (bias/RMSE/pattern correlation vs a reference), and
  `climatology_anomaly` (time-mean state and anomalies). These join the existing
  `vorticity_analysis` workflow.
- `run_analysis` operation `zonal_anomaly` — per-face deviation from the zonal
  mean of each latitude band (`UxDataArray.zonal_anomaly`).
- `run_analysis` operation `remap_to_rectilinear` — remap an unstructured
  variable onto a regular lon/lat grid (`UxDataArray.remap.to_rectilinear`).
- `gradient` and `curl` operations now accept a `scale_by_radius` flag. It
  defaults to `False` to preserve unit-sphere results; set it to `True` to
  divide by `uxgrid.sphere_radius` for physical units.

### Changed
- Bumped the `uxarray` floor to `>=2026.6.0` for the new zonal-anomaly,
  rectilinear-remap, and radius-scaled gradient/curl APIs.
- **Server engine**: replaced FastMCP with
  [toolregistry](https://github.com/Oaklight/ToolRegistry) +
  [toolregistry-server](https://github.com/Oaklight/toolregistry-server).
  `fastmcp` is no longer a dependency.
- **Two-profile tool surface**: `core` (~31 tools, conservative default) and
  `deferred-full` (all tools loaded, 32 deferred behind BM25 discovery).
- **Namespace grouping**: control tools under `session/` and `hpc/`, IO under
  `io/`, prompts under `prompt/`.
- **Policy tags**: every tool carries `ToolTag` metadata (`READ_ONLY`,
  `FILE_SYSTEM`, `NETWORK`, `SLOW`) and custom tags (`experimental`,
  `stateful`) from day one.

### Added
- `src/uxarray_mcp/registry.py` — `build_registry(profile=...)` with namespace
  plan, policy tags, BM25 search hints, and prompt-as-tool wiring.
- Prompt-as-tool: `first_look`, `vorticity_analysis`, `hpc_diagnose` (formerly
  `@mcp.prompt()` decorators) are now regular tools under `prompt/` namespace.
- CLI: `uxarray-mcp serve` now accepts `--profile`, `--transport`, `--host`,
  `--port`.
- Multi-transport MCP: stdio (default), SSE, streamable HTTP.
- Optional OpenAPI/REST surface via `pip install uxarray-mcp[openapi]`.

### Removed
- `fastmcp` dependency.
- `@mcp.prompt()` decorators (replaced by `prompt/` namespace tools).

## 0.1.1 — 2026-06-11

### Changed
- Pinned Python to `>=3.12,<3.13` to match the supported runtime and avoid
  Globus Compute pickle version-mismatch failures.
- Aligned the published package metadata with the current PyPI release for the
  conda-forge recipe.

## 0.1.0 — 2026-06-04

Initial public release.

### Added
- FastMCP stdio server for UXarray mesh analysis.
- Small MCP front-door tool surface:
  - `get_capabilities`
  - `analyze_dataset`
  - `run_analysis`
  - `plot_dataset`
  - `diagnose_endpoint`
  - `probe_path_access`
  - workflow/session helpers
- UXarray-backed operations for mesh inspection, variable inspection, area
  statistics, dataset validation, zonal means, vector calculus, spatial
  subsetting, remapping/regridding, comparison metrics, temporal/ensemble
  reductions, and export.
- Inline PNG plotting for mesh, geographic mesh, variables, and zonal means.
- Optional Globus Compute execution with named endpoint profiles,
  pre-flight health checks, worker probes, and local fallback when safe.
- Scientific provenance attached to tool results.
- Stateful sessions, persisted result handles, and resumable workflows.
- CLI entry point: `uxarray-mcp` with `serve`, `setup`, `endpoints`, `doctor`,
  and `install-claude` subcommands.
- Cluster setup and validation docs for Improv, Chrysalis, and UCAR/Casper.
- PyPI release automation, package smoke tests, and conda-forge seed recipe.

### Security And Privacy
- Endpoint UUIDs are private local configuration values and are not returned in
  public MCP tool provenance or status payloads.
- Repository-local `config.yaml` is ignored; the CLI writes private user config
  under `~/.config/uxarray-mcp/config.yaml` by default.
