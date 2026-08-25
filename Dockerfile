# UXarray MCP Server -- local-only container image.
#
# What this image is for
# ----------------------
# Running the server without fighting a scientific Python install. The
# dependency closure (uxarray -> xarray -> netcdf4 -> numpy/numba, plus
# matplotlib and holoviews) is the single biggest obstacle to someone trying
# this server for ten minutes, and it is also what makes the server awkward to
# drop into an agent-benchmark harness. Both problems go away with an image.
#
# What this image deliberately is NOT
# -----------------------------------
# The HPC path is absent. No globus-compute-sdk, no academy-py, no credentials,
# and the baked config pins execution_mode to "local". A sealed container has
# no business holding Globus tokens or reaching a Slurm endpoint, and an image
# that *could* submit remote work is an image nobody should run untrusted
# agents against. Users who want HPC run the server on the host, where their
# identity lives -- see docs/remote-hpc.md.
#
# Build:
#   docker build -t uxarray-mcp:local .
# Run (stdio, the transport MCP clients expect):
#   docker run --rm -i uxarray-mcp:local
# Run (HTTP, for harnesses):
#   docker run --rm -p 8001:8001 uxarray-mcp:local serve --transport http --host 0.0.0.0

# ---------------------------------------------------------------------------
# Stage 1 -- builder. Resolves and compiles into a relocatable venv.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# A C/C++ toolchain is required, not optional: `healpix` (pulled in by uxarray)
# publishes no wheel for every platform we build on -- notably linux/arm64 --
# and falls back to a source build. This is the entire reason the image is
# multi-stage. The compiler is ~250 MB and none of it reaches the runtime
# stage, which receives only the finished venv.
RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential \
 && rm -rf /var/lib/apt/lists/*

# uv is copied from its own published image rather than pip-installed: it
# pins the uv version explicitly and avoids a bootstrap pip resolve.
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv

# UV_PROJECT_ENVIRONMENT points the venv at its *final* runtime path even
# though we are building in /build. Console scripts get an absolute shebang
# baked in at install time, so a venv built at /build/.venv and then copied
# elsewhere produces `exec .../uxarray-mcp: no such file or directory` -- the
# shebang still references a path that only existed in the builder. Creating
# it at the destination path avoids relocation entirely.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/uxarray-mcp/.venv

WORKDIR /build

# Dependency layer first, source second. Editing a .py file must not force a
# re-resolve of the entire scientific stack -- that is the difference between
# a 10-second rebuild and a 4-minute one.
COPY pyproject.toml README.md LICENSE ./
COPY src/uxarray_mcp/__init__.py src/uxarray_mcp/__init__.py

# --no-install-project: dependencies only at this point. The project itself is
# installed after the source is copied, so source edits invalidate only the
# final, cheap layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project --python 3.12

COPY src/ src/

# --no-editable matters: `uv sync` installs the project editable by default,
# which drops a .pth file pointing at /build/src. That path does not exist in
# the runtime stage, so the venv copies over with a dangling reference and the
# entrypoint dies on `ModuleNotFoundError: No module named 'uxarray_mcp'`.
# A non-editable install copies the package into site-packages instead.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-editable --python 3.12

# Fixtures are generated here, in the stage that already has uxarray, so the
# runtime stage needs no build tooling. See the script's docstring for why
# these are generated rather than committed.
COPY scripts/generate_container_fixtures.py scripts/
RUN /opt/uxarray-mcp/.venv/bin/python scripts/generate_container_fixtures.py --outdir /data/uxarray \
 && /opt/uxarray-mcp/.venv/bin/python scripts/generate_container_fixtures.py --outdir /data/uxarray --verify

# Trim the venv. The scientific stack ships its own test suites, bundled
# headers, and (for numba/llvmlite) large static archives that exist only to
# support compiling *other* extensions -- none of which a runtime image needs.
# Ordering matters: this runs after the fixture step so anything the generator
# imports has already been exercised against the untrimmed tree.
#
# Deliberately conservative -- it removes tests, C headers, and static libs,
# and never touches shared objects. Note that `testing` directories are NOT
# removed: xarray re-exports `xarray.testing` from its top-level __init__, so
# deleting it breaks the import outright. The trailing import check exists to
# catch exactly that class of over-reach, and did.
#
# Bytecode is kept because UV_COMPILE_BYTECODE
# generated it on purpose: dropping it would trade image size for slower cold
# starts, which is the wrong trade for a server an agent spawns per session.
RUN set -eux; \
    VENV=/opt/uxarray-mcp/.venv; \
    SITE="$(ls -d "$VENV"/lib/python3.*/site-packages)"; \
    find "$SITE" -type d -regex '.*/tests?$' -prune -exec rm -rf {} + ; \
    find "$SITE" -type f -name '*.pyx' -delete; \
    find "$SITE" -type f -name '*.pxd' -delete; \
    find "$SITE" -type f -name '*.h' -delete; \
    find "$SITE" -type f -name '*.a' -delete; \
    find "$SITE" -type d -name '__pycache__' -prune -exec rm -rf {} + ; \
    rm -rf "$SITE"/pip "$SITE"/setuptools "$SITE"/pkg_resources; \
    "$VENV"/bin/python -c 'import uxarray, uxarray_mcp, matplotlib, holoviews'

