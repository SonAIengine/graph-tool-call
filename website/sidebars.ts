import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'index',
    {
      type: 'category',
      label: 'Getting Started',
      items: ['getting-started/quickstart', 'getting-started/installation'],
    },
    {
      type: 'category',
      label: 'Core Concepts',
      items: [
        'concepts/tool-graph',
        'concepts/openapi-semantic-build',
        'concepts/trace-learning',
      ],
    },
    {
      type: 'category',
      label: 'Guides',
      items: [
        'guides/openapi-collections',
        'guides/xgen-integration',
        'guides/quality-gates',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      items: ['reference/public-api', 'reference/cli'],
    },
    {
      type: 'category',
      label: 'Validation',
      items: ['validation/benchmarks', 'validation/xgen-scale-gates'],
    },
  ],
};

export default sidebars;
