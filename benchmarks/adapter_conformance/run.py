"""Run deterministic E0 ingest-adapter conformance over the paper corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from benchmarks.corpus.manifest import (
    DEFAULT_MANIFEST_PATH,
    load_corpus_manifest,
    validate_corpus_manifest,
)
from benchmarks.experiment.artifact import (
    ExperimentArtifact,
    finalize_artifact,
    validate_artifact,
    write_artifact,
)
from graph_tool_call import UnknownIngestAdapterError, ingest_source
from graph_tool_call.core.tool import ToolSchema

from .expectations import (
    ToolExpectation,
    inspect_source_expectations,
    normalized_auth_requirements,
    normalized_auth_scheme_fact,
    normalized_tool_key,
    schema_signatures,
)

METRIC_NAMES = (
    "request_schema_preservation",
    "response_schema_preservation",
    "auth_security_preservation",
    "execution_template_generation",
    "api_contract_consumes_extraction",
    "api_contract_produces_extraction",
    "deterministic_serialization_replay",
)
EXPECTATION_POLICY_REVISION = "source-declared-facts-v1"
DIAGNOSTIC_POLICY_REVISION = "structured-negative-probes-v1"
MAX_FAILURE_SAMPLES = 12


def run_adapter_conformance(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    splits: tuple[str, ...] = ("train", "dev"),
    output_path: str | Path = "/tmp/graph-tool-call-adapter-conformance.json",
    allow_held_out: bool = False,
    created_at: str | None = None,
) -> ExperimentArtifact:
    """Evaluate schema, auth, execution, contract, replay, and diagnostic fidelity."""
    normalized_splits = tuple(dict.fromkeys(split.strip() for split in splits if split.strip()))
    invalid_splits = sorted(set(normalized_splits) - {"train", "dev", "test"})
    if not normalized_splits or invalid_splits:
        raise ValueError(f"splits must contain train, dev, or test; invalid={invalid_splits}")
    if "test" in normalized_splits and not allow_held_out:
        raise ValueError("Held-out test access requires --allow-held-out.")

    resolved_manifest = Path(manifest_path).resolve()
    report = validate_corpus_manifest(
        resolved_manifest,
        verify_hashes=True,
        verify_ingest="test" in normalized_splits,
    )
    if not report.integrity_ready:
        blockers = [
            issue.code
            for issue in report.issues
            if issue.scope == "integrity" and issue.severity == "blocker"
        ]
        raise ValueError(f"Corpus integrity validation failed: {', '.join(blockers)}")
    if "test" in normalized_splits and not report.paper_ready:
        raise ValueError(
            "Held-out test access is blocked until the corpus paper-readiness gate passes."
        )

    manifest = load_corpus_manifest(resolved_manifest)
    manifest_root = resolved_manifest.parent
    selected_sources = [
        source
        for source in manifest["sources"]
        if source.get("paper_core") is True and source.get("split") in normalized_splits
    ]
    cases = [_evaluate_source(source, manifest_root) for source in selected_sources]
    diagnostic_probes = _run_diagnostic_probes()
    summary = _summarize(cases, diagnostic_probes)
    manifest_sha256 = _sha256(resolved_manifest)
    output = str(Path(output_path))
    replay_command = [
        "python",
        "-m",
        "benchmarks.adapter_conformance.run",
        "--manifest",
        str(manifest_path),
        "--splits",
        ",".join(normalized_splits),
        "--out",
        output,
    ]
    if allow_held_out:
        replay_command.append("--allow-held-out")

    artifact = ExperimentArtifact(
        benchmark="public-heterogeneous-adapter-conformance",
        methodology="deterministic-source-fidelity-v1",
        run_kind="deterministic",
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        seed=0,
        dataset={
            "id": manifest["corpus_id"],
            "split": normalized_splits[0] if len(normalized_splits) == 1 else "mixed",
            "splits": list(normalized_splits),
            "manifest_sha256": manifest_sha256,
            "held_out_accessed": "test" in normalized_splits,
        },
        config={
            "expectation_policy_revision": EXPECTATION_POLICY_REVISION,
            "diagnostic_policy_revision": DIAGNOSTIC_POLICY_REVISION,
            "failure_sample_limit": MAX_FAILURE_SAMPLES,
            "metrics": list(METRIC_NAMES),
            "source_fact_policy": (
                "Raw source documents are inspected independently from built-in adapters. "
                "Only source-declared facts enter metric denominators."
            ),
        },
        replay={"command": replay_command, "working_directory": "."},
        summary=summary,
        statistics={
            "aggregation": {
                "micro": "sum(passed)/sum(applicable)",
                "macro": "mean(source rate) over applicable sources",
                "confidence_intervals": False,
            }
        },
        cases=cases,
        source={
            "type": "paper_adapter_conformance_manifest",
            "sha256": manifest_sha256,
            "diagnostic_probes": diagnostic_probes,
        },
    )
    finalize_artifact(artifact)
    validation = validate_artifact(artifact)
    if not validation.valid:
        codes = ", ".join(issue.code for issue in validation.issues)
        raise ValueError(f"Generated experiment artifact is invalid: {codes}")
    return artifact


def _evaluate_source(source: dict[str, Any], manifest_root: Path) -> dict[str, Any]:
    raw_source = _read_json_value(manifest_root / source["snapshot_path"])
    source_type = str(source["source_type"])
    expectations = inspect_source_expectations(
        raw_source,
        source_type=source_type,
        ingest_options=source.get("ingest_options") or {},
    )
    options = source.get("ingest_options") or {}
    first = ingest_source(raw_source, format_hint=source["adapter"], **options)
    second = ingest_source(raw_source, format_hint=source["adapter"], **options)
    first_payload = first.to_dict(include_tools=True)
    second_payload = second.to_dict(include_tools=True)
    first_json = _canonical_json(first_payload)
    second_json = _canonical_json(second_payload)
    serialization_passed = _json_round_trip(first_payload) and first_json == second_json

    observed_tools = {
        normalized_tool_key(tool.metadata, source_type=source_type, name=tool.name): tool
        for tool in first.tools
    }
    metric_rows = {
        metric: {"applicable": 0, "passed": 0, "failure_samples": []} for metric in METRIC_NAMES
    }
    for key, expectation in expectations.tools.items():
        tool = observed_tools.get(key)
        _score_tool_expectation(
            key,
            source_type=source_type,
            expectation=expectation,
            tool=tool,
            metric_rows=metric_rows,
        )
    _record(
        metric_rows["deterministic_serialization_replay"],
        applicable=True,
        passed=serialization_passed,
        sample=source["id"],
    )
    metrics = {name: _finalize_metric(row) for name, row in metric_rows.items()}
    missing_keys = sorted(set(expectations.tools) - set(observed_tools))
    unexpected_keys = sorted(set(observed_tools) - set(expectations.tools))
    return {
        "case_id": str(source["id"]),
        "query": "",
        "context": {
            "family_id": source["family_id"],
            "source_type": source_type,
            "split": source["split"],
            "adapter": source["adapter"],
        },
        "expected": {
            "tool_count": len(expectations.tools),
            "source_declared_fact_counts": {
                name: metrics[name]["applicable"]
                for name in METRIC_NAMES
                if name != "deterministic_serialization_replay"
            },
        },
        "observed": {
            "tool_count": len(first.tools),
            "adapter": first.adapter,
            "ready": first.ready,
            "issue_codes": [issue.code for issue in first.issues],
            "missing_tool_keys": missing_keys[:MAX_FAILURE_SAMPLES],
            "unexpected_tool_keys": unexpected_keys[:MAX_FAILURE_SAMPLES],
            "serialization_sha256": hashlib.sha256(first_json.encode()).hexdigest(),
            "replay_serialization_sha256": hashlib.sha256(second_json.encode()).hexdigest(),
        },
        "metrics": {
            **metrics,
            "tool_count_exact": float(
                len(expectations.tools) == len(first.tools)
                and not missing_keys
                and not unexpected_keys
            ),
        },
        "stages": {
            "expectation_inspection": {"policy": EXPECTATION_POLICY_REVISION},
            "ingest_replay": {"count": 2},
        },
        "failure": {},
    }


def _score_tool_expectation(
    key: str,
    *,
    source_type: str,
    expectation: ToolExpectation,
    tool: ToolSchema | None,
    metric_rows: dict[str, dict[str, Any]],
) -> None:
    request_passed = tool is not None and _request_preserved(
        source_type,
        expectation,
        tool,
    )
    _record(
        metric_rows["request_schema_preservation"],
        applicable=expectation.request_applicable,
        passed=request_passed,
        sample=key,
    )
    response_passed = tool is not None and _response_preserved(
        source_type,
        expectation,
        tool,
    )
    _record(
        metric_rows["response_schema_preservation"],
        applicable=expectation.response_applicable,
        passed=response_passed,
        sample=key,
    )
    auth_passed = tool is not None and _auth_preserved(expectation, tool)
    _record(
        metric_rows["auth_security_preservation"],
        applicable=bool(expectation.auth_schemes),
        passed=auth_passed,
        sample=key,
    )
    execution_passed = tool is not None and _execution_template_ready(
        expectation,
        tool,
    )
    _record(
        metric_rows["execution_template_generation"],
        applicable=bool(expectation.execution_transport),
        passed=execution_passed,
        sample=key,
    )
    contract = tool.metadata.get("api_contract") if tool is not None else {}
    if not isinstance(contract, dict):
        contract = {}
    consumes = contract.get("consumes") if isinstance(contract.get("consumes"), list) else []
    produces = contract.get("produces") if isinstance(contract.get("produces"), list) else []
    _record(
        metric_rows["api_contract_consumes_extraction"],
        applicable=expectation.consumes_expected,
        passed=tool is not None
        and _contract_consumes_preserved(
            expectation,
            consumes,
        ),
        sample=key,
    )
    _record(
        metric_rows["api_contract_produces_extraction"],
        applicable=expectation.produces_expected,
        passed=tool is not None
        and _contract_produces_preserved(
            expectation,
            produces,
        ),
        sample=key,
    )


def _request_preserved(
    source_type: str,
    expectation: ToolExpectation,
    tool: ToolSchema,
) -> bool:
    metadata = tool.metadata
    observed_schema = metadata.get("request_body_schema")
    if source_type == "openapi":
        observed_parameters = {
            str(row.get("name"))
            for row in (metadata.get("openapi") or {}).get("parameters") or []
            if isinstance(row, dict) and isinstance(row.get("name"), str)
        }
        fields_preserved = expectation.request_fields.issubset(observed_parameters)
        if expectation.request_schema is None:
            return fields_preserved
        return fields_preserved and _schema_contains(
            expectation.request_signatures,
            observed_schema,
        )
    if not isinstance(observed_schema, dict):
        return False
    observed_fields = {
        str(name) for name in (observed_schema.get("properties") or {}) if isinstance(name, str)
    }
    if not expectation.request_fields.issubset(observed_fields):
        return False
    if source_type == "graphql-introspection":
        properties = observed_schema.get("properties") or {}
        required = set(observed_schema.get("required") or [])
        observed_types = frozenset(
            (
                name,
                str((properties.get(name) or {}).get("type") or ""),
                name in required,
            )
            for name in expectation.request_fields
        )
        return expectation.request_field_types.issubset(observed_types)
    if source_type == "mcp" and expectation.request_schema is not None:
        return _schema_contains(expectation.request_signatures, observed_schema)
    return True


def _response_preserved(
    source_type: str,
    expectation: ToolExpectation,
    tool: ToolSchema,
) -> bool:
    observed_schema = tool.metadata.get("response_schema")
    if not isinstance(observed_schema, dict):
        return False
    if source_type == "graphql-introspection":
        root_field = (tool.metadata.get("graphql") or {}).get("root_field")
        data = (observed_schema.get("properties") or {}).get("data")
        root_schema = (
            (data.get("properties") or {}).get(root_field) if isinstance(data, dict) else None
        )
        return bool(
            isinstance(root_schema, dict)
            and root_schema.get("type") == expectation.graphql_response_root_type
            and (tool.metadata.get("graphql") or {}).get("return_type")
            == expectation.graphql_return_type
        )
    if expectation.response_schema is None:
        return True
    return _schema_contains(expectation.response_signatures, observed_schema)


def _auth_preserved(expectation: ToolExpectation, tool: ToolSchema) -> bool:
    security = (tool.metadata.get("openapi") or {}).get("security")
    if not isinstance(security, dict):
        return False
    observed_schemes = set((security.get("schemes") or {}).keys())
    if not expectation.auth_schemes.issubset(observed_schemes):
        return False
    observed_scheme_facts = frozenset(
        normalized_auth_scheme_fact(name, scheme)
        for name, scheme in (security.get("schemes") or {}).items()
    )
    if not expectation.auth_scheme_facts.issubset(observed_scheme_facts):
        return False
    if normalized_auth_requirements(security.get("requirements")) != expectation.auth_requirements:
        return False
    if not expectation.required_auth_schemes:
        return True
    observed_requirements = {
        str(name)
        for requirement in security.get("requirements") or []
        if isinstance(requirement, dict)
        for name in requirement
    }
    contract = tool.metadata.get("api_contract") or {}
    observed_contract_schemes = {
        str(scheme)
        for row in contract.get("consumes") or []
        if isinstance(row, dict) and row.get("kind") == "auth"
        for scheme in row.get("security_schemes") or []
    }
    return expectation.required_auth_schemes.issubset(
        observed_requirements & observed_contract_schemes
    )


def _execution_template_ready(expectation: ToolExpectation, tool: ToolSchema) -> bool:
    metadata = tool.metadata
    transport = expectation.execution_transport
    if transport == "http":
        method, _, path = expectation.key.partition(" ")
        parameter_names = {parameter.name for parameter in tool.parameters}
        return bool(
            str(metadata.get("method") or "").upper() == method
            and metadata.get("path") == path
            and expectation.request_fields.issubset(parameter_names)
            and (
                expectation.request_schema is None
                or isinstance(metadata.get("request_body_schema"), dict)
            )
        )
    execution = metadata.get("execution")
    if not isinstance(execution, dict) or execution.get("transport") != transport:
        return False
    if transport == "mcp":
        return bool(
            execution.get("method") == "tools/call"
            and execution.get("tool_name") == tool.name
            and execution.get("arguments_binding") == "parameters_to_arguments"
            and execution.get("requires_client_binding") is True
        )
    body_template = execution.get("body_template")
    return (
        execution.get("method") == "POST"
        and bool(execution.get("endpoint"))
        and execution.get("content_type") == "application/json"
        and isinstance(body_template, dict)
        and bool(body_template.get("query"))
        and bool(body_template.get("operationName"))
        and execution.get("variable_binding") == "arguments_to_variables"
        and execution.get("result_path")
        == ["data", (tool.metadata.get("graphql") or {}).get("root_field")]
    )


def _contract_consumes_preserved(
    expectation: ToolExpectation,
    rows: list[Any],
) -> bool:
    observed_fields = {
        str(row.get("field_name"))
        for row in rows
        if isinstance(row, dict) and row.get("field_name")
    }
    if not expectation.consume_fields.issubset(observed_fields):
        return False
    if not expectation.required_auth_schemes:
        return True
    observed_auth_schemes = {
        str(scheme)
        for row in rows
        if isinstance(row, dict) and row.get("kind") == "auth"
        for scheme in row.get("security_schemes") or []
    }
    return expectation.required_auth_schemes.issubset(observed_auth_schemes)


def _contract_produces_preserved(
    expectation: ToolExpectation,
    rows: list[Any],
) -> bool:
    observed_fields = {
        str(row.get("field_name"))
        for row in rows
        if isinstance(row, dict) and row.get("field_name")
    }
    if expectation.produce_fields:
        return expectation.produce_fields.issubset(observed_fields)
    return bool(rows)


def _schema_contains(
    expected_signatures: frozenset[tuple[str, str]],
    observed: Any,
) -> bool:
    if not isinstance(observed, dict):
        return False
    observed_signatures = schema_signatures(observed)
    return expected_signatures.issubset(observed_signatures)


def _record(
    row: dict[str, Any],
    *,
    applicable: bool,
    passed: bool,
    sample: str,
) -> None:
    if not applicable:
        return
    row["applicable"] += 1
    if passed:
        row["passed"] += 1
    elif len(row["failure_samples"]) < MAX_FAILURE_SAMPLES:
        row["failure_samples"].append(sample)


def _finalize_metric(row: dict[str, Any]) -> dict[str, Any]:
    applicable = int(row["applicable"])
    passed = int(row["passed"])
    return {
        "applicable": applicable,
        "passed": passed,
        "rate": passed / applicable if applicable else None,
        "not_applicable": applicable == 0,
        "failure_samples": list(row["failure_samples"]),
    }


def _summarize(
    cases: list[dict[str, Any]],
    diagnostic_probes: list[dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["context"]["source_type"]].append(case)
    metrics = {name: _aggregate_metric(cases, name) for name in METRIC_NAMES}
    per_source_type = {
        source_type: {
            "source_count": len(source_cases),
            "tool_count": sum(case["observed"]["tool_count"] for case in source_cases),
            "metrics": {name: _aggregate_metric(source_cases, name) for name in METRIC_NAMES},
        }
        for source_type, source_cases in sorted(grouped.items())
    }
    diagnostic_passed = sum(bool(probe["passed"]) for probe in diagnostic_probes)
    diagnostic_applicable = len(diagnostic_probes)
    return {
        "source_count": len(cases),
        "source_type_count": len(grouped),
        "tool_count": sum(case["observed"]["tool_count"] for case in cases),
        "tool_count_exact_source_rate": (
            fmean(case["metrics"]["tool_count_exact"] for case in cases) if cases else 0.0
        ),
        "metrics": metrics,
        "per_source_type": per_source_type,
        "structured_unsupported_diagnostics": {
            "applicable": diagnostic_applicable,
            "passed": diagnostic_passed,
            "rate": (diagnostic_passed / diagnostic_applicable if diagnostic_applicable else None),
            "probes": diagnostic_probes,
        },
    }


def _aggregate_metric(cases: list[dict[str, Any]], name: str) -> dict[str, Any]:
    rows = [case["metrics"][name] for case in cases]
    applicable = sum(row["applicable"] for row in rows)
    passed = sum(row["passed"] for row in rows)
    source_rates = [row["rate"] for row in rows if row["rate"] is not None]
    failures = [
        f"{case['case_id']}:{sample}"
        for case in cases
        for sample in case["metrics"][name]["failure_samples"]
    ][:MAX_FAILURE_SAMPLES]
    return {
        "applicable": applicable,
        "passed": passed,
        "micro_rate": passed / applicable if applicable else None,
        "macro_rate": fmean(source_rates) if source_rates else None,
        "applicable_source_count": len(source_rates),
        "failure_samples": failures,
    }


def _run_diagnostic_probes() -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    sources = (
        ("openapi_unsupported_capability", "openapi", _probe_openapi(), {}),
        (
            "graphql_unsupported_capability",
            "graphql-introspection",
            _probe_graphql(),
            {"endpoint_url": "https://example.invalid/graphql"},
        ),
        ("mcp_unsupported_capability", "mcp-tools", _probe_mcp(), {}),
    )
    for probe_id, adapter, source, options in sources:
        result = ingest_source(
            source,
            format_hint=adapter,
            required_capabilities={"paper_probe_unsupported"},
            **options,
        )
        issue = next(
            (row for row in result.issues if row.code == "unsupported_capability"),
            None,
        )
        probes.append(
            {
                "probe_id": probe_id,
                "expected_code": "unsupported_capability",
                "observed_code": issue.code if issue else "",
                "passed": bool(
                    issue
                    and issue.severity == "blocker"
                    and issue.evidence.get("capability") == "paper_probe_unsupported"
                    and issue.evidence.get("adapter") == adapter
                ),
            }
        )

    try:
        ingest_source({"asyncapi": "3.0.0", "channels": {}})
    except UnknownIngestAdapterError:
        unknown_passed = True
    else:
        unknown_passed = False
    probes.append(
        {
            "probe_id": "unknown_source",
            "expected_code": "UnknownIngestAdapterError",
            "observed_code": "UnknownIngestAdapterError" if unknown_passed else "",
            "passed": unknown_passed,
        }
    )
    graphql_missing_endpoint = ingest_source(
        _probe_graphql(),
        format_hint="graphql-introspection",
    )
    probes.append(
        _issue_probe(
            "graphql_endpoint_required",
            graphql_missing_endpoint.issues,
            "graphql_endpoint_required",
        )
    )
    empty_mcp = ingest_source([], format_hint="mcp-tools")
    probes.append(_issue_probe("empty_mcp_catalog", empty_mcp.issues, "empty_tool_catalog"))
    return probes


def _issue_probe(
    probe_id: str,
    issues: list[Any],
    expected_code: str,
) -> dict[str, Any]:
    issue = next((row for row in issues if row.code == expected_code), None)
    return {
        "probe_id": probe_id,
        "expected_code": expected_code,
        "observed_code": issue.code if issue else "",
        "passed": bool(issue and issue.severity == "blocker"),
    }


def _probe_openapi() -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Probe", "version": "1"},
        "paths": {
            "/ping": {
                "get": {
                    "operationId": "ping",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }


def _probe_graphql() -> dict[str, Any]:
    return {
        "data": {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": None,
                "subscriptionType": None,
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "fields": [
                            {
                                "name": "ping",
                                "description": "Ping",
                                "args": [],
                                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                                "isDeprecated": False,
                                "deprecationReason": None,
                            }
                        ],
                    },
                    {"kind": "SCALAR", "name": "String"},
                ],
            }
        }
    }


def _probe_mcp() -> list[dict[str, Any]]:
    return [
        {
            "name": "ping",
            "description": "Ping",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]


def _json_round_trip(value: Any) -> bool:
    try:
        return json.loads(_canonical_json(value)) == value
    except (TypeError, ValueError):
        return False


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _read_json_value(path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    value = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(value, (dict, list)):
        raise ValueError(f"Expected a JSON object or list: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--splits", default="train,dev")
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-held-out", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    artifact = run_adapter_conformance(
        args.manifest,
        splits=tuple(args.splits.split(",")),
        output_path=args.out,
        allow_held_out=args.allow_held_out,
    )
    write_artifact(args.out, artifact)
    print(
        json.dumps(
            {
                "artifact": args.out,
                "artifact_id": artifact.artifact_id,
                "source_count": artifact.summary["source_count"],
                "tool_count": artifact.summary["tool_count"],
                "metrics": artifact.summary["metrics"],
                "structured_unsupported_diagnostics": artifact.summary[
                    "structured_unsupported_diagnostics"
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
