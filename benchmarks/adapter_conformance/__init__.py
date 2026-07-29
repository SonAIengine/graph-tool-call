"""Deterministic adapter-conformance benchmark for the public paper corpus."""

__all__ = ["run_adapter_conformance"]


def __getattr__(name: str):
    if name == "run_adapter_conformance":
        from .run import run_adapter_conformance

        return run_adapter_conformance
    raise AttributeError(name)
