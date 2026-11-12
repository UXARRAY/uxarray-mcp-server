"""The shipped shim running in a real separate process (needs the hpc extra)."""

from __future__ import annotations

import pytest

from tests.fake_endpoint import MEMORY_LIMITS_ENFORCED, fake_endpoint
from uxarray_mcp.remote import executor
from uxarray_mcp.remote.config import EndpointProfile, HPCConfig

pytestmark = pytest.mark.hpc


@pytest.fixture
def config(state_dir):
    executor.reset()
    yield HPCConfig(
        endpoints={
            "fake": EndpointProfile(
                name="fake", endpoint_id="0" * 36, path_prefixes=("/fake/",)
            )
        },
        default_endpoint="fake",
        execution_mode="auto",
        timeout_seconds=120,
    )
    executor.reset()


def test_shim_runs_core_op_in_a_separate_process(config, structured_mesh_files):
    grid, _ = structured_mesh_files
    with fake_endpoint() as ep:
        out = executor.submit(
            "area", {"grid_path": grid, "sphere_radius": 6371000.0}, config=config
        )
    assert ep.submissions == 1 and ep.calls == ["run_op"]
    assert out["total_area"] > 0
    assert out["_remote"]["hostname"] and out["_remote"]["server_version"]
    assert "warnings" not in out  # same interpreter, no drift


def test_plot_png_survives_the_wire(config):
    with fake_endpoint():
        out = executor.submit(
            "plot_mesh",
            {"grid_path": "healpix:1", "width": 200, "height": 100},
            config=config,
        )
    assert out["png"][:8] == b"\x89PNG\r\n\x1a\n" and out["render_mode"] == "polygons"


def test_missing_file_on_worker_is_typed(config):
    with fake_endpoint():
        with pytest.raises(executor.RemoteError) as exc:
            executor.submit(
                "inspect_mesh", {"grid_path": "/fake/none.nc"}, config=config
            )
    assert exc.value.code in (executor.FILE_NOT_FOUND_ON_WORKER, executor.WORKER_LOST)


@pytest.mark.skipif(not MEMORY_LIMITS_ENFORCED, reason="RLIMIT_AS only on Linux")
def test_oom_killed_worker_is_worker_lost(config):
    with fake_endpoint(memory_limit_gib=0.05):
        with pytest.raises(executor.RemoteError) as exc:
            executor.submit(
                "area",
                {"grid_path": "healpix:6", "sphere_radius": 6371000.0},
                config=config,
            )
    assert exc.value.code == executor.WORKER_LOST
