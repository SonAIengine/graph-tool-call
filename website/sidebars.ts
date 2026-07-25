import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'index',
    {
      type: 'category',
      label: 'Getting Started',
      link: {
        type: 'generated-index',
        title: 'Getting Started',
        description: 'Install graph-tool-call, run the first retrieval flow, and learn the mental model.',
      },
      items: [
        'getting-started/installation',
        'getting-started/quickstart',
        'getting-started/mental-model',
      ],
    },
    {
      type: 'category',
      label: 'Tutorials',
      link: {
        type: 'generated-index',
        title: 'Tutorials',
        description: 'Follow end-to-end workflows from source ingestion to evidence-backed planning.',
      },
      items: [
        'tutorials/openapi-search-to-plan',
      ],
    },
    {
      type: 'category',
      label: 'Build Tool Catalogs',
      link: {
        type: 'generated-index',
        title: 'Build Tool Catalogs',
        description: 'Turn OpenAPI, MCP, and Python sources into contract-rich tool graph artifacts.',
      },
      items: [
        'build/openapi-ingestion',
        'build/mcp-ingestion',
        'build/python-functions',
        'build/collection-artifacts',
        'build/semantic-build',
        'build/io-contracts',
        'build/readiness-diagnostics',
        'build/auth-readiness',
      ],
    },
    {
      type: 'category',
      label: 'Search And Selection',
      link: {
        type: 'generated-index',
        title: 'Search And Selection',
        description: 'Retrieve the right tool, inspect evidence, expand candidates, and guard LLM target choices.',
      },
      items: [
        'search/tool-graph-search',
        'search/retrieval-signals',
        'search/candidate-expansion',
        'search/evidence-output',
        'search/target-selection',
        'search/korean-search',
        'search/search-tuning',
      ],
    },
    {
      type: 'category',
      label: 'Plan And Execute',
      link: {
        type: 'generated-index',
        title: 'Plan And Execute',
        description: 'Synthesize executable plans, stream runner events, and classify failures.',
      },
      items: [
        'plan/plan-synthesis',
        'plan/user-input-slots',
        'plan/runner-events',
        'plan/failure-taxonomy',
        'plan/response-synthesis',
      ],
    },
    {
      type: 'category',
      label: 'Learning Loop',
      link: {
        type: 'generated-index',
        title: 'Learning Loop',
        description: 'Use scrubbed trace evidence to improve graph search without training the LLM.',
      },
      items: [
        'concepts/trace-learning',
        'learning/scrubbing',
        'learning/suggestions',
        'learning/shadow-promotion',
      ],
    },
    {
      type: 'category',
      label: 'Validation',
      link: {
        type: 'generated-index',
        title: 'Validation',
        description: 'Run repeatable quality gates before making public claims or releasing engine changes.',
      },
      items: [
        'guides/quality-gates',
        'validation/benchmarks',
        'validation/bfcl-style-evaluation',
        'validation/xgen-scale-gates',
        'validation/quality-lab',
        'validation/release-gates',
      ],
    },
    {
      type: 'category',
      label: 'Integrations',
      link: {
        type: 'generated-index',
        title: 'Integrations',
        description: 'Connect graph-tool-call to XGEN, MCP, LangChain, middleware, and direct API adapters.',
      },
      items: [
        'guides/xgen-integration',
        'integrations/xgen-quality-lab',
        'integrations/mcp-server',
        'integrations/mcp-proxy',
        'integrations/langchain',
        'integrations/middleware',
        'integrations/direct-api',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      link: {
        type: 'generated-index',
        title: 'Reference',
        description: 'Stable public APIs, CLI commands, event schemas, artifact schemas, and compatibility notes.',
      },
      items: [
        'reference/api-cheat-sheet',
        'reference/public-api',
        'reference/cli',
        'reference/event-schemas',
        'reference/report-schemas',
        'reference/artifact-schemas',
        'reference/compatibility',
      ],
    },
  ],
};

export default sidebars;
