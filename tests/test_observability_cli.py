from __future__ import annotations

import json
import sys

from graph_tool_call.__main__ import main
from graph_tool_call.observability import TraceRecorder


def test_trace_cli_replays_json(monkeypatch, capsys, tmp_path):
    recorder = TraceRecorder("retrieve", trace_id="trace-cli")
    with recorder.start_span("retrieval") as span:
        span.decision("getOrder", "ranked", ["retrieval.seed_match"])
    trace_file = recorder.write(tmp_path / "trace.json")
    monkeypatch.setattr(sys, "argv", ["graph-tool-call", "trace", str(trace_file), "--json"])

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["trace_id"] == "trace-cli"
    assert output["reason_coverage"] == 1.0
    assert output["outcomes"]["ranked"] == ["getOrder"]
