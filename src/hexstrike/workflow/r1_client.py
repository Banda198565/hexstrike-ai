"""Minimal OpenAI-compatible client for skill-builder R1 calls."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

_THINKING_RE = re.compile(r"<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>", re.IGNORECASE)


@dataclass(frozen=True)
class R1Config:
    base_url: str
    model: str
    api_key: str | None
    timeout_sec: float = 180.0


def resolve_r1_config() -> R1Config:
    env_path = _REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

    provider = os.environ.get("R1_PROVIDER", "openrouter").lower()
    if provider == "deepseek":
        base = os.environ.get("R1_BASE_URL", "https://api.deepseek.com/v1")
        model = os.environ.get("R1_MODEL", "deepseek-reasoner")
    else:
        base = os.environ.get("R1_BASE_URL", "https://openrouter.ai/api/v1")
        model = os.environ.get("R1_MODEL", "deepseek/deepseek-r1:free")

    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"

    api_key = (
        os.environ.get("R1_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
    )
    return R1Config(
        base_url=base,
        model=model,
        api_key=api_key,
        timeout_sec=float(os.environ.get("R1_TIMEOUT_SEC", "180")),
    )


def strip_thinking(text: str) -> str:
    return _THINKING_RE.sub("", text).strip()


def extract_json(text: str) -> dict:
    cleaned = strip_thinking(text)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object in R1 response")
    return json.loads(cleaned[start : end + 1])


class R1Client:
    def __init__(self, config: R1Config | None = None) -> None:
        self.config = config or resolve_r1_config()

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.2) -> dict:
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        body = json.dumps(
            {
                "model": self.config.model,
                "messages": messages,
                "stream": False,
                "temperature": temperature,
            }
        ).encode()
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_sec) as resp:
                payload = json.loads(resp.read().decode())
            content = (payload.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            return {"ok": True, "content": content, "raw": payload}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": exc.read(400).decode(errors="replace"), "status": exc.code}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
