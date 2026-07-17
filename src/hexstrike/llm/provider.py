"""Ollama / OpenAI-compatible local and cloud LLM provider."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_CLOUD_HOST = "https://ollama.com"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_CLOUD_MODEL = "qwen3-coder:480b-cloud"
DEFAULT_CLOUD_DIRECT_MODEL = "qwen3.5:397b"
DEFAULT_NUM_THREAD = 16
DEFAULT_NUM_PREDICT = 512
DEFAULT_NUM_CTX = 32768

PROVIDER_LOCAL = "ollama-local"
PROVIDER_LOCAL_CLOUD = "ollama-local-cloud"
PROVIDER_CLOUD = "ollama-cloud"


def rescue_path_blocks_llm() -> bool:
    """When true, LLM must not run synchronously on PrepareRescue / signing hot path."""
    return os.environ.get("LLM_ASYNC_ONLY", "1").lower() in ("1", "true", "yes")


def enqueue_llm_task(fn) -> None:
    """Fire-and-forget LLM work (bytecode deobfuscation, extended OSINT)."""
    import threading

    threading.Thread(target=fn, daemon=True, name="hexstrike-llm-async").start()


def ollama_request_options() -> dict[str, int]:
    """Runtime Ollama options — tune via OLLAMA_NUM_THREAD / OLLAMA_NUM_PREDICT / OLLAMA_NUM_CTX."""
    opts: dict[str, int] = {
        "num_thread": int(os.environ.get("OLLAMA_NUM_THREAD", DEFAULT_NUM_THREAD)),
        "num_predict": int(os.environ.get("OLLAMA_NUM_PREDICT", DEFAULT_NUM_PREDICT)),
    }
    num_ctx = os.environ.get("OLLAMA_NUM_CTX")
    if num_ctx:
        opts["num_ctx"] = int(num_ctx)
    elif "qwen2.5-coder" in os.environ.get("OLLAMA_MODEL", os.environ.get("LLM_MODEL", DEFAULT_MODEL)):
        opts["num_ctx"] = DEFAULT_NUM_CTX
    return opts


def is_cloud_model(model: str) -> bool:
    """True when the model tag is an Ollama cloud-offload variant (e.g. gpt-oss:120b-cloud)."""
    return model.endswith("-cloud") or ":cloud" in model


def is_cloud_direct_host(host: str) -> bool:
    """True when routing directly to ollama.com instead of a local daemon."""
    normalized = host.rstrip("/").lower()
    return normalized in (DEFAULT_CLOUD_HOST, "https://ollama.com", "http://ollama.com")


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    host: str
    base_url: str
    model: str
    integration_mode: str
    bypass_tunnel: bool
    api_key: str | None = None
    cloud_mode: str = "local"  # local | local-cloud | cloud-direct


def _local_base_url(host: str) -> str:
    return f"{host.rstrip('/')}/v1"


def _auth_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _request_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
        return resp.status, payload


def detect_ollama(host: str = DEFAULT_HOST, *, api_key: str | None = None, timeout: float = 3.0) -> bool:
    """Return True when Ollama responds on the given host."""
    url = f"{host.rstrip('/')}/api/tags"
    try:
        _request_json(url, headers=_auth_headers(api_key), timeout=timeout)
        return True
    except (urllib.error.URLError, TimeoutError, OSError, urllib.error.HTTPError, json.JSONDecodeError):
        return False


def detect_local_ollama(host: str = DEFAULT_HOST, timeout: float = 3.0) -> bool:
    """Return True when a local Ollama daemon responds on the given host."""
    if is_cloud_direct_host(host):
        return False
    return detect_ollama(host, timeout=timeout)


def list_models(
    host: str = DEFAULT_HOST,
    *,
    api_key: str | None = None,
    timeout: float = 5.0,
) -> list[str]:
    url = f"{host.rstrip('/')}/api/tags"
    _, payload = _request_json(url, headers=_auth_headers(api_key), timeout=timeout)
    return [m.get("name", "") for m in payload.get("models", [])]


def has_qwen_coder(models: list[str]) -> bool:
    return any("qwen2.5-coder" in name or "qwen3-coder" in name for name in models)


def has_deepseek_r1(models: list[str]) -> bool:
    return any("deepseek-r1" in name for name in models)


def resolve_llm_config() -> LlmConfig:
    """Resolve LLM endpoint — localhost, local cloud offload, or ollama.com direct API."""
    provider = os.environ.get("LLM_PROVIDER", PROVIDER_LOCAL).strip().lower()
    integration_mode = os.environ.get("CURSOR_INTEGRATION_MODE", "SYSTEM_INTEGRATION")
    api_key = os.environ.get("OLLAMA_API_KEY", "").strip() or None
    model = os.environ.get("OLLAMA_MODEL", os.environ.get("LLM_MODEL", DEFAULT_MODEL))

    cloud_host = os.environ.get("OLLAMA_CLOUD_HOST", DEFAULT_CLOUD_HOST).strip() or DEFAULT_CLOUD_HOST
    local_host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)

    if provider == PROVIDER_CLOUD or (is_cloud_direct_host(local_host) and api_key):
        host = cloud_host if provider == PROVIDER_CLOUD else local_host
        base_url = _local_base_url(host)
        if not model or model == DEFAULT_MODEL:
            model = os.environ.get("OLLAMA_CLOUD_MODEL", DEFAULT_CLOUD_DIRECT_MODEL)
        cloud_mode = "cloud-direct"
        bypass_tunnel = False
        resolved_provider = PROVIDER_CLOUD
    elif provider == PROVIDER_LOCAL_CLOUD or is_cloud_model(model):
        host = local_host
        base_url = _local_base_url(host)
        if model == DEFAULT_MODEL:
            model = os.environ.get("OLLAMA_CLOUD_MODEL", DEFAULT_CLOUD_MODEL)
        cloud_mode = "local-cloud"
        bypass_tunnel = detect_local_ollama(host)
        resolved_provider = PROVIDER_LOCAL_CLOUD
        api_key = None
    else:
        host = local_host
        local_ok = detect_local_ollama(host)
        bypass_tunnel = os.environ.get("OLLAMA_BYPASS_TUNNEL", "").lower() in ("1", "true", "yes")
        if local_ok:
            bypass_tunnel = True

        public = os.environ.get("OLLAMA_PUBLIC_BASE_URL", "").strip()
        if bypass_tunnel or integration_mode == "OFFLINE_PRIMARY":
            base_url = _local_base_url(host)
        elif public:
            base_url = public if public.endswith("/v1") else f"{public.rstrip('/')}/v1"
        else:
            base_url = _local_base_url(host)

        cloud_mode = "local"
        resolved_provider = PROVIDER_LOCAL
        api_key = None

    return LlmConfig(
        provider=resolved_provider,
        host=host,
        base_url=base_url,
        model=model,
        integration_mode=integration_mode,
        bypass_tunnel=bypass_tunnel,
        api_key=api_key,
        cloud_mode=cloud_mode,
    )


class LocalLlmProvider:
    """Thin client for Ollama OpenAI-compatible API (local, local-cloud, or cloud-direct)."""

    def __init__(self, config: LlmConfig | None = None) -> None:
        self.config = config or resolve_llm_config()
        os.environ.setdefault("LLM_PROVIDER", self.config.provider)
        os.environ.setdefault("LLM_BASE_URL", self.config.base_url)
        os.environ.setdefault("LLM_MODEL", self.config.model)

    def _headers(self, *, content_type: bool = False) -> dict[str, str]:
        headers = _auth_headers(self.config.api_key)
        if content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def status(self) -> dict[str, Any]:
        local_ok = detect_local_ollama(self.config.host)
        cloud_direct = self.config.cloud_mode == "cloud-direct"
        reachable = detect_ollama(
            self.config.host,
            api_key=self.config.api_key,
            timeout=8.0 if cloud_direct else 3.0,
        )
        models: list[str] = []
        if reachable:
            try:
                models = list_models(self.config.host, api_key=self.config.api_key)
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, urllib.error.HTTPError):
                models = []
        return {
            "provider": self.config.provider,
            "host": self.config.host,
            "base_url": self.config.base_url,
            "model": self.config.model,
            "integration_mode": self.config.integration_mode,
            "bypass_tunnel": self.config.bypass_tunnel,
            "cloud_mode": self.config.cloud_mode,
            "cloud_authenticated": bool(self.config.api_key),
            "local_inference": local_ok,
            "endpoint_reachable": reachable,
            "qwen_coder_available": has_qwen_coder(models),
            "deepseek_r1_available": has_deepseek_r1(models),
            "cloud_model": is_cloud_model(self.config.model),
            "models": models,
            "options": ollama_request_options(),
        }

    def measure_hook_latency(self, *, probe: str = "models") -> dict[str, Any]:
        """Measure round-trip latency for the Cursor ↔ model hook."""
        if probe == "chat":
            url = f"{self.config.base_url}/chat/completions"
            body = json.dumps(
                {
                    "model": self.config.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": False,
                    "options": ollama_request_options(),
                }
            ).encode()
            headers = self._headers(content_type=True)
        else:
            url = f"{self.config.base_url}/models"
            body = None
            headers = self._headers()

        start = time.perf_counter()
        req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                elapsed_ms = (time.perf_counter() - start) * 1000
                return {
                    "probe": probe,
                    "url": url,
                    "status": resp.status,
                    "latency_ms": round(elapsed_ms, 2),
                    "ok": True,
                }
        except urllib.error.HTTPError as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            detail = exc.read(300).decode(errors="replace")
            return {
                "probe": probe,
                "url": url,
                "status": exc.code,
                "latency_ms": round(elapsed_ms, 2),
                "ok": False,
                "error": detail[:200],
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return {
                "probe": probe,
                "url": url,
                "latency_ms": round(elapsed_ms, 2),
                "ok": False,
                "error": str(exc),
            }
