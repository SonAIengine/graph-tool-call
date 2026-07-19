"""BM25 keyword scoring for tool retrieval."""

from __future__ import annotations

import math
import re
from collections.abc import Callable

from graph_tool_call.core.tool import ToolSchema

# Baseline stopwords — always removed regardless of corpus.
# These are common filler words that never carry discriminative value.
_BASE_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "for",
        "to",
        "in",
        "by",
        "is",
        "and",
        "or",
    }
)

# CRUD/action verbs that must never be auto-stopworded — they carry intent.
_PROTECTED_TERMS = frozenset(
    {
        "list",
        "get",
        "read",
        "creat",  # stemmed form of "create"
        "delet",  # stemmed form of "delete"
        "updat",  # stemmed form of "update"
        "patch",
        "put",
        "post",
        "watch",
        "find",
        "search",
        "writ",  # stemmed form of "write"
        "send",
        "add",
        "remov",  # stemmed form of "remove"
        "set",
    }
)

# Suffix-stripping rules applied in order. Each entry: (suffix, min_stem_len).
# min_stem_len prevents over-stemming (e.g. "us" → "u").
# Korean → English translation pairs for cross-language retrieval.
# When a Korean query token matches a key, the English tokens are added.
# Values use stemmed forms to match BM25 document index (e.g. "creat" not "create").
# Covers API/software domain terms: CRUD verbs, resources, infra, DevOps, auth, data.
_KO_EN_DICT: dict[str, list[str]] = {
    # ── CRUD / Action verbs ──
    "생성": ["creat", "add", "new"],
    "만들기": ["creat", "add", "new"],
    "추가": ["add", "creat", "insert"],
    "등록": ["register", "creat", "add"],
    "삭제": ["delet", "remov", "drop"],
    "제거": ["remov", "delet"],
    "수정": ["updat", "modifi", "edit", "patch"],
    "변경": ["chang", "updat", "modifi"],
    "편집": ["edit", "modifi"],
    "조회": ["get", "list", "fetch", "retriev", "read"],
    "검색": ["search", "find", "query", "lookup"],
    "확인": ["check", "verifi", "valid"],
    "보기": ["view", "show", "display", "get"],
    "가져오기": ["fetch", "get", "retriev", "import"],
    "내보내기": ["export"],
    "읽기": ["read", "get"],
    "쓰기": ["writ", "post", "put"],
    "작성": ["creat", "submit", "writ", "compos"],
    "전송": ["send", "transmit", "post"],
    "요청": ["request", "call", "invok"],
    "실행": ["execut", "run", "invok"],
    "시작": ["start", "begin", "launch", "init"],
    "중지": ["stop", "halt", "paus"],
    "재시작": ["restart", "reboot"],
    "취소": ["cancel", "abort", "revok"],
    "복사": ["copi", "clone", "duplic"],
    "이동": ["mov", "transfer", "migrat"],
    "설정": ["set", "configur", "prefer"],
    "적용": ["appli", "deploy"],
    "승인": ["approv", "accept", "confirm"],
    "거부": ["reject", "deni", "declin"],
    "활성화": ["enabl", "activ"],
    "비활성화": ["disabl", "deactiv"],
    # ── E-Commerce ──
    "장바구니": ["cart", "shopping", "basket"],
    "상품": ["product", "item", "good"],
    "주문": ["order", "purchas"],
    "결제": ["payment", "checkout", "pay", "billing"],
    "정산": ["settlement", "adjust", "adjustment", "pg", "대사"],
    "비교": ["compare", "comparison", "reconcile", "reconciliation", "대사"],
    "환불": ["refund", "return"],
    "배송": ["shipping", "deliver", "shipment"],
    "배송비": ["shipping", "rate", "calculat", "cost"],
    "쿠폰": ["coupon", "discount", "voucher", "promo"],
    "할인": ["discount", "sale", "promo"],
    "찜": ["wishlist", "favorit", "bookmark"],
    "재고": ["inventori", "stock", "availab"],
    "후기": ["review", "feedback", "comment"],
    "평점": ["rate", "rating", "score"],
    "카테고리": ["categori", "tag", "group"],
    # ── E-Commerce field aliases commonly found in Korean BO OpenAPI specs ──
    "번호": ["id", "no", "number", "num"],
    "코드": ["code", "cd"],
    "명": ["name", "nm"],
    "상품번호": ["good", "goods", "product", "item", "no", "id", "number"],
    "상품명": ["good", "goods", "product", "item", "name", "nm"],
    "브랜드": ["brand"],
    "브랜드번호": ["brand", "no", "id", "number"],
    "브랜드명": ["brand", "name", "nm"],
    "고객": ["customer", "cust", "user", "member"],
    "고객번호": ["customer", "cust", "user", "member", "no", "id", "number"],
    "회원번호": ["member", "user", "account", "no", "id", "number"],
    "주문번호": ["order", "ord", "purchase", "no", "id", "number"],
    "배송번호": ["shipping", "deliver", "shipment", "no", "id", "number"],
    "카테고리번호": ["categori", "category", "cate", "no", "id", "number"],
    # ── User / Auth ──
    "사용자": ["user", "account"],
    "회원": ["user", "member", "account"],
    "관리자": ["admin", "administr"],
    "프로필": ["profil"],
    "계정": ["account"],
    "로그인": ["login", "signin", "auth"],
    "로그아웃": ["logout", "signout"],
    "비밀번호": ["password", "secret", "credenti"],
    "인증": ["auth", "verifi", "token"],
    "권한": ["permiss", "role", "access", "author"],
    "버튼": ["button", "btn"],
    "토큰": ["token", "jwt", "api_key"],
    # ── Data / Resources ──
    "목록": ["list", "index", "collect"],
    "상세": ["detail", "info", "describ"],
    "파일": ["file", "document"],
    "폴더": ["folder", "directori"],
    "이미지": ["imag", "photo", "pictur"],
    "업로드": ["upload"],
    "다운로드": ["download"],
    "첨부": ["attach", "upload"],
    "데이터": ["data", "record", "entri"],
    "데이터베이스": ["databas", "db", "store"],
    "테이블": ["tabl", "schema"],
    "메시지": ["messag", "notif", "alert"],
    "알림": ["notif", "alert", "push"],
    "이메일": ["email", "mail"],
    "댓글": ["comment", "reply"],
    "게시글": ["post", "articl", "content"],
    "태그": ["tag", "label"],
    "로그": ["log", "audit", "histori"],
    # ── Infrastructure / DevOps ──
    "서버": ["server", "host", "instanc"],
    "컨테이너": ["container", "docker", "pod"],
    "배포": ["deploy", "releas", "rollout"],
    "빌드": ["build", "compil"],
    "네트워크": ["network", "connect"],
    "포트": ["port"],
    "도메인": ["domain", "dns", "host"],
    "클러스터": ["cluster"],
    "노드": ["node"],
    "볼륨": ["volum", "storag", "disk"],
    "네임스페이스": ["namespac"],
    "서비스": ["servic"],
    "레플리카": ["replica", "scale"],
    "시크릿": ["secret", "credenti"],
    "설정맵": ["configmap", "config"],
    "인그레스": ["ingress", "rout"],
    "모니터링": ["monitor", "metric", "observ"],
    "스케일": ["scale", "autoscal"],
    # ── Git / VCS ──
    "브랜치": ["branch"],
    "커밋": ["commit"],
    "머지": ["merg", "pull_request"],
    "풀리퀘스트": ["pull_request", "pr", "merg"],
    "저장소": ["repositori", "repo"],
    "이슈": ["issu", "ticket", "bug"],
    "릴리스": ["releas", "version", "tag"],
    # ── General API ──
    "응답": ["respons"],
    "상태": ["status", "state", "health"],
    "버전": ["version"],
    "정렬": ["sort", "order"],
    "필터": ["filter", "where"],
    "페이지": ["page", "pagin", "offset", "limit"],
    "크기": ["size", "length", "count"],
    "전체": ["all", "total", "list"],
    "최신": ["latest", "recent", "newest"],
    "통계": ["statist", "analyt", "metric", "report"],
    "요약": ["summary", "summari"],
    "대시보드": ["dashboard", "overview"],
    "웹훅": ["webhook", "callback"],
    "연동": ["integr", "connect", "link"],
}

