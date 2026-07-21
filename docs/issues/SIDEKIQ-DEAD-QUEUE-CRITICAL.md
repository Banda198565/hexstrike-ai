# Sidekiq Dead Queue — Critical

**Target:** `http://38.107.234.149:3000/sidekiq/stats`  
**Checked (issue):** 2026-07-21 18:35:58 UTC  
**Re-checked (agent, read-only):** 2026-07-21 18:42:07 UTC  

---

## Проблема

457 dead задач из 458 failed — **99.8%** ошибок ушли в dead; live `retries` = 0.

Live snapshot (18:42 UTC): **dead=459 / failed=460**, `processes=1`, `retries=0`, `default_latency=0` (latency на issue был 36.6с; сейчас backlog на `low_priority` ~828с).

---

## Детали

| Метрика | Issue 18:35 | Live 18:42 | Норма |
|---------|-------------|------------|-------|
| processed | 167,343 | 168,727 | — |
| failed | 458 | 460 | < 1% |
| **dead** | **457** | **459** | **~0** |
| retries | 0 | 0 | > 0 (если есть активные retry) |
| busy | 10 | 10 | — |
| enqueued | 178 | 23 | — |
| processes | 1 | 1 | ≥ 2 для HA |
| default_latency | **36.6 сек** | 0 | < 1 сек |

App fingerprint: **Lago API** (`gid://lago-api/...`).

---

## ROOT CAUSE (подтверждено)

**Не middleware Skip и не «retries выключены как единственная причина».**

100% выборки dead (175 jobs с morgue pages):

| Job | Queue | Count | Error |
|-----|-------|------:|-------|
| `Invoices::GeneratePdfAndNotifyJob` | `invoices` | 90 | `Socket::ResolutionError` → `pdf:3000` |
| `PaymentReceipts::GeneratePdfAndNotifyJob` | `low_priority` | 85 | `Socket::ResolutionError` → `pdf:3000` |

```
Socket::ResolutionError: Failed to open TCP connection to pdf:3000
(getaddrinfo(3): Temporary failure in name resolution)
```

Хост **`pdf`** не резолвится в сети воркеров (Docker DNS / сервис PDF down / wrong compose network). PDF-джобы падают → уходят в dead → `retries` set пустой (0).

На detail page есть **Last Retry** — значит retries не «всегда 0 навсегда»; при постоянном DNS fail попытки сгорают и job оказывается в morgue.

---

## Гипотезы — вердикт

| # | Гипотеза | Вердикт |
|---|----------|---------|
| 1 | `sidekiq_retries = 0` | **Маловероятно как root cause** (есть Last Retry). Проверить в исходниках Lago всё равно стоит. |
| 2 | Кастомный middleware → dead | **Не подтверждено** — ошибка обычный DNS/TCP fail |
| 3 | 1 процесс / latency / timeout → dead | **Частично**: `processes=1`, latency на `low_priority` огромная, но **первопричина** — PDF service DNS |
| 4 | Nobody processes dead | Ожидаемо — dead не auto-retry; чистка/replay после фикса PDF |

---

## Что делать

- [x] Проанализировать last error у dead задач (morgue read-only)
- [x] Зафиксировать доминирующий error class / job class
- [ ] **Поднять / починить сервис `pdf:3000`** (DNS + health) в том же Docker network, что Sidekiq
- [ ] Проверить `sidekiq_options retry:` у `GeneratePdfAndNotifyJob` в коде Lago
- [ ] Проверить middleware на `Sidekiq::JobRetry::Skip` (низкий приоритет после DNS fix)
- [ ] Добавить **2+ process** Sidekiq для HA (после фикса PDF)
- [ ] Replay / clear dead **только после** восстановления `pdf` (не сейчас)
- [ ] Поставить `sidekiq_alive` / healthcheck на Queues
- [ ] **Security:** Sidekiq Web UI сейчас открыт без auth на `:3000` — закрыть Basic Auth / VPN / firewall

---

## Команды на хосте приложения (ops, не cloud-agent)

```ruby
# rails/sidekiq console — после фикса PDF
Sidekiq::DeadSet.new.each { |d| puts [d.klass, d.item["error_class"], d.item["error_message"]].inspect }

# НЕ выполнять до починки pdf:
# Sidekiq::DeadSet.new.clear
# Sidekiq::DeadSet.new.each(&:retry)
```

```bash
# на сервере / в compose
getent hosts pdf || true
curl -sv --max-time 3 http://pdf:3000/ || true
docker compose ps | grep -i pdf
```

---

## Артефакт

Read-only live dump: `artifacts/sidekiq-dead-queue/stats-live-2026-07-21T1842Z.json` (локально; `artifacts/` в `.gitignore`).
