"""Optional ai-api-lint integration for spec quality improvement before ingest."""

from __future__ import annotations

import copy
from typing import Any


def _require_lint() -> None:
    """Check that ai-api-lint is available."""
    try:
        import ai_api_lint  # noqa: F401
    except ImportError:
        raise ImportError(
            "ai-api-lint is required for spec linting. "
            "Install with: pip install graph-tool-call[lint]"
        )


def lint_and_fix_spec(
    spec: dict[str, Any],
    *,
    max_level: int = 2,
) -> tuple[dict[str, Any], Any]:
    """Lint an OpenAPI spec and auto-fix issues using ai-api-lint.

    Parameters
    ----------
    spec:
        Raw OpenAPI spec dict.
    max_level:
        Maximum fixer level (1=safe only, 2=safe+inferred). Default 2.

    Returns
    -------
    tuple[dict, FixResult]
        The fixed spec (deep copy) and the FixResult with applied/skipped records.
    """
    _require_lint()

    from ai_api_lint.fixer import FixEngine, create_default_fixers
    from ai_api_lint.rules import create_default_engine

    fixed_spec = copy.deepcopy(spec)

    # Lint
    rule_engine = create_default_engine()
    report = rule_engine.lint(fixed_spec)

    # Fix
    fixers = create_default_fixers()
    fix_engine = FixEngine(fixers, max_level=max_level)
    fix_result = fix_engine.fix(fixed_spec, report.findings)

    return fixed_spec, fix_result
