"""The multi-turn eval harness has to keep separating good runs from bad (#93).

Scoring code that silently stops discriminating is worse than no eval,
so the two scripted adapters are pinned here as a regression fence.
"""

from __future__ import annotations

import pytest

from evals.multi_turn.run import make_fixtures, run_suite, summarize
from evals.multi_turn.scripted import disciplined, naive
from evals.multi_turn.tasks import build_tasks


@pytest.fixture(scope="module")
def disciplined_report():
    return run_suite(disciplined, "scripted:disciplined", "test")


@pytest.fixture(scope="module")
def naive_report():
    return run_suite(naive, "scripted:naive", "test")


def test_every_task_needs_more_than_one_call(tmp_path):
    """A task satisfiable in one call would measure nothing."""
    tasks = build_tasks(make_fixtures(tmp_path))

    assert tasks
    assert all(len(task["requires"]) >= 2 for task in tasks)


def test_disciplined_run_chains_every_task(disciplined_report):
    summary = disciplined_report["summary"]

    assert summary["chained"] == summary["tasks"]
    assert summary["finished"] == summary["tasks"]


def test_disciplined_run_keeps_handle_discipline(disciplined_report):
    summary = disciplined_report["summary"]

    assert summary["handles_invented"] == 0
    assert summary["handles_dropped"] == 0
    assert summary["overrides_used"] == 0


def test_disciplined_run_recovers_from_every_injected_fault(disciplined_report):
    summary = disciplined_report["summary"]

    assert summary["fault_tasks"] == 2
    assert summary["recovered"] == summary["fault_tasks"]


def test_refusal_is_repaired_rather_than_overridden(disciplined_report):
    run = next(
        r for r in disciplined_report["runs"] if r["task_id"] == "refusal_then_repair"
    )

    assert run["refusals_seen"] == 1
    assert run["override_used"] is False
    assert run["recovered"] is True


def test_interruption_is_resumed_not_restarted(disciplined_report):
    run = next(
        r
        for r in disciplined_report["runs"]
        if r["task_id"] == "interrupted_workflow_resume"
    )

    assert "resume_workflow" in run["call_names"]
    assert run["call_names"].count("run_workflow") == 1
    assert run["recovered"] is True


def test_naive_run_is_scored_worse_on_every_axis(disciplined_report, naive_report):
    good = disciplined_report["summary"]
    bad = naive_report["summary"]

    assert bad["chained"] < good["chained"]
    assert bad["handles_invented"] > good["handles_invented"]
    assert bad["handles_dropped"] > good["handles_dropped"]
    assert bad["recovered"] < good["recovered"]


def test_forcing_the_override_does_not_count_as_recovery(naive_report):
    """The failure mode #86 exists to prevent must not score as success."""
    run = next(r for r in naive_report["runs"] if r["task_id"] == "refusal_then_repair")

    assert run["override_used"] is True
    assert run["recovered"] is False


def test_summarize_handles_an_empty_run_list():
    assert summarize([])["mean_calls"] == 0.0
