"""The transfer tools: conditional registration, and what they return.

The path arithmetic itself is covered in ``test_globus_transfer.py``. What is
checked here is the layer above it: that an install with no
``globus_transfer`` block shows no transfer tools at all, that a refused path
comes back as a result rather than a traceback, and that `doctor` reports on
data movement without going red for a feature nobody configured.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from uxarray_mcp.registry import _CONDITIONAL_NAMES, build_registry
from uxarray_mcp.remote.config import EndpointProfile, GlobusTransferProfile, HPCConfig
from uxarray_mcp.tools import transfer_tools
from uxarray_mcp.tools.execution_control import _transfer_check


def _transfer_profile(**overrides) -> GlobusTransferProfile:
    base = {
        "remote_collection_id": "remote-uuid",
        "local_collection_id": "local-uuid",
        "remote_write_root": "/scratch/rjain",
        "remote_read_root": "/lcrc/group/e3sm",
    }
    base.update(overrides)
    return GlobusTransferProfile(**base)


def _config(transfer: GlobusTransferProfile | None) -> HPCConfig:
    return HPCConfig(
        endpoints={
            "chrysalis": EndpointProfile(
                name="chrysalis",
                endpoint_id="11111111-2222-3333-4444-555555555555",
                globus_transfer=transfer,
            )
        },
        default_endpoint="chrysalis",
    )


class FakeService:
    def __init__(self, entries=None, error=None):
        self.entries = entries or []
        self.error = error
        self.submitted = []

    def _raise(self):
        if self.error:
            raise self.error

    def ls(self, remote_path):
        self._raise()
        return self.entries

    def plan_put(self, local_path, remote_path, label=None):
        self._raise()
        return SimpleNamespace(
            kind="put",
            source_path=str(local_path),
            destination_path=remote_path,
        )

    def plan_get(self, remote_path, local_path, recursive=False, label=None):
        self._raise()
        return SimpleNamespace(
            kind="get",
            source_path=remote_path,
            destination_path=str(local_path),
        )

    def submit(self, plan):
        self.submitted.append(plan)
        return {"task_id": "task-1", "status": "Accepted"}

    def status(self, task_id):
        self._raise()
        return {"task_id": task_id, "status": "SUCCEEDED"}


@pytest.fixture
def wired(monkeypatch):
    """Point the tools at a fake service and a configured endpoint."""
    service = FakeService()
    monkeypatch.setattr(
        transfer_tools, "_service_for", lambda endpoint: (service, "chrysalis")
    )
    return service


class TestAnUnconfiguredInstallShowsNoTransferTools:
    def test_they_are_absent_when_no_endpoint_declares_a_block(self, monkeypatch):
        monkeypatch.setattr(
            "uxarray_mcp.registry._transfers_are_configured", lambda: False
        )
        tools = build_registry(profile="deferred-full").list_tools()
        assert not [name for name in tools if "transfer_" in name]

    def test_they_appear_when_one_does(self, monkeypatch):
        monkeypatch.setattr(
            "uxarray_mcp.registry._transfers_are_configured", lambda: True
        )
        tools = build_registry(profile="deferred-full").list_tools()
        for raw in _CONDITIONAL_NAMES:
            assert any(name.endswith(raw) for name in tools), raw

    def test_they_are_deferred_not_visible(self, monkeypatch):
        monkeypatch.setattr(
            "uxarray_mcp.registry._transfers_are_configured", lambda: True
        )
        status = build_registry(profile="deferred-full").get_tools_status()
        transfer_rows = [s for s in status if "transfer_" in s["name"]]
        assert transfer_rows
        assert all(row["defer"] for row in transfer_rows)

    def test_the_coverage_check_still_fires_for_anything_else(self, monkeypatch):
        # The exemption is for the conditional names only; a genuinely
        # unregistered tool must still be a loud failure.
        monkeypatch.setattr(
            "uxarray_mcp.registry._transfers_are_configured", lambda: False
        )
        monkeypatch.setattr(
            "uxarray_mcp.registry._DEFERRED_TOOLS",
            {"inspect": ("inspect_mesh",)},
        )
        with pytest.raises(RuntimeError, match="Namespace plan out of date"):
            build_registry(profile="deferred-full")

    def test_configuration_is_read_from_the_endpoints(self, monkeypatch):
        monkeypatch.setattr(
            transfer_tools, "_config", lambda: (_config(_transfer_profile()), None)
        )
        assert transfer_tools.transfers_are_configured() is True
        monkeypatch.setattr(transfer_tools, "_config", lambda: (_config(None), None))
        assert transfer_tools.transfers_are_configured() is False

    def test_an_unreadable_config_answers_no_rather_than_raising(self, monkeypatch):
        def boom():
            raise OSError("no config here")

        monkeypatch.setattr(transfer_tools, "_config", boom)
        assert transfer_tools.transfers_are_configured() is False


class TestARefusalComesBackAsAResult:
    def test_a_path_outside_the_root_is_reported_not_raised(self, monkeypatch):
        from uxarray_mcp.remote.transfer import PathOutsideRoot

        service = FakeService(error=PathOutsideRoot("/etc/passwd is outside /scratch"))
        monkeypatch.setattr(
            transfer_tools, "_service_for", lambda endpoint: (service, "chrysalis")
        )
        result = transfer_tools.transfer_put("mesh.nc", "/etc/passwd")
        assert result["submitted"] is False
        assert result["reason"] == "PathOutsideRoot"
        assert "outside" in result["message"]
        assert service.submitted == []

    def test_an_endpoint_without_a_block_says_what_to_add(self, monkeypatch):
        monkeypatch.setattr(transfer_tools, "_config", lambda: (_config(None), None))
        result = transfer_tools.transfer_ls("/scratch/rjain")
        assert result["submitted"] is False
        assert "globus_transfer" in result["message"]

    def test_every_result_carries_provenance_and_an_operation_id(self, wired):
        result = transfer_tools.transfer_ls("/scratch/rjain")
        assert result["_provenance"]["operation_id"]
        assert result["_provenance"]["tool"] == "transfer_ls"


class TestTheToolsReportWhatTheyDid:
    def test_ls_counts_its_entries(self, monkeypatch):
        service = FakeService(entries=[{"name": "out.nc"}, {"name": "run"}])
        monkeypatch.setattr(
            transfer_tools, "_service_for", lambda endpoint: (service, "chrysalis")
        )
        result = transfer_tools.transfer_ls("cases")
        assert result["entry_count"] == 2
        assert result["endpoint"] == "chrysalis"

    def test_put_reports_the_direction_and_task(self, wired):
        result = transfer_tools.transfer_put("mesh.nc", "runs/mesh.nc")
        assert result["submitted"] is True
        assert result["direction"] == "upload"
        assert result["task_id"] == "task-1"

    def test_get_reports_the_other_direction(self, wired):
        result = transfer_tools.transfer_get("cases/out.nc", "out.nc")
        assert result["direction"] == "download"
        assert wired.submitted[0].kind == "get"

    def test_status_reads_a_submitted_task_back(self, wired):
        result = transfer_tools.transfer_status("task-1")
        assert result["status"] == "SUCCEEDED"


class TestDoctorReportsOnDataMovement:
    def test_nothing_configured_passes_and_explains(self):
        check = _transfer_check(_config(None), None, False)
        assert check["passed"] is True
        assert check["details"]["configured"] is False
        assert "globus_transfer" in check["guidance"]

    def test_a_block_without_a_write_root_fails(self):
        profile = _transfer_profile(remote_write_root=None)
        check = _transfer_check(_config(profile), None, False)
        assert check["passed"] is False
        assert "remote_write_root" in check["summary"]

    def test_a_client_that_cannot_be_built_fails_with_the_install_step(
        self, monkeypatch
    ):
        from uxarray_mcp.remote import transfer as transfer_mod

        def boom(profile):
            raise transfer_mod.TransferError("globus-sdk is not installed")

        monkeypatch.setattr(transfer_mod, "default_transfer_client", boom)
        check = _transfer_check(_config(_transfer_profile()), None, False)
        assert check["passed"] is False
        assert "transfer" in check["guidance"]

    def test_without_the_probe_it_stops_at_authentication(self, monkeypatch):
        from uxarray_mcp.remote import transfer as transfer_mod

        monkeypatch.setattr(
            transfer_mod, "default_transfer_client", lambda profile: object()
        )
        check = _transfer_check(_config(_transfer_profile()), None, False)
        assert check["passed"] is True
        assert "not probed" in check["summary"]

    def test_the_probe_lists_the_write_root(self, monkeypatch):
        from uxarray_mcp.remote import transfer as transfer_mod

        class Client:
            def operation_ls(self, collection_id, **kwargs):
                assert kwargs["path"] == "/scratch/rjain"
                return {"DATA": [{"name": "runs", "type": "dir"}]}

        monkeypatch.setattr(
            transfer_mod, "default_transfer_client", lambda profile: Client()
        )
        check = _transfer_check(_config(_transfer_profile()), None, True)
        assert check["passed"] is True
        assert check["details"]["entry_count"] == 1

    def test_a_write_root_the_collection_will_not_show_fails(self, monkeypatch):
        from uxarray_mcp.remote import transfer as transfer_mod

        class Client:
            def operation_ls(self, collection_id, **kwargs):
                raise RuntimeError("ClientError.404.NotFound")

        monkeypatch.setattr(
            transfer_mod, "default_transfer_client", lambda profile: Client()
        )
        check = _transfer_check(_config(_transfer_profile()), None, True)
        assert check["passed"] is False
        assert "collection_roots" in check["guidance"]
