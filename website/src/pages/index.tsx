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

type ManualGroup = {
  title: string;
  body: string;
  links: {
    label: string;
    href: string;
    note: string;
  }[];
};

type Stage = {
  title: string;
  artifact: string;
  body: string;
  href: string;
};

type Gate = {
  area: string;
  signal: string;
  proof: string;
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
  outputTitle: string;
  output: string;
  startsTitle: string;
  startsBody: string;
  starts: LinkItem[];
  manualTitle: string;
  manualBody: string;
  manualGroups: ManualGroup[];
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
    title: 'graph-tool-call documentation.',
    subtitle:
      'A technical manual for turning OpenAPI, MCP, and Python tools into contracts, retrieval evidence, target selection, execution plans, quality gates, and trace learning loops.',
    primary: 'Start quickstart',
    secondary: 'Search manual',
    routesLabel: 'Manual routes',
    installLabel: 'Install',
    installCommand: 'pip install "graph-tool-call[openapi]"',
    codeTitle: 'First retrieval call',
    code: `from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(openapi_url)
results = graph.retrieve_with_scores(
    "find refund-ready orders",
    top_k=3,
)

print(results[0].to_dict(include_score=True, max_desc=80))`,
    outputTitle: 'Output shape',
    output: `{
  "name": "getRefundableOrders",
  "description": "Search refund-ready orders...",
  "score": 0.0312,
  "confidence": "high"
}`,
    startsTitle: 'Manual paths',
    startsBody:
      'Start from the workflow you are implementing. Each page is written as a working manual with examples, output shapes, diagnostics, failure modes, and validation commands.',
    starts: [
      {
        title: 'Build catalog',
        body: 'Convert Swagger/OpenAPI sources into tool schemas, contracts, semantic metadata, and collection artifacts.',
        href: '/docs/build/openapi-ingestion/',
        label: 'Build',
      },
      {
        title: 'Search tools',
        body: 'Retrieve compact candidate sets and inspect the score signals behind each ranked tool.',
        href: '/docs/search/tool-graph-search/',
        label: 'Search',
      },
      {
        title: 'Select target',
        body: 'Guard LLM target choices with deterministic action, resource, shape, and contract evidence.',
        href: '/docs/search/target-selection/',
        label: 'Select',
      },
      {
        title: 'Plan execution',
        body: 'Synthesize executable tool paths, user input slots, runner events, and failure reason codes.',
        href: '/docs/plan/plan-synthesis/',
        label: 'Plan',
      },
      {
        title: 'Validate quality',
        body: 'Run repeatable search, plan, execute, benchmark, and release gates before making claims.',
        href: '/docs/validation/quality-lab/',
        label: 'Validation',
      },
      {
        title: 'Learn from traces',
        body: 'Promote scrubbed success evidence into low-weight ranking and planning suggestions.',
        href: '/docs/concepts/trace-learning/',
        label: 'Learn',
      },
    ],
    manualTitle: 'Manual index',
    manualBody:
      'The documentation is organized around the same lifecycle the engine runs in production: build a catalog, search with evidence, select a target, synthesize a plan, validate the result, and learn from traces.',
    manualGroups: [
      {
        title: 'Build tool catalogs',
        body: 'Create stable tool graph artifacts from OpenAPI, MCP, and Python sources.',
        links: [
          {label: 'OpenAPI ingestion', href: '/docs/build/openapi-ingestion/', note: 'Swagger UI, JSON, YAML, private host policy'},
          {label: 'IO contracts', href: '/docs/build/io-contracts/', note: 'Consumes, produces, links, schema coverage'},
          {label: 'Readiness diagnostics', href: '/docs/build/readiness-diagnostics/', note: 'Score, issue codes, repair actions'},
        ],
      },
      {
        title: 'Search and selection',
        body: 'Retrieve compact candidate sets and explain why the final target was selected.',
        links: [
          {label: 'Tool graph search', href: '/docs/search/tool-graph-search/', note: 'Query flow and retrieval API'},
          {label: 'Retrieval signals', href: '/docs/search/retrieval-signals/', note: 'Action, resource, shape, contract, learning'},
          {label: 'Target selection', href: '/docs/search/target-selection/', note: 'LLM guardrails and override policy'},
        ],
      },
      {
        title: 'Plan and execute',
        body: 'Turn a selected target into executable steps with structured runtime events.',
        links: [
          {label: 'Plan synthesis', href: '/docs/plan/plan-synthesis/', note: 'Producer paths, bindings, user slots'},
          {label: 'Runner events', href: '/docs/plan/runner-events/', note: 'Streaming events, metadata, failures'},
          {label: 'Failure taxonomy', href: '/docs/plan/failure-taxonomy/', note: 'Stable reason codes for adapters'},
        ],
      },
      {
        title: 'Validate and learn',
        body: 'Use repeatable gates and scrubbed traces instead of anecdotal quality claims.',
        links: [
          {label: 'Quality Lab', href: '/docs/validation/quality-lab/', note: 'Search, plan, execute cases'},
          {label: 'Benchmarks', href: '/docs/validation/benchmarks/', note: 'Recall, MRR, NDCG, claim policy'},
          {label: 'Trace learning', href: '/docs/concepts/trace-learning/', note: 'Observe, shadow, promote'},
        ],
      },
    ],
    modelTitle: 'Execution model',
    modelBody:
      'The library is not another prompt wrapper. Each stage produces an artifact that can be inspected, stored, validated, and passed to an adapter.',
    stages: [
      {
        title: 'Ingest',
        artifact: 'ToolSchema',
        body: 'Normalize OpenAPI, MCP, and Python sources into stable tool schemas.',
        href: '/docs/build/openapi-ingestion/',
      },
      {
        title: 'Contract',
        artifact: 'api_contract',
        body: 'Extract request/response fields, auth requirements, enums, and context fields.',
        href: '/docs/build/io-contracts/',
      },
      {
        title: 'Retrieve',
        artifact: 'RetrievalResult',
        body: 'Rank a small candidate set with keyword, graph, embedding, and annotation signals.',
        href: '/docs/search/retrieval-signals/',
      },
      {
        title: 'Select',
        artifact: 'target_selector',
        body: 'Compare LLM target output with deterministic action, resource, shape, and contract evidence.',
        href: '/docs/search/target-selection/',
      },
      {
        title: 'Plan/run',
        artifact: 'runner events',
        body: 'Synthesize executable tool paths, stream structured events, and classify auth/request/API failures.',
        href: '/docs/plan/runner-events/',
      },
      {
        title: 'Learn',
        artifact: 'suggestions',
        body: 'Promote scrubbed, validated trace evidence so repeated usage improves future ranking.',
        href: '/docs/learning/suggestions/',
      },
    ],
    gatesTitle: 'Quality gates',
    gatesBody:
      'Quality work should land with repeatable checks, not intuition. Public claims should link to commands, fixtures, or explicit limitations.',
    gates: [
      {
        area: 'Search',
        signal: 'Recall@K, MRR, NDCG, candidate count, Korean/English mixed queries',
        proof: 'Benchmark fixtures and `benchmarks/run_benchmark.py` output',
        link: '/docs/validation/benchmarks/',
      },
      {
        area: 'OpenAPI build',
        signal: 'contract coverage, semantic coverage, readiness score, stable issue codes',
        proof: 'OpenAPI readiness report and collection artifact metadata',
        link: '/docs/guides/openapi-collections/',
      },
      {
        area: 'Plan and execute',
        signal: 'plan hit, runner stages, auth readiness, structured failure reasons',
        proof: 'Quality Lab cases with search, plan, and execute modes',
        link: '/docs/guides/quality-gates/',
      },
      {
        area: 'Trace learning',
        signal: 'scrubbed payloads, shadow improvement, promotion/rejection status',
        proof: 'Learning suggestions and shadow/promotion records',
        link: '/docs/learning/shadow-promotion/',
      },
      {
        area: 'Release',
        signal: 'docs build, API imports, package version, benchmark claim policy',
        proof: 'Release gates before publishing a public claim',
        link: '/docs/validation/release-gates/',
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
        body: 'Local search, inspect, graph, and diagnostics commands.',
        href: '/docs/reference/cli/',
        label: 'CLI',
      },
      {
        title: 'Schemas',
        body: 'Artifact, event, and report shapes used by integrations.',
        href: '/docs/reference/artifact-schemas/',
        label: 'Schemas',
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
    title: 'graph-tool-call 공식 문서.',
    subtitle:
      'OpenAPI, MCP, Python tool을 contract, retrieval evidence, target selection, execution plan, quality gate, trace learning loop로 연결하는 기술 매뉴얼입니다.',
    primary: 'Quickstart 시작',
    secondary: 'Search 매뉴얼',
    routesLabel: '매뉴얼 경로',
    installLabel: '설치',
    installCommand: 'pip install "graph-tool-call[openapi]"',
    codeTitle: '첫 retrieval 호출',
    code: `from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(openapi_url)
results = graph.retrieve_with_scores(
    "환불 가능한 주문을 찾아줘",
    top_k=3,
)

print(results[0].to_dict(include_score=True, max_desc=80))`,
    outputTitle: '출력 형태',
    output: `{
  "name": "getRefundableOrders",
  "description": "Search refund-ready orders...",
  "score": 0.0312,
  "confidence": "high"
}`,
    startsTitle: '매뉴얼 경로',
    startsBody:
      '지금 구현하려는 workflow에서 출발하세요. 각 페이지는 예제, 출력 형태, 진단 정보, 실패 모드, 검증 명령까지 같은 문법으로 읽을 수 있게 구성합니다.',
    starts: [
      {
        title: 'Catalog build',
        body: 'Swagger/OpenAPI source를 tool schema, contract, semantic metadata, collection artifact로 변환합니다.',
        href: '/docs/build/openapi-ingestion/',
        label: 'Build',
      },
      {
        title: 'Tool search',
        body: '작은 후보군을 검색하고 ranked tool의 score signal을 확인합니다.',
        href: '/docs/search/tool-graph-search/',
        label: 'Search',
      },
      {
        title: 'Target select',
        body: 'action, resource, shape, contract evidence로 LLM target 선택을 guard합니다.',
        href: '/docs/search/target-selection/',
        label: 'Select',
      },
      {
        title: 'Plan execution',
        body: '실행 가능한 tool path, 사용자 입력 슬롯, runner event, 실패 reason code를 만듭니다.',
        href: '/docs/plan/plan-synthesis/',
        label: 'Plan',
      },
      {
        title: 'Quality validate',
        body: 'search, plan, execute, benchmark, release gate를 반복 가능한 방식으로 검증합니다.',
        href: '/docs/validation/quality-lab/',
        label: 'Validation',
      },
      {
        title: 'Trace learning',
        body: 'scrub된 성공 evidence를 낮은 가중치의 ranking/plan suggestion으로 승격합니다.',
        href: '/docs/concepts/trace-learning/',
        label: 'Learn',
      },
    ],
    manualTitle: '매뉴얼 인덱스',
    manualBody:
      '문서는 production에서 엔진이 실제로 도는 lifecycle 기준으로 구성되어 있습니다. catalog를 build하고, evidence로 search하고, target을 선택하고, plan을 합성하고, 검증하고, trace에서 학습합니다.',
    manualGroups: [
      {
        title: 'Tool catalog build',
        body: 'OpenAPI, MCP, Python source에서 안정적인 tool graph artifact를 만듭니다.',
        links: [
          {label: 'OpenAPI ingestion', href: '/docs/build/openapi-ingestion/', note: 'Swagger UI, JSON, YAML, private host policy'},
          {label: 'IO contracts', href: '/docs/build/io-contracts/', note: 'Consumes, produces, links, schema coverage'},
          {label: 'Readiness diagnostics', href: '/docs/build/readiness-diagnostics/', note: 'Score, issue code, repair action'},
        ],
      },
      {
        title: 'Search and selection',
        body: '작은 candidate set을 검색하고 최종 target 선택 근거를 설명합니다.',
        links: [
          {label: 'Tool graph search', href: '/docs/search/tool-graph-search/', note: 'Query flow and retrieval API'},
          {label: 'Retrieval signals', href: '/docs/search/retrieval-signals/', note: 'Action, resource, shape, contract, learning'},
          {label: 'Target selection', href: '/docs/search/target-selection/', note: 'LLM guardrail and override policy'},
        ],
      },
      {
        title: 'Plan and execute',
        body: '선택된 target을 실행 가능한 step과 structured runtime event로 바꿉니다.',
        links: [
          {label: 'Plan synthesis', href: '/docs/plan/plan-synthesis/', note: 'Producer path, binding, user slot'},
          {label: 'Runner events', href: '/docs/plan/runner-events/', note: 'Streaming event, metadata, failure'},
          {label: 'Failure taxonomy', href: '/docs/plan/failure-taxonomy/', note: 'Adapter용 stable reason code'},
        ],
      },
      {
        title: 'Validate and learn',
        body: '감이 아니라 반복 가능한 gate와 scrub된 trace로 품질을 증명합니다.',
        links: [
          {label: 'Quality Lab', href: '/docs/validation/quality-lab/', note: 'Search, plan, execute case'},
          {label: 'Benchmarks', href: '/docs/validation/benchmarks/', note: 'Recall, MRR, NDCG, claim policy'},
          {label: 'Trace learning', href: '/docs/concepts/trace-learning/', note: 'Observe, shadow, promote'},
        ],
      },
    ],
    modelTitle: '실행 모델',
    modelBody:
      '이 라이브러리는 prompt wrapper가 아닙니다. 각 단계는 inspect, 저장, 검증, adapter 전달이 가능한 artifact를 만듭니다.',
    stages: [
      {
        title: 'Ingest',
        artifact: 'ToolSchema',
        body: 'OpenAPI, MCP, Python source를 안정적인 tool schema로 정규화합니다.',
        href: '/docs/build/openapi-ingestion/',
      },
      {
        title: 'Contract',
        artifact: 'api_contract',
        body: 'request/response field, auth requirement, enum, context field를 추출합니다.',
        href: '/docs/build/io-contracts/',
      },
      {
        title: 'Retrieve',
        artifact: 'RetrievalResult',
        body: 'keyword, graph, embedding, annotation signal로 작은 후보군을 정렬합니다.',
        href: '/docs/search/retrieval-signals/',
      },
      {
        title: 'Select',
        artifact: 'target_selector',
        body: 'LLM target과 deterministic action/resource/shape/contract evidence를 비교합니다.',
        href: '/docs/search/target-selection/',
      },
      {
        title: 'Plan/run',
        artifact: 'runner events',
        body: '실행 가능한 tool path를 합성하고, structured event와 auth/request/API 실패 원인을 남깁니다.',
        href: '/docs/plan/runner-events/',
      },
      {
        title: 'Learn',
        artifact: 'suggestions',
        body: 'Scrub된 검증 trace evidence를 승격해 반복 사용 시 ranking 품질을 개선합니다.',
        href: '/docs/learning/suggestions/',
      },
    ],
    gatesTitle: '품질 게이트',
    gatesBody:
      '품질 개선은 감이 아니라 재현 가능한 체크로 확인해야 합니다. 공개 claim은 command, fixture, 명시적 한계와 함께 남깁니다.',
    gates: [
      {
        area: 'Search',
        signal: 'Recall@K, MRR, NDCG, candidate count, 한영 혼합 query',
        proof: 'benchmark fixture와 `benchmarks/run_benchmark.py` 결과',
        link: '/docs/validation/benchmarks/',
      },
      {
        area: 'OpenAPI build',
        signal: 'contract coverage, semantic coverage, readiness score, stable issue code',
        proof: 'OpenAPI readiness report와 collection artifact metadata',
        link: '/docs/guides/openapi-collections/',
      },
      {
        area: 'Plan and execute',
        signal: 'plan hit, runner stage, auth readiness, structured failure reason',
        proof: 'search, plan, execute mode의 Quality Lab case',
        link: '/docs/guides/quality-gates/',
      },
      {
        area: 'Trace learning',
        signal: 'scrubbed payload, shadow improvement, promotion/rejection status',
        proof: 'learning suggestion과 shadow/promotion record',
        link: '/docs/learning/shadow-promotion/',
      },
      {
        area: 'Release',
        signal: 'docs build, API import, package version, benchmark claim policy',
        proof: 'public claim 전에 실행하는 release gate',
        link: '/docs/validation/release-gates/',
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
        body: '로컬 search, inspect, graph, diagnostics command를 확인합니다.',
        href: '/docs/reference/cli/',
        label: 'CLI',
      },
      {
        title: 'Schemas',
        body: 'integration에서 사용하는 artifact, event, report shape를 확인합니다.',
        href: '/docs/reference/artifact-schemas/',
        label: 'Schemas',
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
              <Link className="button button--primary button--lg" to="/docs/getting-started/quickstart/">
                {text.primary}
              </Link>
              <Link className="button button--secondary button--lg" to="/docs/search/tool-graph-search/">
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
            <div className={styles.panelHeader}>
              <span>{text.outputTitle}</span>
              <code>JSON</code>
            </div>
            <pre>{text.output}</pre>
          </aside>
        </section>

        <section className={styles.manualIndex}>
          <div className={styles.sectionHeader}>
            <h2>{text.manualTitle}</h2>
            <p>{text.manualBody}</p>
          </div>
          <div className={styles.manualGrid}>
            {text.manualGroups.map((group) => (
              <article className={styles.manualGroup} key={group.title}>
                <h3>{group.title}</h3>
                <p>{group.body}</p>
                <ul>
                  {group.links.map((link) => (
                    <li key={link.href}>
                      <Link to={link.href}>
                        <strong>{link.label}</strong>
                        <span>{link.note}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
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
              <Link className={styles.stage} key={stage.title} to={stage.href}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <code>{stage.artifact}</code>
                <h3>{stage.title}</h3>
                <p>{stage.body}</p>
              </Link>
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
                <em>{gate.proof}</em>
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
