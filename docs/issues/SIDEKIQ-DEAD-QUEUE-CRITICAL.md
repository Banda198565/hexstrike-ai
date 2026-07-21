# Sidekiq Dead Queue — Critical

**Target:** `http://38.107.234.149:3000/sidekiq/stats`  
**Checked (issue):** 2026-07-21 18:35:58 UTC  
**Re-checked (agent, read-only):** 2026-07-21 18:42:07 UTC  
**Status:** root cause confirmed — waiting on SSH to `38.107.234.149` for fix/replay/UI lockdown  

---

## Проблема

457 dead задач из 458 failed — **99.8%** ошибок ушли в dead; live `retries` = 0.

Live snapshot (18:42 UTC): **dead=459 / failed=460**, `processes=1`, `retries=0`, `default_latency=0`  
(на issue latency был 36.6с; на `low_priority` backlog ~828с).

App: **Lago API** (`gid://lago-api/...`, cookie `_lago_production`).

---

## Детали

| Метрика | Issue 18:35 | Live 18:42 | Норма |
|---------|-------------|------------|-------|
| processed | 167,343 | 168,727 | — |
| failed | 458 | 460 | < 1% |
| **dead** | **457** | **459** | **~0** |
| retries | 0 | 0 | > 0 если есть активные retry |
| busy | 10 | 10 | — |
| enqueued | 178 | 23 | — |
| processes | 1 | 1 | ≥ 2 для HA |
| default_latency | **36.6 сек** | 0 | < 1 сек |

---

## ROOT CAUSE (подтверждено)

DNS не резолвит хост **`pdf`** → TCP на `pdf:3000` падает → PDF-джобы Lago в dead.

100% выборки morgue (175 jobs):

| Job | Queue | Count | Error |
|-----|-------|------:|-------|
| `Invoices::GeneratePdfAndNotifyJob` | `invoices` | 90 | `Socket::ResolutionError` → `pdf:3000` |
| `PaymentReceipts::GeneratePdfAndNotifyJob` | `low_priority` | 85 | `Socket::ResolutionError` → `pdf:3000` |

```
Socket::ResolutionError: Failed to open TCP connection to pdf:3000
(getaddrinfo(3): Temporary failure in name resolution)
```

На detail page есть **Last Retry** → retries не «выключены навсегда»; при постоянном DNS fail попытки сгорают → morgue → live `retries=0`.

---

## Гипотезы — вердикт

| # | Гипотеза | Вердикт |
|---|----------|---------|
| 1 | `sidekiq_retries = 0` | Маловероятно как root cause (есть Last Retry) |
| 2 | Middleware → dead напрямую | Не подтверждено |
| 3 | 1 процесс / latency | Усугубляет backlog; первопричина — PDF DNS |
| 4 | Dead nobody processes | Норма; replay только после фикса `pdf` |

---

## Checklist

- [x] Проанализировать last error (morgue read-only)
- [x] Зафиксировать job/error classes
- [x] Задокументировать runbook фикса + replay + UI lockdown
- [ ] SSH на `38.107.234.149`
- [ ] Поднять / починить сервис `pdf:3000` в Docker network Sidekiq
- [ ] Verify: `getent hosts pdf` + `curl http://pdf:3000`
- [ ] Replay dead (не clear вслепую)
- [ ] Закрыть Sidekiq UI (basic auth / IP allowlist / internal-only)
- [ ] (опц.) 2+ Sidekiq process + `sidekiq_alive`
- [ ] (опц.) проверить `sidekiq_options retry:` в коде Lago

---

## Runbook A — починить `pdf` (нужен SSH)

Порядок важен: **сначала DNS/сервис, потом replay**.

```bash
# 1) где крутится Lago / compose
cd /path/to/lago   # или docker compose ls
docker compose ps
docker compose ps | grep -iE 'pdf|gotenberg|api|sidekiq' || true

# 2) резолв из сети воркера (имя сервиса должно быть pdf)
SID=$(docker compose ps -q sidekiq 2>/dev/null || docker ps -qf name=sidekiq | head -1)
docker exec "$SID" getent hosts pdf || docker exec "$SID" nslookup pdf
docker exec "$SID" curl -sv --max-time 5 http://pdf:3000/ || true

# 3) если контейнера pdf нет / Exited — поднять
docker compose up -d pdf
# убедиться, что pdf и sidekiq в ОДНОЙ docker network:
docker network inspect $(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$SID") \
  | grep -E 'Name|pdf|sidekiq' || true

# 4) health с хоста (если порт проброшен) или только из network
docker compose logs --tail=100 pdf
```

