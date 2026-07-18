"""Cloud DeepSeek R1 provider — OpenRouter, DeepSeek official, or any OpenAI-compatible endpoint.

Reasoning-only backend for HexStrike orchestrator. Does not execute tools.

Env:
  R1_PROVIDER=openrouter|deepseek|custom
  R1_API_KEY=...
  R1_BASE_URL=...          (optional; inferred from provider)
  R1_MODEL=...             (optional; provider default)
  R1_TIMEOUT_SEC=180
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]

PROVIDER_OPENROUTER = "openrouter"
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_CUSTOM = "custom"

DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-r1:free"
DEFAULT_DEEPSEEK_MODEL = "deepseek-reasoner"

_THINKING_RE = re.compile(r"<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>", re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _load_dotenv() -> None:
    env_path = _REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


@dataclass(frozen=True)
class CloudR1Config:
    provider: str
    base_url: str
    model: str
    api_key: str | None
    timeout_sec: float = 180.0
    site_url: str | None = None
    site_name: str | None = None


def resolve_cloud_r1_config() -> CloudR1Config:
    """Resolve cloud R1 endpoint from environment."""
    _load_dotenv()
    provider = os.environ.get("R1_PROVIDER", PROVIDER_OPENROUTER).strip().lower()
    api_key = (
        os.environ.get("R1_API_KEY", "").strip()
        or os.environ.get("OPENROUTER_API_KEY", "").strip()
        or os.environ.get("DEEPSEEK_API_KEY", "").strip()
        or None
    )
    timeout = float(os.environ.get("R1_TIMEOUT_SEC", "180"))

    if provider == PROVIDER_DEEPSEEK:
        base = os.environ.get("R1_BASE_URL", DEFAULT_DEEPSEEK_BASE).strip()
        model = os.environ.get("R1_MODEL", DEFAULT_DEEPSEEK_MODEL).strip()
    elif provider == PROVIDER_CUSTOM:
        base = os.environ.get("R1_BASE_URL", "").strip()
        if not base:
            raise ValueError("R1_BASE_URL required when R1_PROVIDER=custom")
        model = os.environ.get("R1_MODEL", DEFAULT_OPENROUTER_MODEL).strip()
    else:
        provider = PROVIDER_OPENROUTER
        base = os.environ.get("R1_BASE_URL", DEFAULT_OPENROUTER_BASE).strip()
        model = os.environ.get("R1_MODEL", DEFAULT_OPENROUTER_MODEL).strip()

    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"

    return CloudR1Config(
        provider=provider,
        base_url=base,
        model=model,
        api_key=api_key,
        timeout_sec=timeout,
        site_url=os.environ.get("R1_SITE_URL", "").strip() or None,
        site_name=os.environ.get("R1_SITE_NAME", "HexStrike").strip() or None,
    )


def strip_r1_thinking(text: str) -> str:
    """Remove DeepSeek R1 thinking blocks from model output."""
    cleaned = _THINKING_RE.sub("", text).strip()
    return cleaned


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse JSON plan from R1 response (handles markdown fences and thinking tags)."""
    cleaned = strip_r1_thinking(text)
    match = _JSON_BLOCK_RE.search(cleaned)
    if match:
        return json.loads(match.group(1))
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ValueError(f"No JSON object found in model response: {cleaned[:200]}...")


class CloudR1Provider:
    """OpenAI-compatible client for cloud DeepSeek R1 reasoning."""

    def __init__(self, config: CloudR1Config | None = None) -> None:
        self.config = config or resolve_cloud_r1_config()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.provider == PROVIDER_OPENROUTER:
            if self.config.site_url:
                headers["HTTP-Referer"] = self.config.site_url
            if self.config.site_name:
                headers["X-Title"] = self.config.site_name
        return headers

    def status(self) -> dict[str, Any]:
        reachable = False
        models: list[str] = []
        if self.config.api_key:
            url = f"{self.config.base_url.rstrip('/')}/models"
            req = urllib.request.Request(url, headers=self._headers(), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    payload = json.loads(resp.read().decode())
                    reachable = 200 <= resp.status < 300
                    data = payload.get("data") or []
                    models = [m.get("id", "") for m in data if isinstance(m, dict)]
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, urllib.error.HTTPError):
                reachable = False
        return {
            "provider": self.config.provider,
            "base_url": self.config.base_url,
            "model": self.config.model,
            "authenticated": bool(self.config.api_key),
            "reachable": reachable,
            "models_sample": models[:10],
            "timeout_sec": self.config.timeout_sec,
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """POST /v1/chat/completions to cloud R1."""
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        body_obj: dict[str, Any] = {
            "model": model or self.config.model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body_obj["max_tokens"] = max_tokens

        body = json.dumps(body_obj).encode()
        req = urllib.request.Request(url, data=body, headers=self._headers(), method="POST")
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_sec) as resp:
                payload = json.loads(resp.read().decode())
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            content = ""
            reasoning = ""
            choices = payload.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
            return {
                "ok": True,
                "content": content,
                "reasoning_content": reasoning,
                "raw": payload,
                "latency_ms": elapsed_ms,
                "url": url,
                "provider": self.config.provider,
            }
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode(errors="replace")
            return {"ok": False, "error": detail[:400], "status": exc.code, "url": url}
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc), "url": url}

    def handshake(self) -> dict[str, Any]:
        """Status + minimal chat ping."""
        st = self.status()
        ping = self.chat(
            [{"role": "user", "content": "Reply with exactly: R1_OK"}],
            temperature=0.0,
            max_tokens=32,
        )
        return {"r1": st, "ping": ping}
