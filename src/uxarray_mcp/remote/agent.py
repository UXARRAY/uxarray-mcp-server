"""Academy agent for orchestrating local and remote UXarray computations."""

from __future__ import annotations

import asyncio
import warnings
from typing import Any, Dict, Optional

try:
    from academy.agent import Agent as _AcademyAgent
    from academy.agent import action
except ImportError:
    _AcademyAgent = object  # type: ignore[assignment,misc]

    def action(fn):  # type: ignore[no-redef]
        """No-op decorator when academy is not installed."""
        return fn


from .compute_functions import (
    remote_calculate_area,
    remote_calculate_azimuthal_mean,
    remote_calculate_curl,
    remote_calculate_divergence,
    remote_calculate_gradient,
    remote_calculate_zonal_mean,
    remote_inspect_mesh,
    remote_inspect_variable,
    remote_plot_mesh,
    remote_plot_variable,
    remote_plot_zonal_mean,
    remote_probe_path,
)
from .config import HPCConfig


class UXarrayComputeAgent(_AcademyAgent):
    """Academy agent for UXarray computations with HPC support.

    This agent orchestrates execution of UXarray operations either locally
    or on remote HPC resources via Globus Compute.

    Parameters
    ----------
    config : HPCConfig
        Configuration for HPC execution

    Examples
    --------
    >>> from uxarray_mcp.remote import load_config, UXarrayComputeAgent
    >>> config = load_config()
    >>> agent = UXarrayComputeAgent(config)
    """

    def __init__(self, config: HPCConfig):
        super().__init__()
        self.config = config
        self._executor: Any = None

    def _get_executor(self):
        """Get or create Globus Compute executor with AllCodeStrategies.

        AllCodeStrategies serializes the actual function code instead of
        just the module reference, so the HPC endpoint does not need
        uxarray_mcp installed — only uxarray and its dependencies.
        """
        if self._executor is None and self.config.endpoint_id:
            from globus_compute_sdk import Executor
            from globus_compute_sdk.serialize import (
                AllCodeStrategies,
                ComputeSerializer,
            )

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"(?s).*Environment differences detected between local SDK and endpoint.*",
                    category=UserWarning,
                )
                self._executor = Executor(
                    endpoint_id=self.config.endpoint_id,
                    serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
                )
        return self._executor

    @action
    async def inspect_mesh_remote(
        self, file_path: str, use_remote: bool = False
    ) -> Dict[str, Any]:
        """Inspect mesh topology with optional remote execution.

        Parameters
        ----------
        file_path : str
            Path to mesh file
        use_remote : bool
            If True, execute on HPC; if False, execute locally

        Returns
        -------
        dict
            Mesh topology info (n_face, n_node, n_edge, source)
        """
        if use_remote and self.config.endpoint_id:
            return await self._run_on_hpc(remote_inspect_mesh, file_path)
        else:
            return self._run_local_inspect_mesh(file_path)

    @action
    async def calculate_area_remote(
        self, file_path: str, use_remote: bool = False
    ) -> Dict[str, Any]:
        """Calculate face areas with optional remote execution.

        Parameters
        ----------
        file_path : str
            Path to mesh file
        use_remote : bool
            If True, execute on HPC; if False, execute locally

        Returns
        -------
        dict
            Area statistics

        Examples
        --------
        >>> result = await agent.calculate_area_remote("mesh.nc", use_remote=False)
        """
        if use_remote and self.config.endpoint_id:
            return await self._run_on_hpc(remote_calculate_area, file_path)
        else:
            return self._run_local_calculate_area(file_path)

    @action
    async def inspect_variable_remote(
        self,
        grid_path: str,
        data_path: str,
        variable_name: Optional[str] = None,
        use_remote: bool = False,
    ) -> Dict[str, Any]:
        """Inspect variables with optional remote execution.

        Parameters
        ----------
        grid_path : str
            Path to grid file
        data_path : str
            Path to data file
        variable_name : str | None
            Variable to inspect, or None for all
        use_remote : bool
            If True, execute on HPC; if False, execute locally

        Returns
        -------
        dict
            Variable metadata
        """
        if use_remote and self.config.endpoint_id:
            return await self._run_on_hpc(
                remote_inspect_variable, grid_path, data_path, variable_name
            )
        else:
            return self._run_local_inspect_variable(grid_path, data_path, variable_name)

    @action
    async def calculate_zonal_mean_remote(
        self,
        grid_path: str,
        data_path: str,
        variable_name: str,
        lat_spec: Optional[tuple | float | list] = None,
        conservative: bool = False,
        use_remote: bool = False,
    ) -> Dict[str, Any]:
        """Calculate zonal mean with optional remote execution.

        Parameters
        ----------
        grid_path : str
            Path to grid file
        data_path : str
            Path to data file
        variable_name : str
            Variable to compute zonal mean for
        lat_spec : tuple | float | list | None
            Latitude specification
        conservative : bool
            Use conservative averaging
        use_remote : bool
            If True, execute on HPC; if False, execute locally

        Returns
        -------
        dict
            Zonal mean results
        """
        if use_remote and self.config.endpoint_id:
            return await self._run_on_hpc(
                remote_calculate_zonal_mean,
                grid_path,
                data_path,
                variable_name,
                lat_spec,
                conservative,
            )
        else:
            return self._run_local_calculate_zonal_mean(
                grid_path, data_path, variable_name, lat_spec, conservative
            )

    @action
    async def calculate_gradient_remote(
        self,
        grid_path: str,
        data_path: str,
        variable_name: str,
        scale_by_radius: bool = False,
        time_index: int = 0,
        level_index: int = 0,
    ) -> Dict[str, Any]:
        """Compute spatial gradient on HPC."""
        return await self._run_on_hpc(
            remote_calculate_gradient,
            grid_path,
            data_path,
            variable_name,
            scale_by_radius,
            time_index,
            level_index,
        )

    @action
    async def calculate_curl_remote(
        self,
        grid_path: str,
        data_path: str,
        u_variable: str,
        v_variable: str,
        scale_by_radius: bool = False,
        time_index: int = 0,
        level_index: int = 0,
    ) -> Dict[str, Any]:
        """Compute relative vorticity (curl) on HPC."""
        return await self._run_on_hpc(
            remote_calculate_curl,
            grid_path,
            data_path,
            u_variable,
            v_variable,
            scale_by_radius,
            time_index,
            level_index,
        )

    @action
    async def calculate_divergence_remote(
        self,
        grid_path: str,
        data_path: str,
        u_variable: str,
        v_variable: str,
        time_index: int = 0,
        level_index: int = 0,
    ) -> Dict[str, Any]:
        """Compute horizontal divergence on HPC."""
        return await self._run_on_hpc(
            remote_calculate_divergence,
            grid_path,
            data_path,
            u_variable,
            v_variable,
            time_index,
            level_index,
        )

    @action
    async def calculate_azimuthal_mean_remote(
        self,
        grid_path: str,
        data_path: str,
        variable_name: str,
        center_lon: float,
        center_lat: float,
        outer_radius: float,
        radius_step: float,
    ) -> Dict[str, Any]:
        """Compute azimuthal mean around a centre point on HPC."""
        return await self._run_on_hpc(
            remote_calculate_azimuthal_mean,
            grid_path,
            data_path,
            variable_name,
            center_lon,
            center_lat,
            outer_radius,
            radius_step,
        )

    @action
    async def probe_path_remote(
        self, file_path: str, inspect_netcdf: bool = True, use_remote: bool = False
    ) -> Dict[str, Any]:
        """Probe whether a remote worker can read the exact target path."""
        if use_remote and self.config.endpoint_id:
            return await self._run_on_hpc(remote_probe_path, file_path, inspect_netcdf)
        else:
            return remote_probe_path(file_path, inspect_netcdf)

    @action
    async def plot_mesh_remote(
        self,
        grid_path: str,
        width: int = 800,
        height: int = 400,
        use_remote: bool = False,
    ) -> Dict[str, Any]:
        """Render mesh wireframe PNG on HPC and return base64 bytes."""
        if use_remote and self.config.endpoint_id:
            return await self._run_on_hpc(remote_plot_mesh, grid_path, width, height)
        else:
            return remote_plot_mesh(grid_path, width, height)

    @action
    async def plot_variable_remote(
        self,
        grid_path: str,
        data_path: str,
        variable_name: Optional[str] = None,
        width: int = 800,
        height: int = 400,
        cmap: str = "viridis",
        vmin: Optional[float] = None,
        vmax: Optional[float] = None,
        title: Optional[str] = None,
        time_index: int = 0,
        use_remote: bool = False,
    ) -> Dict[str, Any]:
        """Render face-centered variable PNG on HPC and return base64 bytes."""
        if use_remote and self.config.endpoint_id:
            return await self._run_on_hpc(
                remote_plot_variable,
                grid_path,
                data_path,
                variable_name,
                width,
                height,
                cmap,
                vmin,
                vmax,
                title,
                time_index,
            )
        else:
            return remote_plot_variable(
                grid_path,
                data_path,
                variable_name,
                width,
                height,
                cmap,
                vmin,
                vmax,
                title,
                time_index,
            )

    @action
    async def plot_zonal_mean_remote(
        self,
        grid_path: str,
        data_path: str,
        variable_name: str,
        width: int = 800,
        height: int = 400,
        lat_spec=None,
        conservative: bool = False,
        line_color: str = "#1f77b4",
        title: Optional[str] = None,
        use_remote: bool = False,
    ) -> Dict[str, Any]:
        """Render zonal mean profile PNG on HPC and return base64 bytes."""
        if use_remote and self.config.endpoint_id:
            return await self._run_on_hpc(
                remote_plot_zonal_mean,
                grid_path,
                data_path,
                variable_name,
                width,
                height,
                lat_spec,
                conservative,
                line_color,
                title,
            )
        else:
            return remote_plot_zonal_mean(
                grid_path,
                data_path,
                variable_name,
                width,
                height,
                lat_spec,
                conservative,
                line_color,
                title,
            )

    async def _run_on_hpc(self, func, *args, **kwargs) -> Dict[str, Any]:
        """Execute function on HPC via Globus Compute.

        Parameters
        ----------
        func : callable
            Remote function to execute
        *args
            Positional arguments for function
        **kwargs
            Keyword arguments for function

        Returns
        -------
        dict
            Function result from HPC
        """
        executor = self._get_executor()
        if executor is None:
            raise RuntimeError("HPC endpoint not configured")

        loop = asyncio.get_event_loop()
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"(?s).*Environment differences detected between local SDK and endpoint.*",
                category=UserWarning,
            )
            future = executor.submit(func, *args, **kwargs)
            result = await loop.run_in_executor(
                None, future.result, self.config.timeout_seconds
            )

        # Attach provenance with the correct HPC venue — the remote functions
        # are self contained and don't call attach_provenance themselves.
        from uxarray_mcp.provenance import _get_uxarray_version, attach_provenance

        endpoint_label = self.config.endpoint_name or "configured"

        # Capture the worker's true software versions (when the remote function
        # reports them) so provenance reflects what actually computed the result
        # — not the local submitter — and warn on local/remote version drift.
        drift_warnings: list[str] = []
        worker_uxarray = None
        if isinstance(result, dict):
            worker_uxarray = result.pop("_worker_uxarray_version", None)
            result.pop("_worker_python_version", None)
        local_uxarray = _get_uxarray_version()
        if (
            worker_uxarray
            and local_uxarray != "unknown"
            and worker_uxarray != local_uxarray
        ):
            drift_warnings.append(
                f"UXarray version drift: local={local_uxarray}, "
                f"remote(worker)={worker_uxarray}. Numerical results may differ "
                "between local and remote runs; compare with care."
            )

        # Fold any warnings the remote function itself produced (e.g. vector
        # component guardrails) into provenance.
        if isinstance(result, dict):
            fn_warnings = result.get("component_warnings") or []
            drift_warnings.extend(fn_warnings)

        annotated = attach_provenance(
            result,
            tool=func.__name__,
            inputs={"args": [str(a) for a in args]},
            venue=f"hpc:{endpoint_label}",
            warnings=drift_warnings or None,
        )
        # Record the worker's uxarray version explicitly alongside the local one.
        if worker_uxarray:
            annotated["_provenance"]["remote_uxarray_version"] = worker_uxarray
        return annotated

    def _run_local_inspect_mesh(self, file_path: str) -> Dict[str, Any]:
        """Execute inspect_mesh locally as fallback."""
        from uxarray_mcp.tools import inspect_mesh

        return inspect_mesh(file_path)

    def _run_local_calculate_area(self, file_path: str) -> Dict[str, Any]:
        """Execute calculate_area locally as fallback."""
        from uxarray_mcp.tools import calculate_area

        return calculate_area(file_path)

    def _run_local_inspect_variable(
        self, grid_path: str, data_path: str, variable_name: Optional[str]
    ) -> Dict[str, Any]:
        """Execute inspect_variable locally as fallback."""
        from uxarray_mcp.tools import inspect_variable

        return inspect_variable(grid_path, data_path, variable_name)

    def _run_local_calculate_zonal_mean(
        self,
        grid_path: str,
        data_path: str,
        variable_name: str,
        lat_spec: Optional[tuple | float | list],
        conservative: bool,
    ) -> Dict[str, Any]:
        """Execute calculate_zonal_mean locally as fallback."""
        from uxarray_mcp.tools import calculate_zonal_mean

        return calculate_zonal_mean(
            grid_path, data_path, variable_name, lat_spec, conservative
        )


_agent_instance = None
_agent_instances: dict[str, UXarrayComputeAgent] = {}


def get_agent(
    endpoint: str | None = None, path: str | None = None
) -> UXarrayComputeAgent:
    """Get or create singleton agent instance.

    Returns
    -------
    UXarrayComputeAgent
        Configured agent instance

    Examples
    --------
    >>> agent = get_agent()
    >>> result = await agent.calculate_area_remote("mesh.nc")
    """
    global _agent_instance
    from .config import load_config

    base_config = load_config()
    config = base_config.for_endpoint(endpoint=endpoint, path=path)

    if endpoint is None and path is None:
        if _agent_instance is None:
            _agent_instance = UXarrayComputeAgent(config)
        return _agent_instance

    key = (
        f"{config.endpoint_name or 'default'}:"
        f"{config.endpoint_id or 'local'}:"
        f"{config.execution_mode}:"
        f"{config.timeout_seconds}"
    )
    if key not in _agent_instances:
        _agent_instances[key] = UXarrayComputeAgent(config)
    return _agent_instances[key]