Критерий готовности: из контейнера Sidekiq  
`getent hosts pdf` → IP, и `curl -f http://pdf:3000/` → не connection/DNS error.

---

## Runbook B — replay dead (только после A)

```bash
# rails runner / sidekiq-friendly console на api/sidekiq host
bundle exec rails runner '
dead = Sidekiq::DeadSet.new
puts "dead=#{dead.size}"
pdf_related = dead.select { |j|
  j.item["error_message"].to_s.include?("pdf:3000") ||
    %w[Invoices::GeneratePdfAndNotifyJob PaymentReceipts::GeneratePdfAndNotifyJob].include?(j.klass)
}
puts "pdf_related=#{pdf_related.size}"
pdf_related.each(&:retry)
puts "retried=#{pdf_related.size} remaining_dead=#{Sidekiq::DeadSet.new.size}"
'
```

Проверка:

```bash
curl -sS http://127.0.0.1:3000/sidekiq/stats   # только с localhost после lockdown
# dead ↓, retries/enqueued ↑ кратко, затем processed ↑
# в morgue не должно снова сыпаться Socket::ResolutionError → pdf:3000
```

**Не делать до фикса PDF:** `Sidekiq::DeadSet.new.clear` — сожжёт историю без восстановления PDF.

---

## Runbook C — закрыть Sidekiq UI (сейчас без auth на `:3000`)

Сейчас UI отдаёт 200 на `/sidekiq`, `/sidekiq/stats`, `/sidekiq/morgue` **из интернета**. Это критичный риск (очередь, payload GID, retry/delete).

Выбрать один вариант (можно комбинировать).

### C1. Nginx Basic Auth + только внутренние IP (предпочтительно)

```nginx
# /etc/nginx/sites-available/lago-sidekiq-guard.conf
# Sidekiq не должен торчать наружу на :3000 напрямую.
# Проксируйте /sidekiq только через nginx :443 с auth.

upstream lago_app {
  server 127.0.0.1:3000;
}

server {
  listen 443 ssl http2;
  server_name lago.example.com;

  # ssl_certificate ...;
  # ssl_certificate_key ...;

  # остальное API — по вашей схеме
  location / {
    proxy_pass http://lago_app;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }

  location /sidekiq {
    # IP allowlist (office / bastion / VPN)
    allow 10.0.0.0/8;
    allow 192.168.0.0/16;
    allow 127.0.0.1;
    deny all;

    auth_basic "Sidekiq";
    auth_basic_user_file /etc/nginx/.htpasswd-sidekiq;

    proxy_pass http://lago_app;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

```bash
sudo htpasswd -c /etc/nginx/.htpasswd-sidekiq sidekiqadmin
sudo nginx -t && sudo systemctl reload nginx

# закрыть прямой доступ к app :3000 снаружи
sudo ufw deny 3000/tcp || sudo iptables -A INPUT -p tcp --dport 3000 ! -s 127.0.0.1 -j DROP
# если Docker publish 0.0.0.0:3000 — сменить на 127.0.0.1:3000:3000 в compose
```

### C2. Только Docker internal (без publish Sidekiq/UI порта)

В `docker-compose.yml` для api/web:

```yaml
ports:
  - "127.0.0.1:3000:3000"   # было "3000:3000" / "0.0.0.0:3000:3000"
```

Доступ снаружи — только через VPN/bastion + SSH tunnel:

```bash
ssh -L 3000:127.0.0.1:3000 user@38.107.234.149
# затем https://localhost:3000/sidekiq  (или http)
```

### C3. Sidekiq Web constraint в Rails (доп. слой)

```ruby
# config/routes.rb — пример
require "sidekiq/web"
Sidekiq::Web.use Rack::Auth::Basic do |user, pass|
  ActiveSupport::SecurityUtils.secure_compare(user, ENV.fetch("SIDEKIQ_USER")) &
    ActiveSupport::SecurityUtils.secure_compare(pass, ENV.fetch("SIDEKIQ_PASSWORD"))
end
mount Sidekiq::Web => "/sidekiq"
```

Критерий готовности: с внешней сети  
`curl -sS -o /dev/null -w '%{http_code}\n' http://38.107.234.149:3000/sidekiq/stats` → **не 200** (timeout / 401 / connection refused).

---

## Команды диагностики (read-only, уже использовались)

```bash
curl -sS http://38.107.234.149:3000/sidekiq/stats | python3 -m json.tool
# morgue: Invoices:: / PaymentReceipts:: + Socket::ResolutionError pdf:3000
```

---

## Артефакт

Read-only live dump: `artifacts/sidekiq-dead-queue/stats-live-2026-07-21T1842Z.json` (локально; `artifacts/` в `.gitignore`).
