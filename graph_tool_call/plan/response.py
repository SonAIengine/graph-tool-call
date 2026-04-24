"""Stage 4 — Response Synthesizer.

ExecutionTrace 를 사용자 친화적 자연어 응답으로 변환한다. LLM 1회 호출,
context 는 execution 결과 요약 + 원본 요구사항.

성공 / 실패 두 경우 모두 다룸:
  - 성공: plan.output (final step body) + 요구사항 → 답변
  - 실패: failed_step + error + 부분 결과 → 무엇이 됐고 무엇이 안 됐는지

실행 결과가 대형 JSON 일 수 있으므로 호출자가 미리 projection / 압축한 후
넘기는 것을 권장 (본 모듈은 단순히 ``str(output)`` 사용).
"""

from __future__ import annotations

import json
from typing import Any

from graph_tool_call.ontology.llm_provider import OntologyLLM


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------


_SUCCESS_PROMPT = """\
You turn API execution results into a natural answer for the user.

User asked:
{requirement}

Execution result (from the last step):
{result}

Respond in Korean unless the user's question is clearly in another language.
Keep it concise — 1~3 sentences for simple answers, short bullet list for
multi-item results. Do not invent data not present in the result.
"""


_FAILURE_PROMPT = """\
You explain an API execution failure to the user.

User asked:
{requirement}

Plan aborted at step {failed_step!r}.
Error: {error}

Partial results collected before the failure:
{partial}

Tell the user clearly in Korean (unless the question is another language):
  - what they asked for
  - what was attempted
  - where and why it failed (in plain language — do not dump stack traces)
  - what they can try next, if obvious
Keep it short and helpful — 2~4 sentences.
"""


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def synthesize_success_response(
    *,
    requirement: str,
    result: Any,
    llm: OntologyLLM,
    result_char_limit: int = 2000,
) -> str:
    """Success case — plan completed, convert output to NL answer."""
    prompt = _SUCCESS_PROMPT.format(
        requirement=requirement.strip(),
        result=_render(result, result_char_limit),
    )
    return llm.generate(prompt).strip()


def synthesize_failure_response(
    *,
    requirement: str,
    failed_step: str,
    error: Any,
    partial_results: Any = None,
    llm: OntologyLLM,
    partial_char_limit: int = 1000,
) -> str:
    """Failure case — plan aborted, explain to user."""
    prompt = _FAILURE_PROMPT.format(
        requirement=requirement.strip(),
        failed_step=failed_step,
        error=_render(error, 300),
        partial=_render(partial_results, partial_char_limit) if partial_results else "(none)",
    )
    return llm.generate(prompt).strip()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _render(value: Any, char_limit: int) -> str:
    """Serialize *value* to a short string for prompt use."""
    if value is None:
        return "(none)"
    if isinstance(value, str):
        return value[:char_limit] + ("…" if len(value) > char_limit else "")
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= char_limit:
        return text
    return text[:char_limit] + "…"


__all__ = [
    "synthesize_success_response",
    "synthesize_failure_response",
]
