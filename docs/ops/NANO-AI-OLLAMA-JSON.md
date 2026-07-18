# Nano AI + Ollama — JSON Parse Error (Unexpected character: E)

## Cause

Nano AI (OpenAI-compatible) expects a JSON body starting with `{`.  
If the server returns plain text such as `Error: model "deepseek-v4-flash" not found...`, the parser fails on the first character `E`.

## Correct client settings

| Field | Value |
| --- | --- |
| Base URL | `http://<mac-ip>:11434/v1` |
| API Key | `ollama` |
| Model | `qwen2.5-coder:7b` (local tag) |

Config file: [config/nano-ai-ollama.json](../../config/nano-ai-ollama.json)

## Wrong settings (common)

- Base URL = `.../api/generate` or `.../api/chat`
- Model = `deepseek-v4-flash` / `deepseek-v4-pro` (official API / OpenRouter ids, **not** local Ollama)
- Base URL = `127.0.0.1` from iPhone (points at the phone, not the Mac)

## Verify on Mac

```bash
bash scripts/verify-openai-v1-json.sh
# or with explicit model:
OLLAMA_MODEL=qwen2.5-coder:7b bash scripts/verify-openai-v1-json.sh
```

Pull if missing:

```bash
ollama pull qwen2.5-coder:7b
```

## HexStrike terminal (same stack)

```bash
./hexstrike-go.sh
# default chat model is now qwen2.5-coder:7b
```
