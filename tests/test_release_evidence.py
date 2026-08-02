"""Release evidence remains tied to checked-in benchmark inputs."""

import json

from benchmarks.release_evidence import EVIDENCE_SCHEMA_VERSION, build_release_evidence


def test_release_evidence_is_complete_and_reproducible() -> None:
    evidence = build_release_evidence()

    assert evidence["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert evidence["model"] == "none"
    assert evidence["dataset"]["case_count"] == 7
    assert evidence["claims"]["producer_recall"] == {
        "before": 0.142857,
        "after": 1.0,
        "delta": 0.857143,
    }
    assert evidence["claims"]["candidate_plan_coverage"] == {
        "before": 0.47619,
        "after": 1.0,
        "delta": 0.52381,
    }
    assert all(row["selected_target"] == row["expected_target"] for row in evidence["cases"])
    assert "/home/" not in json.dumps(evidence)
