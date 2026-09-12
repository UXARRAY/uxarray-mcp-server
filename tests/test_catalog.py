"""Tests for the list_datasets catalog tool."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from uxarray_mcp.tools.catalog import list_datasets


def _make_files(base: Path, files: list[str]) -> None:
    """Create empty files at the given relative paths."""
    for f in files:
        p = base / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


class TestListDatasetsBasic:
    """Basic functionality tests."""

    def test_empty_directory(self, tmp_path):
        result = list_datasets(str(tmp_path))
        assert result["total_files"] == 0
        assert result["groups"] == []
        assert result["truncated"] is False
        assert "_provenance" in result
        assert any("No mesh" in r for r in result["recommendations"])

    def test_finds_nc_files(self, tmp_path):
        _make_files(tmp_path, ["grid.nc", "data.nc"])
        result = list_datasets(str(tmp_path))
        assert result["total_files"] == 2

    def test_finds_hdf5_files(self, tmp_path):
        _make_files(tmp_path, ["output.h5", "mesh.nc4"])
        result = list_datasets(str(tmp_path))
        assert result["total_files"] == 2

    def test_ignores_non_mesh_extensions(self, tmp_path):
        _make_files(tmp_path, ["notes.txt", "script.py", "data.nc"])
        result = list_datasets(str(tmp_path))
        assert result["total_files"] == 1

    def test_directory_field(self, tmp_path):
        result = list_datasets(str(tmp_path))
        assert result["directory"] == str(tmp_path)

    def test_provenance_tool_name(self, tmp_path):
        result = list_datasets(str(tmp_path))
        assert result["_provenance"]["tool"] == "list_datasets"

    def test_provenance_inputs(self, tmp_path):
        result = list_datasets(str(tmp_path), recursive=True, max_files=50)
        inputs = result["_provenance"]["inputs"]
        assert inputs["recursive"] is True
        assert inputs["max_files"] == 50


class TestListDatasetsClassification:
    """File classification heuristics."""

    def test_grid_file_classified(self, tmp_path):
        _make_files(tmp_path, ["grid.nc"])
        result = list_datasets(str(tmp_path))
        file_entry = result["groups"][0]["files"][0]
        assert file_entry["kind"] == "grid"

    def test_mesh_file_classified(self, tmp_path):
        _make_files(tmp_path, ["mesh.QU.480km.nc"])
        result = list_datasets(str(tmp_path))
        file_entry = result["groups"][0]["files"][0]
        assert file_entry["kind"] == "grid"

    def test_data_file_classified(self, tmp_path):
        _make_files(tmp_path, ["data.nc"])
        result = list_datasets(str(tmp_path))
        file_entry = result["groups"][0]["files"][0]
        assert file_entry["kind"] == "data"

    def test_unknown_file_classified(self, tmp_path):
        _make_files(tmp_path, ["something.nc"])
        result = list_datasets(str(tmp_path))
        file_entry = result["groups"][0]["files"][0]
        assert file_entry["kind"] == "unknown"

    def test_suggested_tool_for_grid(self, tmp_path):
        _make_files(tmp_path, ["grid.nc"])
        result = list_datasets(str(tmp_path))
        entry = result["groups"][0]["files"][0]
        assert "inspect_mesh" in entry["suggested_tool"]

    def test_suggested_tool_for_data(self, tmp_path):
        _make_files(tmp_path, ["data.nc"])
        result = list_datasets(str(tmp_path))
        entry = result["groups"][0]["files"][0]
        assert "inspect_variable" in entry["suggested_tool"]


class TestListDatasetsGrouping:
    """Grouping by subdirectory."""

    def test_flat_directory_has_dot_subdir(self, tmp_path):
        _make_files(tmp_path, ["grid.nc"])
        result = list_datasets(str(tmp_path))
        assert result["groups"][0]["subdir"] == "."

    def test_groups_by_subdir(self, tmp_path):
        _make_files(tmp_path, ["QU/grid.nc", "dyamond/data.nc"])
        result = list_datasets(str(tmp_path), recursive=True)
        subdirs = {g["subdir"] for g in result["groups"]}
        assert "QU" in subdirs
        assert "dyamond" in subdirs

    def test_non_recursive_ignores_subdirs(self, tmp_path):
        _make_files(tmp_path, ["top.nc", "sub/nested.nc"])
        result = list_datasets(str(tmp_path), recursive=False)
        assert result["total_files"] == 1

    def test_recursive_finds_nested(self, tmp_path):
        _make_files(tmp_path, ["top.nc", "sub/nested.nc", "a/b/c/deep.nc"])
        result = list_datasets(str(tmp_path), recursive=True)
        assert result["total_files"] == 3


class TestListDatasetsLimits:
    """max_files truncation."""

    def test_truncation(self, tmp_path):
        _make_files(tmp_path, [f"file_{i}.nc" for i in range(10)])
        result = list_datasets(str(tmp_path), max_files=3)
        assert result["total_files"] == 3
        assert result["truncated"] is True
        assert any("truncated" in r.lower() for r in result["recommendations"])

    def test_no_truncation_when_under_limit(self, tmp_path):
        _make_files(tmp_path, ["a.nc", "b.nc"])
        result = list_datasets(str(tmp_path), max_files=10)
        assert result["truncated"] is False


class TestListDatasetsErrors:
    """Error handling."""

    def test_nonexistent_directory(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            list_datasets("/nonexistent/path/that/does/not/exist")

    def test_file_not_directory(self, tmp_path):
        f = tmp_path / "file.nc"
        f.touch()
        with pytest.raises(ValueError, match="Not a directory"):
            list_datasets(str(f))

    def test_remote_scan_fails_fast_when_endpoint_unavailable(self, tmp_path):
        with (
            patch("uxarray_mcp.tools.catalog.get_agent") as mock_get_agent,
            patch(
                "uxarray_mcp.tools.catalog._endpoint_is_ready",
                return_value=(False, "endpoint status='stopped': "),
            ),
        ):
            mock_agent = MagicMock()
            mock_agent.config.endpoint_id = "fake-endpoint"
            mock_get_agent.return_value = mock_agent

            with pytest.raises(RuntimeError, match="HPC endpoint not ready"):
                list_datasets(str(tmp_path), use_remote=True)

    def test_remote_scan_forwards_named_endpoint(self, tmp_path):
        with (
            patch("uxarray_mcp.tools.catalog.get_agent") as mock_get_agent,
            patch(
                "uxarray_mcp.tools.catalog._endpoint_is_ready",
                return_value=(True, "ok"),
            ),
            patch("uxarray_mcp.tools.remote_tools._run_sync") as mock_run_sync,
        ):
            mock_agent = MagicMock()
            mock_agent.config.endpoint_id = "improv-id"
            mock_agent.config.endpoint_name = "improv"
            mock_get_agent.return_value = mock_agent
            mock_run_sync.return_value = {
                "directory": str(tmp_path),
                "total_files": 0,
                "truncated": False,
                "groups": [],
                "recommendations": [],
                "_provenance": {"warnings": []},
            }

            result = list_datasets(str(tmp_path), use_remote=True, endpoint="improv")

            mock_get_agent.assert_called_once_with(
                endpoint="improv", path=str(tmp_path)
            )
            assert result["_provenance"]["inputs"]["endpoint"] == "improv"


class TestListDatasetsRecommendations:
    """Recommendation logic."""

    def test_grid_and_data_recommends_pairing(self, tmp_path):
        _make_files(tmp_path, ["grid.nc", "data.nc"])
        result = list_datasets(str(tmp_path))
        combined = " ".join(result["recommendations"])
        assert "pair" in combined.lower() or "grid" in combined.lower()

    def test_grid_only_recommends_inspect(self, tmp_path):
        _make_files(tmp_path, ["grid.nc"])
        result = list_datasets(str(tmp_path))
        combined = " ".join(result["recommendations"])
        assert "inspect_mesh" in combined

    def test_size_mb_present(self, tmp_path):
        _make_files(tmp_path, ["grid.nc"])
        result = list_datasets(str(tmp_path))
        entry = result["groups"][0]["files"][0]
        assert "size_mb" in entry


class TestListDatasetsArchiveRoot:
    """A directory whose datasets are all one level down.

    This is how GDEX and most model archives are laid out, and the
    non-recursive scan of such a root is the ordinary way to get zero hits.
    Reporting only ``total_files: 0`` made a wrong flag look like a missing
    dataset, so the recommendation names what is actually there.
    """

    def test_subdirectories_are_named_when_no_files_match(self, tmp_path):
        _make_files(tmp_path, ["d651007/data.nc", "d651014/data.nc"])
        result = list_datasets(str(tmp_path), recursive=False)
        combined = " ".join(result["recommendations"])
        assert result["total_files"] == 0
        assert "d651007" in combined
        assert "d651014" in combined
        assert "recursive=True" in combined

    def test_the_subdirectory_count_is_reported(self, tmp_path):
        _make_files(tmp_path, [f"member_{i:02d}/data.nc" for i in range(14)])
        result = list_datasets(str(tmp_path), recursive=False)
        combined = " ".join(result["recommendations"])
        assert "14 subdirectories" in combined
        # Only the first ten are named; the rest are counted, not listed.
        assert "(+4 more)" in combined

    def test_a_single_subdirectory_reads_as_singular(self, tmp_path):
        _make_files(tmp_path, ["only/data.nc"])
        result = list_datasets(str(tmp_path), recursive=False)
        combined = " ".join(result["recommendations"])
        assert "1 subdirectory:" in combined

    def test_a_genuinely_empty_directory_still_says_so(self, tmp_path):
        result = list_datasets(str(tmp_path), recursive=False)
        combined = " ".join(result["recommendations"])
        assert "No mesh or data files found" in combined
        assert "subdirector" not in combined

    def test_a_recursive_scan_that_finds_nothing_does_not_blame_subdirs(self, tmp_path):
        """recursive=True already looked inside, so the hint would be wrong."""
        _make_files(tmp_path, ["sub/notes.txt"])
        result = list_datasets(str(tmp_path), recursive=True)
        combined = " ".join(result["recommendations"])
        assert result["total_files"] == 0
        assert "subdirector" not in combined

    def test_the_remote_scan_gives_the_same_hint(self, tmp_path):
        """The worker copy is the one that meets GDEX; it must not drift.

        ``_remote_catalog_fn`` is shipped to the endpoint by value and
        cannot call module scope, so the logic is duplicated there. Test
        the duplicate rather than trust it.
        """
        from uxarray_mcp.tools.catalog import _remote_catalog_fn

        _make_files(tmp_path, ["d651007/data.nc", "d651014/data.nc"])
        result = _remote_catalog_fn(str(tmp_path), False, 200)
        combined = " ".join(result["recommendations"])
        assert result["total_files"] == 0
        assert "d651007" in combined
        assert "recursive=True" in combined
