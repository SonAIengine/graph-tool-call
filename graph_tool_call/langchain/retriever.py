"""LangChain BaseRetriever implementation for graph-based tool retrieval."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

try:
    from langchain_core.callbacks import CallbackManagerForRetrieverRun
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever

    _HAS_LANGCHAIN = True
except ImportError:
    _HAS_LANGCHAIN = False


def _check_langchain() -> None:
    if not _HAS_LANGCHAIN:
        raise ImportError(
            "langchain-core is required for LangChain integration. "
            "Install with: pip install langchain-core"
        )


if _HAS_LANGCHAIN:

    class GraphToolRetriever(BaseRetriever):
        """Retrieves relevant tools from a ToolGraph based on a query.

        Each retrieved tool is returned as a LangChain Document with:
        - page_content: tool description
        - metadata: tool name, parameters, tags
        """

        tool_graph: Any  # ToolGraph (avoid circular import at type level)
        top_k: int = 10
        max_graph_depth: int = 2

        class Config:
            arbitrary_types_allowed = True

        def _get_relevant_documents(
            self,
            query: str,
            *,
            run_manager: CallbackManagerForRetrieverRun | None = None,
        ) -> list[Document]:
            tools = self.tool_graph.retrieve(
                query, top_k=self.top_k, max_graph_depth=self.max_graph_depth
            )
            docs: list[Document] = []
            for tool in tools:
                docs.append(
                    Document(
                        page_content=f"{tool.name}: {tool.description}",
                        metadata={
                            "tool_name": tool.name,
                            "parameters": [p.to_dict() for p in tool.parameters],
                            "tags": tool.tags,
                        },
                    )
                )
            return docs

else:

    class GraphToolRetriever:  # type: ignore[no-redef]
        """Stub when langchain-core is not installed."""

        def __init__(self, **kwargs: Any) -> None:
            _check_langchain()