# ---------------------------------------------------------------------------
# Stage 2 -- runtime. Carries the venv and the data, none of the build tools.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="UXarray MCP Server" \
      org.opencontainers.image.description="MCP server for analyzing unstructured climate meshes with UXarray (local-only build)" \
      org.opencontainers.image.source="https://github.com/UXARRAY/uxarray-mcp-server" \
      org.opencontainers.image.documentation="https://uxarray-mcp-server.readthedocs.io" \
      org.opencontainers.image.licenses="Apache-2.0"

# MPLBACKEND: the plotting tools call matplotlib.use("Agg") themselves, but a
# headless default protects any import path that touches pyplot first.
# PYTHONUNBUFFERED: stdio transport is a pipe; buffered stdout deadlocks a
# handshake that is waiting on a line the interpreter has not flushed.
# HOME: the state directory falls back to Path.home(), which must be writable
# for the non-root user below.
ENV PATH="/opt/uxarray-mcp/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    HOME=/home/uxarray \
    UXARRAY_MCP_CONFIG=/etc/uxarray-mcp/config.yaml \
    UXARRAY_MCP_STATE_DIR=/home/uxarray/state \
    UXARRAY_MCP_DATA_DIR=/data/uxarray

# Non-root by default. The server opens whatever files it is pointed at, so an
# agent driving it as root inside the container is an unnecessary blast radius.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin uxarray

COPY --from=builder /opt/uxarray-mcp/.venv /opt/uxarray-mcp/.venv
COPY --from=builder --chown=uxarray:uxarray /data/uxarray /data/uxarray

# The baked config is local-only and has no endpoints. execution_mode "local"
# (not "auto") is deliberate: "auto" would silently start using an endpoint if
# one ever appeared in a mounted config, and a container should fail loudly
# rather than quietly acquire the ability to submit remote jobs.
RUN mkdir -p /etc/uxarray-mcp \
 && printf '%s\n' \
    '# Container config -- local execution only.' \
    '# The HPC extras are not installed in this image; see the Dockerfile' \
    '# header for why. To use HPC, run the server on the host instead.' \
    'hpc:' \
    '  execution_mode: "local"' \
    '  timeout_seconds: 300' \
    '  endpoints: {}' \
    > /etc/uxarray-mcp/config.yaml \
 && mkdir -p /home/uxarray/state /home/uxarray/outputs \
 && chown -R uxarray:uxarray /home/uxarray

# /work is the mount point for a user's own meshes:
#   docker run --rm -i -v /path/to/my/data:/work uxarray-mcp:local
WORKDIR /work
RUN chown uxarray:uxarray /work

USER uxarray

# Import-only check. It must not start a server: stdio would block forever and
# HTTP would need a port, so neither is usable as a healthcheck. What can go
# wrong at runtime is a broken dependency closure, and this catches exactly
# that, plus fixture presence.
HEALTHCHECK --interval=30s --timeout=20s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import uxarray, uxarray_mcp; from uxarray_mcp.app import make_registry; make_registry(); import os,sys; sys.exit(0 if os.path.exists('/data/uxarray/MANIFEST.json') else 1)"]

# stdio is the default because that is what MCP clients spawn. Override the
# arguments for other transports; see the header for the HTTP invocation.
ENTRYPOINT ["uxarray-mcp"]
CMD ["serve", "--transport", "stdio", "--profile", "core"]
