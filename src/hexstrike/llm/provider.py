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
DEFAULT_MODEL = "deepseek-r1:1.5b"
DEFAULT_NUM_THREAD = 16
DEFAULT_NUM_PREDICT = 256

# llama-server (llama.cpp) default OpenAI-compatible endpoint
LLAMA_SERVER_HOST = "http://127.0.0.1:8080"

# Provider priority (first alive wins). Override with LLM_PROVIDER_PRIORITY.
DEFAULT_PROVIDER_PRIORITY = ("llama-server", "ollama-local")


def rescue_path_blocks_llm() -> bool:
    """When true, LLM must not run synchronously on PrepareRescue / signing hot path."""
    return os.environ.get("LLM_ASYNC_ONLY", "1").lower() in ("1", "true", "yes")


def enqueue_llm_task(fn) -> None:
    """Fire-and-forget LLM work (bytecode deobfuscation, extended OSINT)."""
    import threading

    threading.Thread(target=fn, daemon=True, name="hexstrike-llm-async").start()


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


def detect_llama_server(host: str = LLAMA_SERVER_HOST, timeout: float = 3.0) -> bool:
    """Return True when llama.cpp llama-server responds on the given host."""
    url = f"{host.rstrip('/')}/v1/models"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def llama_server_models(host: str = LLAMA_SERVER_HOST, timeout: float = 5.0) -> list[str]:
    url = f"{host.rstrip('/')}/v1/models"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
        return [m.get("id", "") for m in payload.get("data", [])]
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []


def list_models(host: str = DEFAULT_HOST, timeout: float = 5.0) -> list[str]:
    url = f"{host.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    return [m.get("name", "") for m in payload.get("models", [])]


def has_deepseek_r1(models: list[str]) -> bool:
    return any("deepseek-r1" in name for name in models)


def resolve_llm_config() -> LlmConfig:
    """Resolve LLM endpoint — llama-server on :8080 preferred, Ollama fallback.

    Priority (first alive wins):
      1. LLM_PROVIDER=llama-server (or auto-detect on LLAMA_SERVER_HOST)
      2. LLM_PROVIDER=ollama-local (or auto-detect on OLLAMA_HOST)

    Override auto-detect with:
      LLM_PROVIDER=<name>          — force this provider
      LLM_BASE_URL=http://…/v1     — force explicit URL
      LLM_PROVIDER_PRIORITY=llama-server,ollama-local
    """
    integration_mode = os.environ.get("CURSOR_INTEGRATION_MODE", "SYSTEM_INTEGRATION")

    priority_env = os.environ.get("LLM_PROVIDER_PRIORITY", "")
    if priority_env:
        priority = tuple(x.strip() for x in priority_env.split(",") if x.strip())
    else:
        priority = DEFAULT_PROVIDER_PRIORITY

    llama_host = os.environ.get("LLAMA_SERVER_HOST", LLAMA_SERVER_HOST)
    ollama_host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)

    explicit_provider = os.environ.get("LLM_PROVIDER", "").strip()
    explicit_base = os.environ.get("LLM_BASE_URL", "").strip()

    def _pick(name: str) -> tuple[str, str, str] | None:
        if name in ("llama-server", "llama.cpp", "openai-local"):
            if detect_llama_server(llama_host):
                models = llama_server_models(llama_host)
                model = os.environ.get("LLM_MODEL") or (models[0] if models else "local")
                base = f"{llama_host.rstrip('/')}/v1"
                return name, base, model
        elif name in ("ollama-local", "ollama"):
            if detect_local_ollama(ollama_host):
                model = os.environ.get("OLLAMA_MODEL", os.environ.get("LLM_MODEL", DEFAULT_MODEL))
                base = _local_base_url(ollama_host)
                return name, base, model
        return None

    picked: tuple[str, str, str] | None = None

    # 1. explicit user choice
    if explicit_provider:
        picked = _pick(explicit_provider)

    # 2. explicit base URL (skip detection)
    if picked is None and explicit_base:
        model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        picked = (explicit_provider or "custom", explicit_base, model)

    # 3. priority scan
    if picked is None:
        for name in priority:
            picked = _pick(name)
            if picked is not None:
                break

    # 4. fallback (Ollama default, may be down — caller sees local_inference=False)
    if picked is None:
        model = os.environ.get("OLLAMA_MODEL", os.environ.get("LLM_MODEL", DEFAULT_MODEL))
        picked = ("ollama-local", _local_base_url(ollama_host), model)

    provider, base_url, model = picked

    # bypass_tunnel: always true when talking to localhost
    host = llama_host if provider.startswith(("llama", "openai-local")) else ollama_host
    bypass_tunnel = os.environ.get("OLLAMA_BYPASS_TUNNEL", "").lower() in ("1", "true", "yes")
    if base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost"):
        bypass_tunnel = True

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
        provider = self.config.provider
        models: list[str] = []
        local_ok = False
        if provider.startswith(("llama", "openai-local")):
            local_ok = detect_llama_server(self.config.host)
            if local_ok:
                models = llama_server_models(self.config.host)
        else:
            local_ok = detect_local_ollama(self.config.host)
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
