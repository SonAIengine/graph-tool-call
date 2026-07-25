import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';

import styles from './index.module.css';

type LinkItem = {
  title: string;
  body: string;
  href: string;
  label: string;
};

type Stage = {
  title: string;
  body: string;
};

type Gate = {
  area: string;
  signal: string;
  link: string;
};

type Copy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  primary: string;
  secondary: string;
  routesLabel: string;
  installLabel: string;
  installCommand: string;
  codeTitle: string;
  code: string;
  startsTitle: string;
  startsBody: string;
  starts: LinkItem[];
  modelTitle: string;
  modelBody: string;
  stages: Stage[];
  gatesTitle: string;
  gatesBody: string;
  gates: Gate[];
  refsTitle: string;
  refs: LinkItem[];
};

const copy: Record<string, Copy> = {
  en: {
    eyebrow: 'Official documentation',
    title: 'Developer manual for searchable tool graphs.',
    subtitle:
      'Build OpenAPI, MCP, and Python tool catalogs into evidence-backed graphs for retrieval, target selection, planning, validation, and trace learning.',
    primary: 'Start with search',
    secondary: 'Build OpenAPI catalogs',
    routesLabel: 'Manual routes',
    installLabel: 'Install',
    installCommand: 'pip install "graph-tool-call[openapi]"',
    codeTitle: 'Minimal retrieval flow',
    code: `from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(openapi_url)
results = graph.retrieve(
    "find refund-ready orders",
    top_k=8,
    include_evidence=True,
)

for item in results:
    print(item.tool.name, item.score_breakdown)`,
    startsTitle: 'Start here',
    startsBody: 'Choose the entry point that matches the job in front of you.',
    starts: [
      {
        title: 'Tool Graph Search',
        body: 'Retrieve compact candidate sets and inspect the evidence behind each ranked tool.',
        href: '/docs/search/tool-graph-search/',
        label: 'Core manual',
      },
      {
        title: 'OpenAPI ingestion',
        body: 'Convert Swagger/OpenAPI sources into tool schemas, IO contracts, and semantic metadata.',
        href: '/docs/build/openapi-ingestion/',
        label: 'Build catalogs',
      },
      {
        title: 'Target selection',
        body: 'Guard LLM target choices with deterministic action, resource, shape, and contract evidence.',
        href: '/docs/search/target-selection/',
        label: 'Selection',
      },
      {
        title: 'Quality Lab',
        body: 'Validate search, plan, and execution behavior with repeatable collection-level cases.',
        href: '/docs/validation/quality-lab/',
        label: 'Validation',
      },
    ],
    modelTitle: 'How the engine is meant to be used',
    modelBody:
      'The library is not another prompt wrapper. It prepares a compact, evidence-backed tool surface before an LLM chooses or executes anything.',
    stages: [
      {
        title: 'Ingest',
        body: 'Normalize OpenAPI, MCP, and Python sources into stable tool schemas.',
      },
      {
        title: 'Analyze',
        body: 'Extract request/response contracts, auth requirements, semantic action, resource, and module signals.',
      },
      {
        title: 'Retrieve',
        body: 'Rank a small candidate set with keyword, semantic metadata, graph expansion, and selector evidence.',
      },
      {
        title: 'Plan and run',
        body: 'Synthesize executable tool paths, stream structured events, and classify auth/request/API failures.',
      },
      {
        title: 'Learn',
        body: 'Promote scrubbed, validated trace evidence so repeated usage improves future ranking.',
      },
    ],
    gatesTitle: 'Validation surface',
    gatesBody:
      'Quality work should land with repeatable checks, not intuition. These are the gates this documentation points users toward.',
    gates: [
      {
        area: 'Search',
        signal: 'Recall@K, MRR, NDCG, candidate count, Korean/English mixed queries',
        link: '/docs/validation/benchmarks/',
      },
      {
        area: 'OpenAPI build',
        signal: 'contract coverage, semantic coverage, readiness score, stable issue codes',
        link: '/docs/guides/openapi-collections/',
      },
      {
        area: 'XGEN scale',
        signal: 'selector hit rate, schema context reduction, uncaught error count',
        link: '/docs/validation/xgen-scale-gates/',
      },
      {
        area: 'Execution',
        signal: 'plan hit, runner stages, auth readiness, structured failure reasons',
        link: '/docs/guides/quality-gates/',
      },
    ],
    refsTitle: 'Reference paths',
    refs: [
      {
        title: 'Public API',
        body: 'Stable imports and engine-level contracts.',
        href: '/docs/reference/public-api/',
        label: 'API',
      },
      {
        title: 'CLI',
        body: 'Search, inspect, and graph commands for local validation.',
        href: '/docs/reference/cli/',
        label: 'CLI',
      },
      {
        title: 'llms.txt',
        body: 'A compact documentation index for LLM-assisted development.',
        href: 'https://sonaiengine.github.io/graph-tool-call/llms.txt',
        label: 'LLM context',
      },
    ],
  },
  ko: {
    eyebrow: '공식 문서',
    title: 'Tool graph 검색 엔진 개발자 매뉴얼.',
    subtitle:
      'OpenAPI, MCP, Python tool catalog를 retrieval, target selection, planning, validation, trace learning이 가능한 evidence-backed graph로 만듭니다.',
    primary: 'Search부터 보기',
    secondary: 'OpenAPI catalog 만들기',
    routesLabel: '매뉴얼 경로',
    installLabel: '설치',
    installCommand: 'pip install "graph-tool-call[openapi]"',
    codeTitle: '최소 retrieval 흐름',
    code: `from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(openapi_url)
results = graph.retrieve(
    "환불 가능한 주문을 찾아줘",
    top_k=8,
    include_evidence=True,
)

for item in results:
    print(item.tool.name, item.score_breakdown)`,
    startsTitle: '어디서 시작할까',
    startsBody: '지금 하려는 작업에 맞는 진입점을 먼저 선택하세요.',
    starts: [
      {
        title: 'Tool Graph Search',
        body: 'compact candidate set을 검색하고 각 ranked tool의 evidence를 확인합니다.',
        href: '/docs/search/tool-graph-search/',
        label: '핵심 매뉴얼',
      },
      {
        title: 'OpenAPI ingestion',
        body: 'Swagger/OpenAPI source를 tool schema, IO contract, semantic metadata로 변환합니다.',
        href: '/docs/build/openapi-ingestion/',
        label: 'Catalog build',
      },
      {
        title: 'Target selection',
        body: 'action, resource, shape, contract evidence로 LLM target 선택을 guard합니다.',
        href: '/docs/search/target-selection/',
        label: 'Selection',
      },
      {
        title: 'Quality Lab',
        body: 'collection 단위 search, plan, execution behavior를 반복 가능한 case로 검증합니다.',
        href: '/docs/validation/quality-lab/',
        label: 'Validation',
      },
    ],
    modelTitle: '엔진 사용 모델',
    modelBody:
      '이 라이브러리는 prompt wrapper가 아닙니다. LLM이 tool을 선택하거나 실행하기 전에 작고 근거가 있는 tool surface를 만들어줍니다.',
    stages: [
      {
        title: 'Ingest',
        body: 'OpenAPI, MCP, Python source를 안정적인 tool schema로 정규화합니다.',
      },
      {
        title: 'Analyze',
        body: 'Request/response contract, auth requirement, semantic action/resource/module signal을 추출합니다.',
      },
      {
        title: 'Retrieve',
        body: 'Keyword, semantic metadata, graph expansion, selector evidence로 작은 후보군을 정렬합니다.',
      },
      {
        title: 'Plan and run',
        body: '실행 가능한 tool path를 합성하고, structured event와 auth/request/API 실패 원인을 남깁니다.',
      },
      {
        title: 'Learn',
        body: 'Scrub된 검증 trace evidence를 승격해 반복 사용 시 ranking 품질을 개선합니다.',
      },
    ],
    gatesTitle: '검증 표면',
    gatesBody:
      '품질 개선은 감이 아니라 재현 가능한 체크로 확인해야 합니다. 이 문서는 아래 gate로 이어지게 설계했습니다.',
    gates: [
      {
        area: 'Search',
        signal: 'Recall@K, MRR, NDCG, candidate count, 한영 혼합 query',
        link: '/docs/validation/benchmarks/',
      },
      {
        area: 'OpenAPI build',
        signal: 'contract coverage, semantic coverage, readiness score, stable issue code',
        link: '/docs/guides/openapi-collections/',
      },
      {
        area: 'XGEN scale',
        signal: 'selector hit rate, schema context reduction, uncaught error count',
        link: '/docs/validation/xgen-scale-gates/',
      },
      {
        area: 'Execution',
        signal: 'plan hit, runner stage, auth readiness, structured failure reason',
        link: '/docs/guides/quality-gates/',
      },
    ],
    refsTitle: 'Reference 경로',
    refs: [
      {
        title: 'Public API',
        body: '안정 public import와 engine-level contract를 확인합니다.',
        href: '/docs/reference/public-api/',
        label: 'API',
      },
      {
        title: 'CLI',
        body: '로컬 검색, inspect, graph command를 확인합니다.',
        href: '/docs/reference/cli/',
        label: 'CLI',
      },
      {
        title: 'llms.txt',
        body: 'LLM-assisted development를 위한 compact documentation index입니다.',
        href: 'https://sonaiengine.github.io/graph-tool-call/ko/llms.txt',
        label: 'LLM context',
      },
    ],
  },
};

