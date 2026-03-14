"""Interactive dashboard helpers."""

__all__ = ["build_dashboard_app", "launch_dashboard"]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "build_dashboard_app": ("graph_tool_call.dashboard.app", "build_dashboard_app"),
    "launch_dashboard": ("graph_tool_call.dashboard.app", "launch_dashboard"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'graph_tool_call.dashboard' has no attribute {name!r}")
