import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';

import styles from './index.module.css';

type Copy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  primary: string;
  openapi: string;
  validation: string;
  metrics: Array<{value: string; label: string}>;
  problemsTitle: string;
  problems: Array<{title: string; body: string}>;
  flowTitle: string;
  flow: Array<{title: string; body: string}>;
};

const copy: Record<string, Copy> = {
  en: {
    eyebrow: 'Tool retrieval engine for LLM agents',
    title: 'Search the right tools, not the whole catalog.',
    subtitle:
      'Build an evidence-rich tool graph from OpenAPI, MCP, and Python sources. Give agents ranked candidates, contracts, and trace-backed diagnostics instead of thousands of raw schemas.',
    primary: 'Get started',
    openapi: 'OpenAPI collections',
    validation: 'Validation',
    metrics: [
      {value: '1,000+', label: 'API operations reduced before the LLM sees tools'},
      {value: '0 deps', label: 'dependency-light core retrieval engine'},
      {value: 'Trace-aware', label: 'successful and failed runs become scrubbed evidence'},
    ],
    problemsTitle: 'Built for large tool catalogs',
    problems: [
      {
        title: 'Context pressure',
        body: 'Large catalogs overflow prompts. graph-tool-call narrows tools before model selection.',
      },
      {
        title: 'Workflow blindness',
        body: 'The graph keeps prerequisites, producers, consumers, and trace paths visible.',
      },
      {
        title: 'Weak API metadata',
        body: 'Semantic build derives action, resource, module, result shape, and contracts.',
      },
      {
        title: 'Unclear failures',
        body: 'Readiness and runner metadata split search, plan, auth, request, and API failures.',
      },
    ],
    flowTitle: 'Engine flow',
    flow: [
      {title: 'Ingest', body: 'Normalize OpenAPI, MCP, and Python sources into tool schemas.'},
      {title: 'Build', body: 'Derive semantic metadata, contracts, and graph evidence.'},
      {title: 'Retrieve', body: 'Rank candidates with BM25, graph expansion, and selector guards.'},
      {title: 'Improve', body: 'Promote validated trace evidence into future ranking signals.'},
    ],
  },
  ko: {
    eyebrow: 'LLM 에이전트를 위한 Tool Retrieval Engine',
    title: '필요한 tool만 먼저 찾습니다.',
    subtitle:
      'OpenAPI, MCP, Python source에서 evidence-rich tool graph를 만들고, agent에는 수천 개 raw schema 대신 ranked candidate, contract, trace 기반 diagnostics를 전달합니다.',
    primary: '시작하기',
    openapi: 'OpenAPI 컬렉션',
    validation: '검증',
    metrics: [
      {value: '1,000+', label: 'API operation을 LLM 호출 전에 작은 후보로 축소'},
      {value: '0 deps', label: '가벼운 core retrieval engine'},
      {value: 'Trace-aware', label: '성공/실패 실행 이력을 scrub된 evidence로 축적'},
    ],
    problemsTitle: '대형 tool catalog를 위한 엔진',
    problems: [
      {
        title: 'Context pressure',
        body: '대형 catalog는 prompt를 압도합니다. graph-tool-call은 모델 선택 전에 tool을 좁힙니다.',
      },
      {
        title: 'Workflow blindness',
        body: 'Graph는 prerequisite, producer, consumer, trace path를 보존합니다.',
      },
      {
        title: '약한 API metadata',
        body: 'Semantic build가 action, resource, module, result shape, contract를 파생합니다.',
      },
      {
        title: '불명확한 실패',
        body: 'Readiness와 runner metadata가 search, plan, auth, request, API 실패를 분리합니다.',
      },
    ],
    flowTitle: 'Engine flow',
    flow: [
      {title: 'Ingest', body: 'OpenAPI, MCP, Python source를 tool schema로 정규화합니다.'},
      {title: 'Build', body: 'Semantic metadata, contract, graph evidence를 파생합니다.'},
      {title: 'Retrieve', body: 'BM25, graph expansion, selector guard로 후보를 정렬합니다.'},
      {title: 'Improve', body: '검증된 trace evidence를 다음 ranking signal로 승격합니다.'},
    ],
  },
};

function Home(): ReactNode {
  const {i18n} = useDocusaurusContext();
  const text = copy[i18n.currentLocale] ?? copy.en;

  return (
    <Layout title="Tool retrieval for LLM agents" description="Graph-structured tool retrieval for LLM agents">
      <main>
        <section className={styles.hero}>
          <div className={styles.heroText}>
            <p className={styles.eyebrow}>{text.eyebrow}</p>
            <h1>{text.title}</h1>
            <p className={styles.subtitle}>{text.subtitle}</p>
            <div className={styles.actions}>
              <Link className="button button--primary button--lg" to="/docs/getting-started/quickstart/">
                {text.primary}
              </Link>
              <Link className="button button--secondary button--lg" to="/docs/guides/openapi-collections/">
                {text.openapi}
              </Link>
              <Link className="button button--secondary button--lg" to="/docs/validation/benchmarks/">
                {text.validation}
              </Link>
            </div>
          </div>
          <div className={styles.panel}>
            <div className={styles.panelHeader}>graph-tool-call</div>
            <pre>{`from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(openapi_url)
tools = graph.retrieve(
    "find orders that need refund",
    top_k=8,
)

# ranked tools + graph evidence + IO contracts`}</pre>
          </div>
        </section>

        <section className={styles.metrics}>
          {text.metrics.map((metric) => (
            <article className={styles.metric} key={metric.value}>
              <strong>{metric.value}</strong>
              <span>{metric.label}</span>
            </article>
          ))}
        </section>

        <section className={styles.section}>
          <h2>{text.problemsTitle}</h2>
          <div className={styles.cards}>
            {text.problems.map((problem) => (
              <article className={styles.card} key={problem.title}>
                <h3>{problem.title}</h3>
                <p>{problem.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className={styles.section}>
          <h2>{text.flowTitle}</h2>
          <div className={styles.flow}>
            {text.flow.map((step, index) => (
              <article className={styles.flowStep} key={step.title}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </Layout>
  );
}

export default Home;
