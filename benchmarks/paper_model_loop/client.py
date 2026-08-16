"""Small deterministic chat client for the paper model-loop harness."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelResponse:
    """One provider-neutral chat completion."""

    content: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    status_code: int = 0
    finish_reason: str = ""
    error: str = ""

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        value = asdict(self)
        if not include_content:
            value.pop("content", None)
        return value


class ModelClient(Protocol):
    """Injected model interface used by network-free contract tests."""

    provider: str

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        seed: int,
        timeout: int,
        max_tokens: int,
    ) -> ModelResponse:
        """Return one deterministic JSON-oriented chat completion."""


class HTTPModelClient:
    """Call an OpenAI-compatible or Ollama chat endpoint without storing secrets."""

    def __init__(
        self,
        *,
        model: str,
        url: str,
        provider: str,
        disable_thinking: bool = True,
        include_seed: bool = True,
        api_key_env: str = "OPENAI_API_KEY",
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        if not model.strip() or not url.strip():
            raise ValueError("model and url must be non-empty.")
        if provider not in {"openai-compatible", "ollama"}:
            raise ValueError("provider must be openai-compatible or ollama.")
        self.model = model
        self.url = url
        self.provider = provider
        self.disable_thinking = disable_thinking
        self.include_seed = include_seed
        self.api_key_env = api_key_env
        self.extra_body = dict(extra_body or {})

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        seed: int,
        timeout: int,
        max_tokens: int,
    ) -> ModelResponse:
        """Call the configured endpoint with temperature zero."""
        if self.provider == "ollama":
            return self._complete_ollama(
                messages,
                seed=seed,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        return self._complete_openai(
            messages,
            seed=seed,
            timeout=timeout,
            max_tokens=max_tokens,
        )

    def _complete_openai(
        self,
        messages: list[dict[str, str]],
        *,
        seed: int,
        timeout: int,
        max_tokens: int,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if self.include_seed:
            payload["seed"] = seed
        if self.disable_thinking and "thinking" not in self.extra_body:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        payload.update(self.extra_body)
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get(self.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        url = self.url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        started = time.perf_counter()
        body, status_code, error = _post_json(url, payload, headers=headers, timeout=timeout)
        latency_ms = (time.perf_counter() - started) * 1000
        if error:
            return ModelResponse(
                latency_ms=latency_ms,
                status_code=status_code,
                error=error,
            )
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = body.get("usage") or {}
        return ModelResponse(
            content=str(message.get("content") or ""),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency_ms,
            status_code=status_code,
            finish_reason=str(choice.get("finish_reason") or ""),
        )

    def _complete_ollama(
        self,
        messages: list[dict[str, str]],
        *,
        seed: int,
        timeout: int,
        max_tokens: int,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": max_tokens,
            },
        }
        if self.include_seed:
            payload["options"]["seed"] = seed
        if self.disable_thinking:
            payload["think"] = False
        started = time.perf_counter()
        body, status_code, error = _post_json(
            self.url,
            payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        if error:
            return ModelResponse(
                latency_ms=latency_ms,
                status_code=status_code,
                error=error,
            )
        message = body.get("message") or {}
        return ModelResponse(
            content=str(message.get("content") or ""),
            input_tokens=int(body.get("prompt_eval_count") or 0),
            output_tokens=int(body.get("eval_count") or 0),
            latency_ms=latency_ms,
            status_code=status_code,
            finish_reason=str(body.get("done_reason") or ""),
        )


def redacted_url(url: str) -> str:
    """Remove embedded credentials and sensitive query values from artifact URLs."""
    try:
        parsed = urllib.parse.urlsplit(url)
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = f"***@{netloc.rsplit('@', 1)[1]}"
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        scrubbed_query = urllib.parse.urlencode(
            [(key, "***" if _is_sensitive_query_key(key) else value) for key, value in query]
        )
        return urllib.parse.urlunsplit(
            (parsed.scheme, netloc, parsed.path, scrubbed_query, parsed.fragment)
        )
    except ValueError:
        return re.sub(r"://([^/@]+)@", "://***@", url)


def _is_sensitive_query_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", key.lower())
    return any(
        marker in normalized
        for marker in ("apikey", "token", "authorization", "password", "secret", "signature")
    )


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: int,
) -> tuple[dict[str, Any], int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = json.loads(response.read().decode())
            return (body if isinstance(body, dict) else {}, int(response.status), "")
    except urllib.error.HTTPError as exc:
        return {}, int(exc.code), f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return {}, 0, redacted_url(f"{type(exc).__name__}: {exc}")
