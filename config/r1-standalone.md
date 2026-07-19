# DeepSeek R1 — standalone (без Cursor)

Облачный **DeepSeek R1** как plan-only backend для HexStrike. **Никакой привязки к Cursor IDE**, `.cursor/rules`, Cloud Agent или MCP транспорту.

---

## Стек

```
.env / export R1_*
       ↓
src/hexstrike/llm/cloud_r1.py
       ↓
src/hexstrike/llm/reasoning.py  (JSON plan only)
       ↓
hexstrike_orchestrator.py reasoning plan
       ↓
Worker dispatch (отдельно, вне R1)
```

| Компонент | Путь |
|-----------|------|
| Provider | `src/hexstrike/llm/cloud_r1.py` |
| Reasoning agent | `src/hexstrike/llm/reasoning.py` |
| System prompt | `config/reasoning-system-prompt.md` |
| Task example | `config/reasoning-protocol.example.json` |
| Connect | `scripts/connect-r1.sh` |
| Verify | `scripts/verify-r1-deepseek.py` |

**Ветка:** `cursor/r1-deepseek-standalone-7b69` — только R1, без transport/cli.json/gated MCP.

---

## Быстрый старт

### 1. Ключ

DeepSeek official:

```bash
export R1_PROVIDER=deepseek
export R1_API_KEY=sk-...          # https://platform.deepseek.com/api_keys
export R1_MODEL=deepseek-reasoner
export R1_BASE_URL=https://api.deepseek.com/v1
```

OpenRouter (free tier):

```bash
export R1_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-...
export R1_MODEL=deepseek/deepseek-r1:free
```

### 2. Проверка

```bash
python3 scripts/verify-r1-deepseek.py
bash scripts/connect-r1.sh --handshake
```

### 3. Mission plan (JSON only)

```bash
python3 hexstrike_orchestrator.py reasoning plan config/reasoning-protocol.example.json
# или
bash scripts/connect-r1.sh --plan config/reasoning-protocol.example.json
```

R1 **не выполняет** команды — только план JSON.

---

## Где запускать

| Среда | Как |
|-------|-----|
| Mac / Linux terminal | `.env` + команды выше |
| VPS | systemd / cron + `.env` |
| Docker | env vars в compose |
| Любой CI | secrets → `verify-r1-deepseek.py` |

**Не требуется:** Cursor, Zed, `.cursor/mcp.json`, Cloud Agent URL.

---

## Отличие от ветки web3-audit / PR #71

| | **r1-deepseek-standalone** | **web3-audit-mcp** |
|--|---------------------------|---------------------|
| Cursor rules/cli.json | нет | да |
| Gated MCP | нет | да |
| R1 cloud_r1 + reasoning CLI | **да** | частично / другой r1_client |

Две ветки **не мержить** в одну логику Cursor — R1 standalone живёт отдельно.

---

## Troubleshooting

| Симптом | Fix |
|---------|-----|
| `authenticated=false` | Проверьте `R1_API_KEY` |
| HTTP 401 | Неверный ключ или provider |
| Timeout | `R1_TIMEOUT_SEC=300` |
| Invalid JSON from R1 | Повторите plan; модель иногда шлёт prose — reasoning.py strip thinking |