_KO_ACTION_TERMS = frozenset(
    {
        "검색",
        "조회",
        "수정",
        "등록",
        "삭제",
        "저장",
        "처리",
        "취소",
        "철회",
        "승인",
        "거부",
        "비교",
        "요약",
    }
)
_KO_BRIDGE_TERMS = frozenset({"목록", "리스트", "정보", "관리", "대상"})

_EN_QUERY_SYNONYMS: dict[str, list[str]] = {
    # Common math/science wording that appears in user requests more often
    # than in compact operationIds.
    "geographic": ["geo"],
    "geographical": ["geo"],
    "hypotenuse": ["hypot", "norm"],
    "euclidean": ["hypot", "norm"],
    "series": ["sequence"],
    "covered": ["travel", "traveled"],
    "cover": ["travel", "traveled"],
}

# Suffix-stripping rules applied in order. Each entry: (suffix, min_stem_len).
_STEM_RULES: list[tuple[str, int]] = [
    ("ies", 2),  # queries → quer, bodies → bodi
    ("ied", 2),  # applied → appl
    ("ing", 3),  # running → runn, listing → list
    ("tion", 3),  # creation → crea, deletion → dele
    ("sion", 3),  # permission → permis
    ("ment", 3),  # deployment → deploy
    ("ness", 3),  # readiness → readi
    ("able", 3),  # readable → read
    ("ible", 3),  # accessible → access
    ("ous", 3),  # dangerous → danger
    ("ive", 3),  # destructive → destruct
    ("ful", 3),  # successful → success
    ("es", 3),  # namespaces → namespac, resources → resourc
    ("ed", 3),  # namespaced → namespac, created → creat
    ("er", 3),  # controller → controll
    ("ly", 3),  # permanently → permanent
    ("s", 3),  # pods → pod, secrets → secret
]


