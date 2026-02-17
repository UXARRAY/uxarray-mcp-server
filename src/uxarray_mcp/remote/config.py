"""Configuration management for remote execution."""

from pathlib import Path
from typing import Optional
import yaml


class HPCConfig:
    """HPC execution configuration.

    Parameters
    ----------
    endpoint_id : str | None
        Globus Compute endpoint UUID
    execution_mode : str
        Execution mode: "local", "remote", or "auto"
    timeout_seconds : int
        Timeout for remote execution in seconds

    Examples
    --------
    >>> config = HPCConfig(endpoint_id="abc-123", execution_mode="remote")
    >>> config.has_endpoint
    True
    """

    def __init__(
        self,
        endpoint_id: Optional[str] = None,
        execution_mode: str = "local",
        timeout_seconds: int = 300,
    ):
        self.endpoint_id = endpoint_id
        self.execution_mode = execution_mode
        self.timeout_seconds = timeout_seconds

    @property
    def has_endpoint(self) -> bool:
        """Check if Globus Compute endpoint is configured."""
        return self.endpoint_id is not None

    @property
    def should_use_remote(self) -> bool:
        """Determine if remote execution should be used."""
        if self.execution_mode == "local":
            return False
        elif self.execution_mode == "remote":
            return self.has_endpoint
        else:
            return False


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

    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    hpc_config = data.get("hpc", {})
    globus_config = hpc_config.get("globus_compute", {})

    return HPCConfig(
        endpoint_id=globus_config.get("endpoint_id"),
        execution_mode=hpc_config.get("execution_mode", "local"),
        timeout_seconds=hpc_config.get("timeout_seconds", 300),
    )