function Home(): ReactNode {
  const {i18n} = useDocusaurusContext();
  const text = copy[i18n.currentLocale] ?? copy.en;

  return (
    <Layout title="Official documentation" description="Graph-structured tool retrieval for LLM agents">
      <main className={styles.page}>
        <section className={styles.hero}>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>{text.eyebrow}</p>
            <h1>{text.title}</h1>
            <p className={styles.subtitle}>{text.subtitle}</p>
            <div className={styles.actions}>
              <Link className="button button--primary button--lg" to="/docs/search/tool-graph-search/">
                {text.primary}
              </Link>
              <Link className="button button--secondary button--lg" to="/docs/build/openapi-ingestion/">
                {text.secondary}
              </Link>
            </div>
            <nav className={styles.routeRail} aria-label={text.routesLabel}>
              {text.starts.map((item) => (
                <Link key={item.href} to={item.href}>
                  <span>{item.label}</span>
                  <strong>{item.title}</strong>
                </Link>
              ))}
            </nav>
          </div>
          <aside className={styles.quickPanel} aria-label={text.installLabel}>
            <div className={styles.panelHeader}>
              <span>{text.installLabel}</span>
              <code>Python 3.10+</code>
            </div>
            <pre className={styles.command}>{text.installCommand}</pre>
            <div className={styles.panelHeader}>
              <span>{text.codeTitle}</span>
              <code>OpenAPI</code>
            </div>
            <pre>{text.code}</pre>
          </aside>
        </section>

        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2>{text.startsTitle}</h2>
            <p>{text.startsBody}</p>
          </div>
          <div className={styles.startGrid}>
            {text.starts.map((item) => (
              <Link className={styles.startCard} key={item.href} to={item.href}>
                <span>{item.label}</span>
                <strong>{item.title}</strong>
                <p>{item.body}</p>
              </Link>
            ))}
          </div>
        </section>

        <section className={styles.modelSection}>
          <div className={styles.sectionHeader}>
            <h2>{text.modelTitle}</h2>
            <p>{text.modelBody}</p>
          </div>
          <div className={styles.pipeline} aria-label={text.modelTitle}>
            {text.stages.map((stage, index) => (
              <article className={styles.stage} key={stage.title}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <h3>{stage.title}</h3>
                <p>{stage.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2>{text.gatesTitle}</h2>
            <p>{text.gatesBody}</p>
          </div>
          <div className={styles.gateTable}>
            {text.gates.map((gate) => (
              <Link className={styles.gateRow} key={gate.area} to={gate.link}>
                <strong>{gate.area}</strong>
                <span>{gate.signal}</span>
              </Link>
            ))}
          </div>
        </section>

        <section className={styles.refs}>
          <h2>{text.refsTitle}</h2>
          <div className={styles.refLinks}>
            {text.refs.map((item) => (
              <Link className={styles.refLink} key={item.href} to={item.href}>
                <span>{item.label}</span>
                <strong>{item.title}</strong>
                <p>{item.body}</p>
              </Link>
            ))}
          </div>
        </section>
      </main>
    </Layout>
  );
}

export default Home;