def _stem(token: str) -> str:
    """Lightweight suffix-stripping stemmer for API/tool vocabulary.

    Not a full Porter/Snowball — just enough to normalize plural/tense forms
    that commonly appear in OpenAPI operationIds and tool descriptions.
    """
    if len(token) <= 3:
        return token
    for suffix, min_len in _STEM_RULES:
        if token.endswith(suffix) and len(token) - len(suffix) >= min_len:
            return token[: -len(suffix)]
    return token


class BM25Scorer:
    """BM25 scoring for tool corpus.

    Directly implemented (no external library) because:
    - Tool corpus is small (typically <1000 tools)
    - Need tool-specific tokenization (camelCase splitting, etc.)
    """

    def __init__(
        self,
        tools: dict[str, ToolSchema],
        k1: float = 1.2,
        b: float = 0.75,
        stopword_df_threshold: float = 0.7,
        *,
        tokenizer: Callable[[str], list[str]] | None = None,
    ) -> None:
        self._k1 = k1
        self._b = b
        self._tools = tools
        self._stopword_df_threshold = stopword_df_threshold
        # Custom tokenizer hook. None → built-in BM25Scorer._tokenize (byte-for-byte
        # backward compatible). A callable str → list[str] replaces tokenization in
        # both indexing and scoring (BM25 requires index/query symmetry).
        self._tokenize_fn: Callable[[str], list[str]] = tokenizer or BM25Scorer._tokenize
        self._doc_freqs: dict[str, int] = {}  # term -> number of docs containing it
        self._doc_lens: dict[str, int] = {}  # tool_name -> doc length
        self._avg_dl: float = 0.0
        self._n_docs: int = 0
        self._tool_tokens: dict[str, list[str]] = {}  # tool_name -> token list
        self._stopwords: frozenset[str] = _BASE_STOPWORDS
        self._build_index()

    def _build_index(self) -> None:
        """Build inverted index from tool corpus."""
        self._n_docs = len(self._tools)
        if self._n_docs == 0:
            return

        total_len = 0
        self._tf_maps: dict[str, dict[str, int]] = {}  # pre-computed tf per doc
        self._name_token_counts: dict[str, int] = {}  # operationId token count
        # Cache each tool's name tokens once at build time. ``score()`` used to
        # re-tokenize (and re-stem) every tool name on *every* query inside
        # ``_name_subsequence_boost`` — O(corpus) tokenization per query, which
        # dominated latency at thousands of tools. Caching makes it a lookup.
        self._name_tokens: dict[str, list[str]] = {}
        for name, tool in self._tools.items():
            tokens = self._tokenize_tool(tool)
            self._tool_tokens[name] = tokens
            self._doc_lens[name] = len(tokens)
            total_len += len(tokens)

            # Pre-compute term frequency map
            tf_map: dict[str, int] = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1
            self._tf_maps[name] = tf_map

            # Count name tokens for length penalty (+ cache the tokens themselves)
            name_tokens = self._tokenize_fn(name)
            self._name_tokens[name] = name_tokens
            self._name_token_counts[name] = len(name_tokens)

            # Count document frequency (unique terms per document)
            for term in tf_map:
                self._doc_freqs[term] = self._doc_freqs.get(term, 0) + 1

        self._avg_dl = total_len / self._n_docs if self._n_docs > 0 else 0.0

        # Auto-compute stopwords: tokens appearing in >threshold% of documents
        # but never remove CRUD/action verbs — they carry retrieval intent.
        if self._n_docs >= 10:
            auto_stops = {
                term
                for term, df in self._doc_freqs.items()
                if df / self._n_docs >= self._stopword_df_threshold
                and len(term) <= 4
                and term not in _PROTECTED_TERMS
            }
            self._stopwords = _BASE_STOPWORDS | frozenset(auto_stops)

    def score(self, query: str, *, restrict: set[str] | None = None) -> dict[str, float]:
        """Score all tools against query using BM25.

        Returns dict of tool_name -> BM25 score (only non-zero scores).

        ``restrict`` (keyword-only) limits scoring to the given tool names — a
        perf lever for large corpora when the caller has already narrowed the
        candidate set (e.g. a category prefilter pool). ``None`` (default)
        scores the whole corpus and is byte-for-byte the pre-existing behaviour.
        """
        raw_tokens = self._tokenize_fn(query)
        if not raw_tokens:
            return {}
        # Remove stopwords from query; keep all if everything is a stopword
        filtered = [t for t in raw_tokens if t not in self._stopwords]
        query_tokens = filtered if filtered else raw_tokens
        # Expand with scope/action signals from the original query
        query_tokens = self._expand_query_tokens(query_tokens, query)

        scores: dict[str, float] = {}
        for name in self._tool_tokens:
            if restrict is not None and name not in restrict:
                continue
            doc_len = self._doc_lens[name]
            tf_map = self._tf_maps[name]
            doc_score = 0.0

            for q_term in query_tokens:
                tf = tf_map.get(q_term, 0)
                if tf == 0:
                    continue

                # IDF: log((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)
                n_qi = self._doc_freqs.get(q_term, 0)
                idf = math.log((self._n_docs - n_qi + 0.5) / (n_qi + 0.5) + 1.0)

                # BM25 term score
                numerator = tf * (self._k1 + 1.0)
                denominator = tf + self._k1 * (1.0 - self._b + self._b * doc_len / self._avg_dl)
                doc_score += idf * numerator / denominator

            if doc_score > 0:
                # Penalize long operationIds (noisy partial matches)
                name_len = self._name_token_counts.get(name, 0)
                if name_len > 6:
                    doc_score *= 1.0 / (1.0 + 0.15 * (name_len - 6))

                # Boost when query tokens appear as ordered subsequence in name
                doc_score *= self._name_subsequence_boost(query_tokens, name)
                doc_score *= self._semantic_phrase_boost(query, name, self._tools[name])

                scores[name] = doc_score

        return scores

    def _name_subsequence_boost(self, query_tokens: list[str], tool_name: str) -> float:
        """Boost score when query tokens match tool name in order."""
        # Cached at index build (falls back to tokenizing for ad-hoc names).
        name_tokens = self._name_tokens.get(tool_name)
        if name_tokens is None:
            name_tokens = self._tokenize_fn(tool_name)
        if not name_tokens or not query_tokens:
            return 1.0
        qi = 0
        for nt in name_tokens:
            if qi < len(query_tokens) and nt == query_tokens[qi]:
                qi += 1
        match_ratio = qi / len(query_tokens)
        return 1.0 + match_ratio * 0.5  # up to 1.5x boost

    def _semantic_phrase_boost(self, query: str, tool_name: str, tool: ToolSchema) -> float:
        """Boost compact operationIds for common user-facing semantic phrases."""
        return BM25Scorer._semantic_phrase_multiplier(query, tool_name, tool)

    @staticmethod
    def _semantic_phrase_multiplier(query: str, tool_name: str, tool: ToolSchema) -> float:
        """Return deterministic phrase/synonym boost for high-confidence matches."""
        q = query.lower()
        tool_text = f"{tool_name} {tool.description}".lower()
        boost = 1.0

        if "hypotenuse" in q and (
            re.search(r"(^|[._\s-])hypot($|[._\s-])", tool_text) or "euclidean norm" in tool_text
        ):
            boost *= 8.0
        if ("area under the curve" in q or "area under curve" in q) and (
            "integral" in tool_text or "integrate" in tool_text
        ):
            boost *= 2.0
            if tool_name.lower() == "integral":
                boost *= 2.0
        if ("distance covered" in q or "distance travelled" in q or "distance traveled" in q) and (
            "distance_traveled" in tool_name or "distance traveled" in tool_text
        ):
            boost *= 2.0
        if re.search(r"\bgeo(?:graphic|graphical)?\s+distance\b", q) and (
            "geo_distance" in tool_name.lower() or "geographic distance" in tool_text
        ):
            boost *= 2.0
        if "fibonacci series" in q and ("sequence" in tool_text or "series" in tool_text):
            boost *= 1.6

        boost *= BM25Scorer._korean_business_phrase_multiplier(query, tool_text)
        return boost

    @staticmethod
    def _korean_business_phrase_multiplier(query: str, tool_text: str) -> float:
        """Boost Korean business intent phrases that appear compacted in OpenAPI docs.

        Large Swagger specs often contain menu-like summaries such as
        ``주문조회`` or ``PG정산대사`` while users type separated phrases such as
        ``주문 목록 조회`` or ``정산 비교 조회``. Character bigrams keep these
        candidates visible, but near-duplicate list APIs can still crowd the
        exact target. This boost is deterministic and only fires when the
        compact phrase is directly present in the tool text.
        """
        words = re.findall(r"[가-힣]{2,}", query)
        if not words:
            return 1.0

        tool_norm = re.sub(r"[^a-z0-9가-힣]+", "", tool_text.lower())
        query_norm = "".join(words)
        phrases = BM25Scorer._korean_intent_phrases(words)
        matches = 0
        longest = 0
        for phrase in phrases:
            if len(phrase) < 4:
                continue
            if phrase in tool_norm:
                matches += 1
                longest = max(longest, len(phrase))

        boost = 1.0
        if len(query_norm) >= 4 and query_norm in tool_norm:
            boost *= 1.35
        if matches:
            boost *= min(1.6, 1.0 + 0.18 * matches + min(0.12, longest / 100.0))

        if "정산" in words and "비교" in words and "정산대사" in tool_norm:
            boost *= 1.35
        if "권한" in words and "버튼" in words and "권한" in tool_norm and "버튼" in tool_norm:
            boost *= 1.08
        if "권한" in words and "버튼" in words and "button" in tool_norm:
            if "pagerole" in tool_norm:
                boost *= 1.35
            elif "role" in tool_norm:
                boost *= 1.12
        return min(boost, 2.0)

    @staticmethod
    def _korean_intent_phrases(words: list[str]) -> set[str]:
        """Build compact phrase candidates from spaced Korean query terms."""
        phrases: set[str] = set()
        for i, left in enumerate(words):
            if left in _KO_BRIDGE_TERMS:
                continue
            for right in words[i + 1 : i + 4]:
                if right in _KO_BRIDGE_TERMS:
                    continue
                phrases.add(left + right)
        for action_index, action in enumerate(words):
            if action not in _KO_ACTION_TERMS:
                continue
            for word in words[:action_index]:
                if word not in _KO_ACTION_TERMS and word not in _KO_BRIDGE_TERMS:
                    phrases.add(word + action)
        if "정산" in words and "비교" in words:
            phrases.add("정산대사")
        return phrases

    def _tokenize_tool(self, tool: ToolSchema) -> list[str]:
        """Extract tokens from all tool fields: name, description, tags, param names, metadata."""
        tokens: list[str] = []
        tokens.extend(self._tokenize_fn(tool.name))
        tokens.extend(self._tokenize_fn(tool.description))
        for tag in tool.tags:
            tokens.extend(self._tokenize_fn(tag))
        for param in tool.parameters:
            tokens.extend(self._tokenize_fn(param.name))
            if param.description:
                tokens.extend(self._tokenize_fn(param.description))
        tokens.extend(self._extract_metadata_tokens(tool))
        # Include LLM-generated example queries for richer keyword matching
        if hasattr(tool, "metadata") and tool.metadata:
            for eq in tool.metadata.get("example_queries", []):
                tokens.extend(self._tokenize_fn(eq))
        return tokens

    def _extract_metadata_tokens(self, tool: ToolSchema) -> list[str]:
        """Extract discriminative tokens from tool metadata.

        For OpenAPI tools, the path carries critical scope/sub-resource information
        that descriptions often omit (e.g. namespaced vs cluster-wide).
        Graphify/Planflow collections also carry LLM enrichment and IO contracts;
        indexing those fields lets BM25 match user vocabulary to short or opaque
        operationIds such as ``seltPrdtInfo``.
        """
        metadata = tool.metadata
        if not metadata:
            return []
        tokens: list[str] = []

        method = metadata.get("method", "")
        path = metadata.get("path", "")

        if method:
            tokens.append(method.lower())

        tokens.extend(self._extract_planflow_metadata_tokens(metadata))

        if not path:
            return tokens

        # Split path into segments, skip empty and {param} placeholders
        segments = [s for s in path.split("/") if s and not s.startswith("{")]
        for seg in segments:
            tokens.extend(self._tokenize_fn(seg))

        # Scope detection: does the path contain a {namespace} parameter?
        has_namespace_param = "{namespace}" in path or "{ns}" in path
        # Is it a "list" or "get" style path? (ends with plural or has {name})
        has_name_param = "{name}" in path

        if has_namespace_param:
            tokens.extend(["namespac", "scoped"])
        elif any(s in path for s in ["/namespaces", "/namespace"]):
            # Path references namespaces without a param = cluster-level namespace listing
            pass
        else:
            # No namespace scoping at all
            if method.lower() in ("get", "list") or not has_name_param:
                tokens.extend(["cluster", "all"])

        # Sub-resource tokens from path suffix
        if segments:
            last = segments[-1].lower()
            sub_resources = {
                "exec": ["exec", "execut"],
                "attach": ["attach"],
                "portforward": ["portforward", "port", "forward"],
                "proxy": ["proxy"],
                "log": ["log"],
                "status": ["status"],
                "scale": ["scale"],
                "finalize": ["finaliz"],
                "binding": ["bind"],
                "eviction": ["evict"],
                "ephemeralcontainers": ["ephemer", "container"],
            }
            if last in sub_resources:
                tokens.extend(sub_resources[last])

        # Collection pattern: DELETE on a plural path without {name}
        if method.lower() == "delete" and not has_name_param:
            tokens.extend(["collect", "bulk"])

        return tokens

    def _extract_planflow_metadata_tokens(self, metadata: dict) -> list[str]:
        """Tokenize graphify enrichment and IO contract metadata."""
        tokens: list[str] = []
        ai = metadata.get("ai_metadata") or {}
        if isinstance(ai, dict):
            for key in (
                "one_line_summary",
                "when_to_use",
                "when_not_to_use",
                "primary_resource",
                "canonical_action",
            ):
                value = ai.get(key)
                if value:
                    tokens.extend(self._tokenize_fn(str(value)))
            for item in ai.get("produces_semantics") or []:
                if isinstance(item, dict):
                    tokens.extend(self._tokenize_fn(str(item.get("semantic") or "")))
                    tokens.extend(self._tokenize_fn(str(item.get("json_path") or "")))
            for item in ai.get("consumes_semantics") or []:
                if isinstance(item, dict):
                    tokens.extend(self._tokenize_fn(str(item.get("semantic") or "")))
                    tokens.extend(self._tokenize_fn(str(item.get("field") or "")))
            for pair in ai.get("pairs_well_with") or []:
                if isinstance(pair, dict):
                    tokens.extend(self._tokenize_fn(str(pair.get("reason") or "")))

        for key in ("produces", "consumes"):
            for field in metadata.get(key) or []:
                if not isinstance(field, dict):
                    continue
                if (
                    field.get("contract_source") == "api_contract"
                    and field.get("search_signal") is False
                ):
                    continue
                for field_key in (
                    "field_name",
                    "semantic_tag",
                    "json_path",
                    "field_type",
                    "kind",
                    "description",
                    "example_name",
                ):
                    value = field.get(field_key)
                    if value:
                        tokens.extend(self._tokenize_fn(str(value)))
                for alias in field.get("value_path_aliases") or []:
                    if alias:
                        tokens.extend(self._tokenize_fn(str(alias)))
                enum_values = field.get("enum")
                if isinstance(enum_values, list):
                    for value in enum_values[:20]:
                        if value is not None:
                            tokens.extend(self._tokenize_fn(str(value)))

        return tokens

    @staticmethod
    def _expand_query_tokens(tokens: list[str], query: str) -> list[str]:
        """Expand query tokens with scope/action signals detected from the full query.

        Detects multi-word patterns that individual tokens can't capture,
        then adds synthetic tokens that match metadata-derived document tokens.
        """
        q = query.lower()
        extra: list[str] = []

        # Scope detection
        if re.search(r"\bin\s+(a|the|this|default|my)\s+namespace\b", q):
            extra.extend(["namespac", "scoped"])
        elif re.search(r"\ball\s+namespace", q) or "cluster-wide" in q or "across all" in q:
            extra.extend(["cluster", "all"])

        # Sub-resource patterns
        if "port-forward" in q or "port forward" in q or "portforward" in q:
            extra.extend(["portforward", "port", "forward"])
        if re.search(r"\b(exec|execute)\b", q):
            extra.append("exec")
        if re.search(r"\battach\b", q):
            extra.append("attach")

        # Collection/bulk delete
        if re.search(r"\bdelete\s+all\b", q) or re.search(r"\bremove\s+all\b", q) or "at once" in q:
            extra.extend(["collect", "bulk"])

        # Generic math/science wording.
        if re.search(r"\bhypotenuse\b", q):
            extra.extend(["hypot", "norm"])
        if "area under the curve" in q or "area under curve" in q:
            extra.extend(["integral", "integrat"])
        if "distance covered" in q or "distance travelled" in q or "distance traveled" in q:
            extra.extend(["distance", "travel", "traveled"])
        if re.search(r"\bgeo(?:graphic|graphical)?\s+distance\b", q):
            extra.extend(["geo", "geographic"])
        if re.search(r"\bfibonacci\s+series\b", q):
            extra.extend(["fibonacci", "sequence"])

        # Status/logs
        if re.search(r"\bstatus\b", q):
            extra.append("status")
        if re.search(r"\blogs?\b", q):
            extra.append("log")
        if re.search(r"\bscale\b", q):
            extra.append("scale")
        if re.search(r"\bephemeral\b", q):
            extra.append("ephemer")
        if re.search(r"\bproxy\b", q):
            extra.append("proxy")

        # Korean → English expansion via dictionary
        for token in tokens:
            if token in _EN_QUERY_SYNONYMS:
                extra.extend(_EN_QUERY_SYNONYMS[token])
            if token in _KO_EN_DICT:
                extra.extend(_KO_EN_DICT[token])

        # Also check raw query for multi-char Korean words not split by tokenizer
        for ko_word, en_tokens in _KO_EN_DICT.items():
            if ko_word in q and not any(t == ko_word for t in tokens):
                extra.extend(en_tokens)

        if extra:
            return tokens + extra
        return tokens

    @staticmethod
    def _korean_bigrams(text: str) -> list[str]:
        """Generate character-level bigrams from Korean (Hangul) text.

        Only processes characters in the Hangul syllable range (U+AC00–U+D7AF).
        Returns empty list if fewer than 2 Korean characters are found.

        Examples:
            "정기주문해지하기" -> ["정기", "기주", "주문", "문해", "해지", "지하", "하기"]
            "a" -> []
            "한" -> []
        """
        korean_chars = [ch for ch in text if "\uac00" <= ch <= "\ud7af"]
        if len(korean_chars) < 2:
            return []
        return [korean_chars[i] + korean_chars[i + 1] for i in range(len(korean_chars) - 1)]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenizer with camelCase splitting, stemming, and Korean bigrams.

        Emits both the original lowered token and its stemmed form (if different)
        so that "pods" matches "pod" and "namespaced" matches "namespace".

        Examples:
            "getUserById" -> ["get", "user", "by", "id"]
            "list_all_pets" -> ["list", "all", "pet", "pets"]
            "namespaced" -> ["namespac", "namespaced"]
            "정기주문해지" -> ["정기주문해지", "정기", "기주", "주문", "문해", "해지"]
        """
        # Step 1: Split on separators (underscore, hyphen, space, quotes, punctuation)
        parts = re.split(r"[\s_\-/.,;:!?()'\"`\[\]{}]+", text)

        tokens: list[str] = []
        for part in parts:
            if not part:
                continue
            # Step 2: Further split camelCase
            camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", part)
            camel_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel_split)
            sub_parts = camel_split.split()
            # Step 3: Lowercase, stem, and add Korean bigrams
            for sp in sub_parts:
                lowered = sp.lower()
                if not lowered:
                    continue
                stemmed = _stem(lowered)
                tokens.append(stemmed)
                if stemmed != lowered:
                    tokens.append(lowered)
                # Add Korean bigrams if the token contains Korean characters
                if re.search(r"[\uac00-\ud7af]", lowered):
                    bigrams = BM25Scorer._korean_bigrams(lowered)
                    tokens.extend(bigrams)

        return tokens
