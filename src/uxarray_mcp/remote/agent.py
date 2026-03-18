"""Academy agent for orchestrating local and remote UXarray computations."""

import asyncio
from typing import Dict, Any, Optional
from academy.agent import Agent, action

from .config import HPCConfig
from .compute_functions import (
    remote_inspect_mesh,
    remote_calculate_area,
    remote_inspect_variable,
    remote_calculate_zonal_mean,
)


class UXarrayComputeAgent(Agent):
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
        self._executor = None

    def _get_executor(self):
        """Get or create Globus Compute executor with AllCodeStrategies.

        AllCodeStrategies serializes the actual function code instead of
        just the module reference, so the HPC endpoint does not need
        uxarray_mcp installed — only uxarray and its dependencies.
        """
        if self._executor is None and self.config.has_endpoint:
            from globus_compute_sdk import Executor
            from globus_compute_sdk.serialize import (
                AllCodeStrategies,
                ComputeSerializer,
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
        if use_remote and self.config.has_endpoint:
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
        if use_remote and self.config.has_endpoint:
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
        if use_remote and self.config.has_endpoint:
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
        if use_remote and self.config.has_endpoint:
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

        future = executor.submit(func, *args, **kwargs)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, future.result, self.config.timeout_seconds
        )

        return result

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


def get_agent() -> UXarrayComputeAgent:
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
    if _agent_instance is None:
        from .config import load_config

        config = load_config()
        _agent_instance = UXarrayComputeAgent(config)
    return _agent_instance
