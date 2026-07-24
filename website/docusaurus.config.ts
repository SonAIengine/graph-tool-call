import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'graph-tool-call',
  tagline: 'Graph-structured tool retrieval for LLM agents',
  favicon: 'img/social_preview.png',

  future: {
    v4: true,
  },

  url: 'https://sonaiengine.github.io',
  baseUrl: '/graph-tool-call/',
  organizationName: 'SonAIengine',
  projectName: 'graph-tool-call',

  onBrokenLinks: 'throw',
  trailingSlash: true,
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en', 'ko'],
    localeConfigs: {
      en: {label: 'English'},
      ko: {label: '한국어'},
    },
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/SonAIengine/graph-tool-call/tree/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/social_preview.png',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'graph-tool-call',
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          to: '/docs/validation/benchmarks/',
          label: 'Benchmarks',
          position: 'left',
        },
        {
          type: 'localeDropdown',
          position: 'right',
        },
        {
          href: 'https://github.com/SonAIengine/graph-tool-call',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {label: 'Quickstart', to: '/docs/getting-started/quickstart/'},
            {label: 'OpenAPI Collections', to: '/docs/guides/openapi-collections/'},
            {label: 'Public API', to: '/docs/reference/public-api/'},
          ],
        },
        {
          title: 'Validation',
          items: [
            {label: 'Benchmarks', to: '/docs/validation/benchmarks/'},
            {label: 'XGEN Scale Gates', to: '/docs/validation/xgen-scale-gates/'},
          ],
        },
        {
          title: 'Project',
          items: [
            {label: 'GitHub', href: 'https://github.com/SonAIengine/graph-tool-call'},
            {label: 'PyPI', href: 'https://pypi.org/project/graph-tool-call/'},
            {label: 'llms.txt', href: 'https://sonaiengine.github.io/graph-tool-call/llms.txt'},
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} SonAIengine. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
