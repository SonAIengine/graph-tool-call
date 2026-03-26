"""Tool result compressor: intelligently compress large tool outputs for LLM context.

Usage::

    from graph_tool_call.compressor import compress_tool_result, CompressConfig

    # Simple — auto-detect type, default 4000 chars
    compressed = compress_tool_result(huge_json)

    # Custom config
    cfg = CompressConfig(max_chars=2000, max_list_items=5)
    compressed = compress_tool_result(data, config=cfg)
"""

from graph_tool_call.compressor.base import CompressConfig
from graph_tool_call.compressor.detector import compress_tool_result

__all__ = ["CompressConfig", "compress_tool_result"]
