# Cloud Agent — transport-only и permissions

Как ограничения из PR #71 применяются к **Cloud Agent** (`cursor.com/agents/bc-…`) vs **локальный IDE/CLI**.

---

## Важно: ветка и checkout

Cloud Agent читает `.cursor/` **из ветки, на которой запущен run**, не из «логической ссылки» на агента.

| Run | Branch (пример) | `.cursor/cli.json` |
|-----|-----------------|-------------------|
| R1 облачный бэкенд `bc-019f7688-…` | `cursor/cloud-r1-reasoning-agent-7b69` | **нет** (до merge/cherry-pick) |
| Web3 audit agent | `cursor/web3-audit-mcp-7b69` (PR #71) | **есть** |

**Действие:** merge PR #71 → `master`, либо cherry-pick transport-коммиты на ветку Cloud Agent, либо перезапустить run с base branch `master` после merge.

---

## Что применяется где (матрица)

| Конфиг | Cursor IDE Agent | Cursor CLI (`cursor agent`) | Cloud Agent (VM) |
|--------|------------------|----------------------------|------------------|
| `.cursor/rules/*.mdc` | да (alwaysApply) | да | **да** — основной рычаг для Cloud |
| `.cursor/cli.json` `Shell(*)` deny | частично / CLI-first | **да** — enforcement | **может не блокировать** platform Shell tool |
| `.cursor/permissions.json` | да (auto-run IDE) | отдельно от CLI | ограниченно |
| `.cursor/mcp.json` | да | да | да (если MCP подключены в run) |
| `.cursor/settings.json` autoApply | да | n/a | зависит от run mode |

**Вывод:** для Cloud Agent критичны **rules** (`transport-only.mdc`, `shell-policy.mdc`) + **промпт run** + **gated MCP**. `cli.json` — обязателен для CLI; для Cloud — страховка после merge, но не единственная.

---

## Рекомендуемый промпт при старте Cloud run

```
Transport-only. R1 = planner. No file edits, no shell, no git unless I say implement/run/commit.
Follow .cursor/rules/transport-only.mdc and shell-policy.mdc.
Use gated-orchestrator MCP only for RPC reads and fs_create_report_file.
```

---

## Проверка конфигов в checkout (без shell)

```bash
python3 scripts/verify-transport-config.py
```

Ожидается: все checks PASS на ветке с PR #71.

---

## Если Cloud Agent всё ещё запускает shell

1. **Проверьте ветку run** — `git branch --show-current` в VM / в UI run settings.
2. **Убедитесь, что `.cursor/cli.json` в checkout:**
   ```bash
   test -f .cursor/cli.json && grep -q 'Shell(\*)' .cursor/cli.json && echo OK
   ```
3. **Rules:** в run должны подхватываться `.cursor/rules/transport-only.mdc` и `shell-policy.mdc` (alwaysApply).
4. **Run mode:** Cloud Agent по умолчанию Agent (не Ask) — может иметь platform Shell. Rules + явный промпт + merge конфигов; для жёсткого CLI-style deny используйте локальный `cursor agent` с project `cli.json`.
5. **Глобально (опционально):**
   ```bash
   cp config/cursor-cli-config.example.json ~/.cursor/cli-config.json
   ```
   Проектный `.cursor/cli.json` перекрывает global.

---

## MCP и subagents

- Subagents наследуют **rules** из repo, не отдельный `cursor-agent.json`.
- MCP: только серверы из `.cursor/mcp.json`; для transport — **`gated-orchestrator`** first.
- Нет отдельного `cursor-agent.json` в HexStrike — source of truth: `.cursor/agents/*.md` + `.cursor/rules/`.

---

## Связанные файлы

| File | Purpose |
|------|---------|
| `config/cursor-transport-mode.md` | Полный рецепт Ask + cli.json + rules |
| `.cursor/cli.json` | Shell(*) deny (project) |
| `.cursor/permissions.json` | IDE terminalAllowlist: [] |
| `.cursor/rules/shell-policy.mdc` | Поведение shell |
| `.cursor/rules/transport-only.mdc` | Transport hard block |
| `config/cursor-cli-config.example.json` | Global template |

PR: #71 → merge в `master` для всех веток Cloud Agent на default base.
