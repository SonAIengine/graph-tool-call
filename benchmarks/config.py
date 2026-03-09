"""Benchmark configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark run."""

    # Dataset selection
    datasets: list[str] = field(default_factory=lambda: ["petstore", "github", "mixed_mcp"])

    # Retrieval settings
    top_k: int = 5

    # LLM settings (None = retrieval-only mode)
    model: str | None = None
    ollama_url: str = "http://localhost:11434/api/chat"
    num_ctx: int = 8192
    timeout: int = 120

    # Output
    output_dir: str = "benchmarks/results"
    save_json: bool = True
    verbose: bool = False


# Dataset registry: name → (ground_truth_path, source_configs)
DATASET_REGISTRY: dict[str, dict] = {
    "petstore": {
        "ground_truth": "benchmarks/ground_truth/petstore.json",
        "sources": [
            {"path": "benchmarks/specs/petstore3.json", "type": "openapi"},
        ],
    },
    "github": {
        "ground_truth": "benchmarks/ground_truth/github.json",
        "sources": [
            {"path": "benchmarks/specs/github_subset.json", "type": "openapi"},
        ],
    },
    "mixed_mcp": {
        "ground_truth": "benchmarks/ground_truth/mixed_mcp.json",
        "sources": [
            {"path": "benchmarks/mcp_tools/filesystem.json", "type": "mcp"},
            {"path": "benchmarks/mcp_tools/github.json", "type": "mcp"},
        ],
    },
    "k8s": {
        "ground_truth": "benchmarks/ground_truth/k8s.json",
        "sources": [
            {"path": "benchmarks/specs/k8s_core_v1.json", "type": "openapi"},
        ],
    },
    # Existing datasets (backward compat)
    "petstore_legacy": {
        "ground_truth": None,
        "sources": [],
        "legacy": True,
    },
    "synthetic": {
        "ground_truth": None,
        "sources": [],
        "legacy": True,
    },
}


@dataclass
class PipelineConfig:
    """Configuration for a single benchmark pipeline."""

    name: str
    use_retrieval: bool = False
    top_k: int = 5
    embedding: str | None = None
    reranker: str | None = None
    weights: dict[str, float] | None = None
    organize: str | None = None  # "auto", "ollama/model", or None (skip)


PIPELINE_PRESETS: dict[str, PipelineConfig] = {
    "baseline": PipelineConfig(name="baseline", use_retrieval=False),
    "retrieve-k3": PipelineConfig(name="retrieve-k3", use_retrieval=True, top_k=3),
    "retrieve-k5": PipelineConfig(name="retrieve-k5", use_retrieval=True, top_k=5),
    "retrieve-k10": PipelineConfig(name="retrieve-k10", use_retrieval=True, top_k=10),
    "retrieve-k5-auto": PipelineConfig(
        name="retrieve-k5-auto", use_retrieval=True, top_k=5, organize="auto"
    ),
    "retrieve-k5-llm": PipelineConfig(
        name="retrieve-k5-llm", use_retrieval=True, top_k=5, organize="llm"
    ),
    # OpenAI-powered presets
    "retrieve-k5-emb": PipelineConfig(
        name="retrieve-k5-emb",
        use_retrieval=True,
        top_k=5,
        embedding="openai/text-embedding-3-small",
    ),
    "retrieve-k5-ont": PipelineConfig(
        name="retrieve-k5-ont",
        use_retrieval=True,
        top_k=5,
        organize="openai/gpt-4o-mini",
    ),
    "retrieve-k5-full": PipelineConfig(
        name="retrieve-k5-full",
        use_retrieval=True,
        top_k=5,
        embedding="openai/text-embedding-3-small",
        organize="openai/gpt-4o-mini",
    ),
}

DEFAULT_PIPELINES = ["baseline", "retrieve-k5"]
