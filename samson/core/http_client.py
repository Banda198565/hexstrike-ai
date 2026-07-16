"""Production HTTP client with retries, timeouts, TLS verification, and structured errors."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from samson.core.config import SamsonSettings, get_settings
from samson.core.errors import NetworkError

logger = logging.getLogger(__name__)


class SamsonHttpClient:
    """Synchronous HTTP client for arena targets, Ollama, and mock payment services."""

    def __init__(self, settings: SamsonSettings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=self._settings.http_connect_timeout_sec,
                read=self._settings.http_timeout_sec,
                write=self._settings.http_timeout_sec,
                pool=self._settings.http_connect_timeout_sec,
            ),
            headers={"User-Agent": self._settings.http_user_agent},
            follow_redirects=False,
            verify=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SamsonHttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        content: bytes | None = None,
        expected_status: tuple[int, ...] = (200, 201, 202, 204),
    ) -> httpx.Response:
        last_exc: Exception | None = None
        merged_headers = dict(headers or {})

        for attempt in range(1, self._settings.http_max_retries + 1):
            try:
                response = self._client.request(
                    method=method.upper(),
                    url=url,
                    json=json,
                    headers=merged_headers,
                    params=params,
                    content=content,
                )
                if response.status_code in expected_status:
                    return response

                if response.status_code in (429, 502, 503, 504) and attempt < self._settings.http_max_retries:
                    sleep_for = self._settings.http_retry_backoff_sec * attempt
                    logger.warning(
                        "HTTP %s %s -> %s; retry %s/%s in %.1fs",
                        method,
                        url,
                        response.status_code,
                        attempt,
                        self._settings.http_max_retries,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue

                raise NetworkError(
                    f"HTTP {response.status_code} from {method} {url}",
                    url=url,
                    method=method,
                    status_code=response.status_code,
                    body=response.text[:2000],
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt >= self._settings.http_max_retries:
                    break
                time.sleep(self._settings.http_retry_backoff_sec * attempt)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= self._settings.http_max_retries:
                    break
                time.sleep(self._settings.http_retry_backoff_sec * attempt)

        raise NetworkError(
            f"HTTP request failed after {self._settings.http_max_retries} attempts: {method} {url}",
            url=url,
            method=method,
            error=str(last_exc),
        )

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs).json()

    def post_json(self, url: str, payload: dict[str, Any], **kwargs: Any) -> Any:
        response = self.request("POST", url, json=payload, **kwargs)
        if not response.content:
            return {}
        return response.json()


class OllamaClient:
    """Ollama embedding and chat API over real HTTP."""

    def __init__(self, settings: SamsonSettings | None = None, http: SamsonHttpClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._http = http or SamsonHttpClient(self._settings)
        self._owns_http = http is None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def embed(self, text: str) -> list[float]:
        url = f"{self._settings.ollama_base_url_str}/api/embeddings"
        payload = {"model": self._settings.ollama_embed_model, "prompt": text}
        try:
            data = self._http.post_json(url, payload)
        except NetworkError as exc:
            raise NetworkError(
                f"Ollama embedding failed for model {self._settings.ollama_embed_model}",
                model=self._settings.ollama_embed_model,
                error=exc.detail.message,
            ) from exc

        embedding = data.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise NetworkError(
                "Ollama returned empty embedding vector",
                model=self._settings.ollama_embed_model,
                response_keys=list(data.keys()) if isinstance(data, dict) else [],
            )
        return [float(x) for x in embedding]

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
        url = f"{self._settings.ollama_base_url_str}/api/chat"
        payload = {
            "model": self._settings.ollama_chat_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        data = self._http.post_json(url, payload)
        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise NetworkError("Ollama chat returned empty content", model=self._settings.ollama_chat_model)
        return content.strip()

    def health_check(self) -> dict[str, Any]:
        url = f"{self._settings.ollama_base_url_str}/api/tags"
        return self._http.get_json(url)
