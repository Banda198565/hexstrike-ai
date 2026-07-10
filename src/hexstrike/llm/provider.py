"""Ollama / OpenAI-compatible local LLM provider."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "deepseek-r1"
DEFAULT_NUM_THREAD = 16
DEFAULT_NUM_PREDICT = 16


def ollama_request_options() -> dict[str, int]:
    """Runtime options for deepseek-r1 — tune via OLLAMA_NUM_THREAD / OLLAMA_NUM_PREDICT."""
    return {
        "num_thread": int(os.environ.get("OLLAMA_NUM_THREAD", DEFAULT_NUM_THREAD)),
        "num_predict": int(os.environ.get("OLLAMA_NUM_PREDICT", DEFAULT_NUM_PREDICT)),
    }


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    host: str
    base_url: str
    model: str
    integration_mode: str
    bypass_tunnel: bool


def _local_base_url(host: str) -> str:
    return f"{host.rstrip('/')}/v1"


def detect_local_ollama(host: str = DEFAULT_HOST, timeout: float = 3.0) -> bool:
    """Return True when Ollama responds on the given host."""
    url = f"{host.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def list_models(host: str = DEFAULT_HOST, timeout: float = 5.0) -> list[str]:
    url = f"{host.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    return [m.get("name", "") for m in payload.get("models", [])]


def has_deepseek_r1(models: list[str]) -> bool:
    return any("deepseek-r1" in name for name in models)


def resolve_llm_config() -> LlmConfig:
    """Resolve LLM endpoint — localhost wins when local inference is available."""
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    model = os.environ.get("OLLAMA_MODEL", os.environ.get("LLM_MODEL", DEFAULT_MODEL))
    integration_mode = os.environ.get("CURSOR_INTEGRATION_MODE", "SYSTEM_INTEGRATION")
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

    provider = os.environ.get("LLM_PROVIDER", "ollama-local")
    return LlmConfig(
        provider=provider,
        host=host,
        base_url=base_url,
        model=model,
        integration_mode=integration_mode,
        bypass_tunnel=bypass_tunnel,
    )


class LocalLlmProvider:
    """Thin client for Ollama OpenAI-compatible API."""

    def __init__(self, config: LlmConfig | None = None) -> None:
        self.config = config or resolve_llm_config()
        os.environ.setdefault("LLM_PROVIDER", self.config.provider)
        os.environ.setdefault("LLM_BASE_URL", self.config.base_url)
        os.environ.setdefault("LLM_MODEL", self.config.model)

    def status(self) -> dict[str, Any]:
        local_ok = detect_local_ollama(self.config.host)
        models: list[str] = []
        if local_ok:
            try:
                models = list_models(self.config.host)
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
                models = []
        return {
            "provider": self.config.provider,
            "host": self.config.host,
            "base_url": self.config.base_url,
            "model": self.config.model,
            "integration_mode": self.config.integration_mode,
            "bypass_tunnel": self.config.bypass_tunnel,
            "local_inference": local_ok,
            "deepseek_r1_available": has_deepseek_r1(models),
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
            headers = {"Content-Type": "application/json"}
        else:
            url = f"{self.config.base_url}/models"
            body = None
            headers = {}

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
