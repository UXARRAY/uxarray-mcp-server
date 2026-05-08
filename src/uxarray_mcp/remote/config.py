"""Configuration management for remote execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import yaml

_VALID_EXECUTION_MODES = {"local", "hpc", "auto"}
_EXECUTION_MODE_ALIASES = {"remote": "hpc"}


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class EndpointProfile:
    """Named Globus Compute endpoint profile."""

    name: str
    endpoint_id: str
    path_prefixes: tuple[str, ...] = ()
    timeout_seconds: int | None = None


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
    ):
        self.endpoints = endpoints or {}
        self.default_endpoint = default_endpoint
        self.endpoint_name = endpoint_name
        self.endpoint_id = endpoint_id
        self.execution_mode = normalize_execution_mode(execution_mode)
        self.timeout_seconds = timeout_seconds

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
        """Resolve an explicit endpoint name, default endpoint, or raw UUID."""
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

        return HPCConfig(
            endpoint_id=profile.endpoint_id,
            execution_mode=self.execution_mode,
            timeout_seconds=profile.timeout_seconds or self.timeout_seconds,
            endpoints=self.endpoints,
            default_endpoint=self.default_endpoint,
            endpoint_name=profile.name,
        )


def _coerce_prefixes(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if item)
    return ()


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
        profiles[str(name)] = EndpointProfile(
            name=str(name),
            endpoint_id=str(endpoint_id),
            path_prefixes=_coerce_prefixes(raw_profile.get("path_prefixes")),
            timeout_seconds=int(timeout) if timeout is not None else None,
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
        config_path = Path(__file__).parent.parent.parent.parent / "config.yaml"

    if not config_path.exists():
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

    return HPCConfig(
        endpoint_id=endpoint_id,
        execution_mode=hpc_config.get("execution_mode", "local"),
        timeout_seconds=hpc_config.get("timeout_seconds", 300),
        endpoints=endpoints,
        default_endpoint=default_endpoint,
        endpoint_name=endpoint_name,
    )
