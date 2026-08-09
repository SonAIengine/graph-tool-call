from __future__ import annotations

from benchmarks.observability_release import (
    EVIDENCE_SCHEMA_VERSION,
    MAX_P95_MS_PER_SPAN,
    build_observability_evidence,
    validate_observability_evidence,
)
from graph_tool_call import __version__


def test_observability_release_evidence_passes_all_contract_gates() -> None:
    evidence = build_observability_evidence(iterations=5)

    assert evidence["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert evidence["release_ref"] == f"v{__version__}"
    assert evidence["status"] == "pass"
    assert all(evidence["checks"].values())
    assert evidence["scenario"]["reason_coverage"] == 1.0
    assert evidence["overhead"]["per_span_p95_ms"] < MAX_P95_MS_PER_SPAN
    assert validate_observability_evidence(evidence) == []


def test_observability_release_validation_rejects_failed_artifact() -> None:
    evidence = build_observability_evidence(iterations=2)
    evidence["checks"]["secret_scan_passed"] = False
    evidence["status"] = "fail"

    assert validate_observability_evidence(evidence) == ["checks", "status"]
