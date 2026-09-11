"""Configuration management for remote execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import yaml

USER_CONFIG_PATH = Path.home() / ".config" / "uxarray-mcp" / "config.yaml"


def discover_config_path() -> Path | None:
    """Return the first existing config file in the discovery order.

    Order:
      1. ``$UXARRAY_MCP_CONFIG`` (explicit override)
      2. ``./config.yaml`` (current working directory — project-local)
      3. ``~/.config/uxarray-mcp/config.yaml`` (user install)
      4. ``<repo_root>/config.yaml`` (editable install fallback)

    Project-local (cwd) wins over the user config so that running the CLI
    from inside a checkout uses the repo's config, even when an empty user
    config was previously written by ``uxarray-mcp setup``.

    Returns ``None`` when no config file is found.
    """
    env_path = os.environ.get("UXARRAY_MCP_CONFIG")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return candidate

    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.exists():
        return cwd_config

    if USER_CONFIG_PATH.exists():
        return USER_CONFIG_PATH

    repo_config = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml"
    if repo_config.exists():
        return repo_config

    return None


def discover_config_search_paths() -> list[Path]:
    """Return the ordered list of paths discover_config_path inspects.

    Useful for diagnostics — ``endpoints list`` prints this when no
    endpoints are configured so the user can see exactly which file was
    used or which paths were searched.
    """
    paths: list[Path] = []
    env_path = os.environ.get("UXARRAY_MCP_CONFIG")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.append(Path.cwd() / "config.yaml")
    paths.append(USER_CONFIG_PATH)
    paths.append(Path(__file__).resolve().parent.parent.parent.parent / "config.yaml")
    return paths


_VALID_EXECUTION_MODES = {"local", "hpc", "auto"}
_EXECUTION_MODE_ALIASES = {"remote": "hpc"}


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class GlobusTransferProfile:
    """Where an endpoint's files live, in Globus Transfer's terms.

    Compute and Transfer do not share an identifier: a Globus Compute endpoint
    UUID says nothing about which collection serves that filesystem, so the
    collection is configured explicitly rather than guessed.

    ``remote_write_root`` is the only place a transfer may write. It is a
    containment boundary, not a default directory -- a path outside it is
    refused rather than relocated into it. ``remote_read_root`` widens what may
    be read without widening what may be written, which is the common case: a
    project's whole data tree is readable and one scratch subtree is writable.
    Left unset, reads are confined to the write root as well.

    ``collection_roots`` translates filesystem paths into collection paths. A
    collection usually exposes a subtree as its own ``/``, so
    ``/lcrc/group/e3sm/x`` is ``/x`` to a collection rooted at
    ``/lcrc/group/e3sm``. Paths under no configured root are passed through
    unchanged, because a wrong translation is worse than none: Globus rejects a
    path it does not recognize, while a silently rewritten one can name a real
    file that was never asked for.
    """

    remote_collection_id: str
    local_collection_id: str | None = None
    remote_write_root: str | None = None
    remote_read_root: str | None = None
    collection_roots: tuple[str, ...] = ()
    # Optional containment for this machine's side of a transfer. Unset means
    # the local filesystem is treated the way every other tool here treats it.
    local_root: str | None = None


@dataclass(frozen=True)
class EndpointProfile:
    """Named Globus Compute endpoint profile."""

    name: str
    endpoint_id: str
    path_prefixes: tuple[str, ...] = ()
    timeout_seconds: int | None = None
    globus_transfer: GlobusTransferProfile | None = None
    # Multi-user endpoints refuse a submit that carries no user_endpoint_config
    # ("did not signal readiness", HTTP 422) because the child endpoint is only
    # spawned once the client asks for one. An empty mapping is a valid ask and
    # is enough when the endpoint's template declares no variables.
    user_endpoint_config: dict[str, Any] | None = None


def normalize_execution_mode(execution_mode: str) -> str:
    """Return the canonical execution mode name.

    The repository previously used ``remote`` for the HPC-only mode. Accept it
    as a backwards-compatible alias so older configs and tests keep working.
    """
    canonical_mode = _EXECUTION_MODE_ALIASES.get(execution_mode, execution_mode)
    if canonical_mode not in _VALID_EXECUTION_MODES:
        raise ValueError(
            f"Invalid execution mode {execution_mode!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_EXECUTION_MODES))}"
        )
    return canonical_mode


class HPCConfig:
    """HPC execution configuration.

    Parameters
    ----------
    endpoint_id : str | None
        Globus Compute endpoint UUID
    execution_mode : str
        Execution mode: "local", "hpc", or "auto"
    timeout_seconds : int
        Timeout for remote execution in seconds

    Examples
    --------
    >>> config = HPCConfig(endpoint_id="abc-123", execution_mode="hpc")
    >>> config.has_endpoint
    True
    """

    def __init__(
        self,
        endpoint_id: Optional[str] = None,
        execution_mode: str = "local",
        timeout_seconds: int = 300,
        endpoints: dict[str, EndpointProfile] | None = None,
        default_endpoint: str | None = None,
        endpoint_name: str | None = None,
        user_endpoint_config: dict[str, Any] | None = None,
    ):
        self.endpoints = endpoints or {}
        self.default_endpoint = default_endpoint
        self.endpoint_name = endpoint_name
        self.endpoint_id = endpoint_id
        self.user_endpoint_config = user_endpoint_config
        self.execution_mode = normalize_execution_mode(execution_mode)
        self.timeout_seconds = timeout_seconds
        # Set by for_endpoint(); declared here so the routing provenance is
        # part of the type rather than an attribute that appears out of
        # nowhere on some instances and not others.
        self.routed_by_default_guess: bool = False
        self.routed_path: str | None = None

    @property
    def has_endpoint(self) -> bool:
        """Check if Globus Compute endpoint is configured."""
        return self.endpoint_id is not None or bool(self.endpoints)

    @property
    def should_use_remote(self) -> bool:
        """Determine if remote execution should be used."""
        if self.execution_mode == "local":
            return False
        elif self.execution_mode == "hpc":
            return self.has_endpoint
        elif self.execution_mode == "auto":
            return self.has_endpoint
        else:
            return False

    @property
    def endpoint_names(self) -> list[str]:
        """Return configured endpoint profile names."""
        return sorted(self.endpoints)

    def resolve_endpoint(
        self, endpoint: str | None = None, path: str | None = None
    ) -> EndpointProfile | None:
        """Resolve an explicit endpoint, matching path prefix, or default."""
        self._last_route_was_guess = False
        if endpoint:
            if endpoint in self.endpoints:
                return self.endpoints[endpoint]
            if endpoint == self.endpoint_id:
                return EndpointProfile(
                    name=self.endpoint_name or endpoint,
                    endpoint_id=endpoint,
                    timeout_seconds=self.timeout_seconds,
                )
            if _is_uuid(endpoint):
                return EndpointProfile(
                    name=endpoint,
                    endpoint_id=endpoint,
                    timeout_seconds=self.timeout_seconds,
                )
            configured = ", ".join(self.endpoint_names) or "none"
            raise ValueError(
                f"Unknown endpoint {endpoint!r}. "
                f"Configured endpoint names: {configured}. "
                "Pass a configured endpoint name or a Globus Compute endpoint UUID."
            )

        if path:
            matches: list[tuple[int, EndpointProfile, str]] = []
            for profile in self.endpoints.values():
                for prefix in profile.path_prefixes:
                    if path.startswith(prefix):
                        matches.append((len(prefix), profile, prefix))
            if not matches and self.default_endpoint:
                # No prefix claimed this path, so it is about to fall through to
                # the default endpoint. That is a silent cross-facility misroute
                # when the file actually lives on a different cluster, so make
                # the guess explicit instead of letting it look deliberate.
                self._last_route_was_guess = True
            if matches:
                longest = max(length for length, _, _ in matches)
                best = [item for item in matches if item[0] == longest]
                names = {profile.name for _, profile, _ in best}
                if len(names) > 1:
                    raise ValueError(
                        f"Path {path!r} matches equally specific endpoint prefixes: "
                        + ", ".join(sorted(names))
                    )
                return best[0][1]

        if self.default_endpoint and self.default_endpoint in self.endpoints:
            return self.endpoints[self.default_endpoint]

        if self.endpoint_id is not None:
            return EndpointProfile(
                name=self.endpoint_name or "default",
                endpoint_id=self.endpoint_id,
                timeout_seconds=self.timeout_seconds,
            )

        if len(self.endpoints) == 1:
            return next(iter(self.endpoints.values()))

        return None

    def for_endpoint(
        self, endpoint: str | None = None, path: str | None = None
    ) -> "HPCConfig":
        """Return a copy configured for the selected endpoint profile."""
        profile = self.resolve_endpoint(endpoint=endpoint, path=path)
        if profile is None:
            return HPCConfig(
                endpoint_id=None,
                execution_mode=self.execution_mode,
                timeout_seconds=self.timeout_seconds,
                endpoints=self.endpoints,
                default_endpoint=self.default_endpoint,
            )

        scoped = HPCConfig(
            endpoint_id=profile.endpoint_id,
            execution_mode=self.execution_mode,
            timeout_seconds=profile.timeout_seconds or self.timeout_seconds,
            endpoints=self.endpoints,
            default_endpoint=self.default_endpoint,
            endpoint_name=profile.name,
            user_endpoint_config=profile.user_endpoint_config,
        )
        # Propagate whether this endpoint was chosen because a prefix claimed
        # the path, or merely because it is the default.
        scoped.routed_by_default_guess = bool(
            path and getattr(self, "_last_route_was_guess", False)
        )
        scoped.routed_path = path
        return scoped


def _coerce_prefixes(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if item)
    return ()


def _parse_transfer_profile(value: Any) -> GlobusTransferProfile | None:
    """Read one endpoint's ``globus_transfer`` block, or nothing.

    A block without ``remote_collection_id`` is dropped rather than half-built:
    every transfer names a collection, so a profile that cannot is not a
    profile, and the tools that read this treat ``None`` as "this endpoint does
    not do transfers" -- which is the honest answer.
    """
    if not isinstance(value, dict):
        return None
    collection_id = value.get("remote_collection_id") or value.get("collection_id")
    if not collection_id:
        return None
    local_collection_id = value.get("local_collection_id")
    return GlobusTransferProfile(
        remote_collection_id=str(collection_id),
        local_collection_id=(str(local_collection_id) if local_collection_id else None),
        remote_write_root=(
            str(value["remote_write_root"]) if value.get("remote_write_root") else None
        ),
        remote_read_root=(
            str(value["remote_read_root"]) if value.get("remote_read_root") else None
        ),
        collection_roots=_coerce_prefixes(value.get("collection_roots")),
        local_root=str(value["local_root"]) if value.get("local_root") else None,
    )


def _parse_endpoint_profiles(raw_endpoints: Any) -> dict[str, EndpointProfile]:
    if not isinstance(raw_endpoints, dict):
        return {}

    profiles: dict[str, EndpointProfile] = {}
    for name, raw_profile in raw_endpoints.items():
        if not isinstance(raw_profile, dict):
            continue
        endpoint_id = raw_profile.get("endpoint_id")
        if not endpoint_id:
            continue
        timeout = raw_profile.get("timeout_seconds")
        raw_user_config = raw_profile.get("user_endpoint_config")
        profiles[str(name)] = EndpointProfile(
            name=str(name),
            endpoint_id=str(endpoint_id),
            path_prefixes=_coerce_prefixes(raw_profile.get("path_prefixes")),
            timeout_seconds=int(timeout) if timeout is not None else None,
            globus_transfer=_parse_transfer_profile(raw_profile.get("globus_transfer")),
            user_endpoint_config=(
                dict(raw_user_config) if isinstance(raw_user_config, dict) else None
            ),
        )
    return profiles


def load_config(config_path: Optional[Path] = None) -> HPCConfig:
    """Load HPC configuration from YAML file.

    Parameters
    ----------
    config_path : Path | None
        Path to config.yaml. If None, uses default location.

    Returns
    -------
    HPCConfig
        Loaded configuration object

    Examples
    --------
    >>> config = load_config()
    >>> config.execution_mode
    'local'
    """
    if config_path is None:
        config_path = discover_config_path()

    if config_path is None or not config_path.exists():
        return HPCConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        return HPCConfig()

    hpc_config = data.get("hpc", {})
    if not isinstance(hpc_config, dict):
        hpc_config = {}

    globus_config = hpc_config.get("globus_compute", {})
    if not isinstance(globus_config, dict):
        globus_config = {}

    endpoints = _parse_endpoint_profiles(hpc_config.get("endpoints"))
    if not endpoints:
        endpoints = _parse_endpoint_profiles(globus_config.get("endpoints"))

    default_endpoint = hpc_config.get("default_endpoint") or globus_config.get(
        "default_endpoint"
    )
    endpoint_id = globus_config.get("endpoint_id")

    if endpoint_id is None and default_endpoint in endpoints:
        endpoint_id = endpoints[default_endpoint].endpoint_id
    endpoint_name = (
        default_endpoint
        if default_endpoint in endpoints
        and endpoint_id == endpoints[default_endpoint].endpoint_id
        else None
    )

    # The top-level config mirrors whichever profile endpoint_id came from, so
    # a bare `endpoint_id` submit carries the same multi-user config the named
    # profile would have used.
    user_endpoint_config = hpc_config.get("user_endpoint_config")
    if not isinstance(user_endpoint_config, dict):
        user_endpoint_config = None
    if user_endpoint_config is None and endpoint_name in endpoints:
        user_endpoint_config = endpoints[endpoint_name].user_endpoint_config

    return HPCConfig(
        endpoint_id=endpoint_id,
        execution_mode=hpc_config.get("execution_mode", "local"),
        timeout_seconds=hpc_config.get("timeout_seconds", 300),
        endpoints=endpoints,
        default_endpoint=default_endpoint,
        endpoint_name=endpoint_name,
        user_endpoint_config=user_endpoint_config,
    )
