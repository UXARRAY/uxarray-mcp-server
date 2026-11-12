"""The envelope every tool result promises."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from uxarray_mcp.server.contract import (
    OVERRIDE_TOKEN,
    Refusal,
    check,
    enforce,
    finish,
    guard,
    json_safe,
)


def test_json_safe_removes_nan_and_numpy():
    out = json_safe(
        {"a": float("nan"), "b": np.float32(1.5), "c": np.arange(2), "d": math.inf}
    )
    assert out == {"a": None, "b": 1.5, "c": [0, 1], "d": None}
    json.dumps(out, allow_nan=False)


def test_finish_marks_complete_and_attaches_provenance():
    out = finish(
        {"total": 1.0}, tool="compute", inputs={"grid_path": "g.nc", "x": None}
    )
    assert out["status"] == "complete"
    assert out["physically_interpretable"] is True
    assert out["preconditions"]["status"] == "not_evaluated"
    prov = out["_provenance"]
    assert prov["tool"] == "compute" and prov["inputs"] == {"grid_path": "g.nc"}
    assert prov["venue"] == "local" and "uxarray_version" in prov


def test_finish_promotes_coverage_codes_to_warning():
    out = finish(
        {"coverage": {"warning_codes": ["REMAP_COVERAGE_PARTIAL"]}},
        tool="remap",
        inputs={},
    )
    assert out["status"] == "warning"
    assert out["warning_codes"] == ["REMAP_COVERAGE_PARTIAL"]
    assert out["physically_interpretable"] is False


def test_failed_check_refuses_with_repair():
    checks = [check("radius", False, "no sphere_radius", "pass sphere_radius=6371000")]
    with pytest.raises(Refusal) as exc:
        finish({}, tool="compute", inputs={}, checks=checks)
    payload = exc.value.payload
    assert payload["outcome"] == "input_required"
    assert payload["refusal"]["repairs"] == ["pass sphere_radius=6371000"]
    assert payload["refusal"]["override"]["value"] == OVERRIDE_TOKEN


def test_override_runs_but_marks_unverified():
    checks = [check("radius", False, "", "fix")]
    out = finish(
        {"v": 1}, tool="compute", inputs={}, checks=checks, acknowledge=OVERRIDE_TOKEN
    )
    assert out["status"] == "unverified"
    assert out["physically_interpretable"] is False
    assert "PRECONDITION_FAILED_RADIUS" in out["warning_codes"]
    assert out["preconditions"]["override_used"] is True


def test_wrong_token_is_a_refusal_not_an_override():
    with pytest.raises(Refusal) as exc:
        enforce("op", [check("c", False, "", "r")], acknowledge="please")
    assert "not the override token" in exc.value.payload["refusal"]["hint"]


def test_guard_turns_refusal_into_payload():
    @guard
    def tool():
        raise Refusal({"outcome": "input_required", "refusal": {"summary": "no"}})

    assert tool()["outcome"] == "input_required"


def test_remote_block_sets_venue():
    out = finish(
        {"v": 1, "_remote": {"endpoint": "ucar", "hostname": "n1", "job_id": None}},
        tool="compute",
        inputs={},
    )
    assert out["_provenance"]["venue"] == "hpc:ucar"
    assert out["_provenance"]["remote"] == {"hostname": "n1"}
