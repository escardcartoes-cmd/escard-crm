# Krylo CRM — Backend

Flask + SQLite/PostgreSQL API that powers the [Krylo Next.js frontend](https://github.com/escardcartoes-cmd/krylo-crm-next).

Production: <https://web-production-7599a.up.railway.app> (Railway)

## Stack

- Python 3.11 · Flask 3 · Flask-Login · Flask-Limiter · Flask-CORS · Flask-WTF (CSRF)
- SQLite (dev) · PostgreSQL (prod via `DATABASE_URL`)
- Anthropic SDK (Claude Sonnet 4.6) for the Central IA
- Brevo (email + WhatsApp templating)
- APScheduler for cadence dispatch

## Quick start (local)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # edit values
python app.py             # boots on :5001 with livereload
```

## Environment

Copy `.env.example` and fill in:

| Var | Purpose | Required |
|---|---|---|
| `SECRET_KEY` | Flask session signing (32+ bytes) | **prod: yes** |
| `DATABASE_URL` | Postgres URL. Empty = SQLite file `escard.db` | prod: yes |
| `ANTHROPIC_API_KEY` | Central IA | for IA features |
| `BREVO_API_KEY` | Email + WhatsApp templates | for cadence |
| `CRON_TOKEN` | Guards `/cron/*` cadence trigger | for scheduler |
| `BREVO_WEBHOOK_SECRET` | Verifies inbound Brevo webhooks | for tracking |
| `KRYLO_WHATSAPP` | Sender number (E.164 no `+`) | optional |
| `EMAIL_ONBOARDING` | Reply-to for outbound cadence | optional |
| `BASE_URL` / `APP_URL` | Absolute URL for webhook callbacks | prod |
| `SCHEDULER_OFF` | Set `1` to disable APScheduler (tests, dev) | optional |
| `CORS_EXTRA_ORIGINS` | Comma-separated extra origins | optional |

Prod flags (`RAILWAY_ENVIRONMENT`, `VERCEL`, or `PRODUCTION`) tighten cookies + refuse to boot without `SECRET_KEY`.

## Tests

```bash
pytest tests/ -v
```

Coverage: auth flow, empresas CRUD, security headers, CORS, rate-limit gating.

## Deploy

Railway auto-deploys on push to `master`. CI (`.github/workflows/ci.yml`) blocks the deploy workflow on:

- `ruff check`, `compileall`, boot check, `pytest`, `pip-audit`, `bandit`, `trufflehog`

Manual deploy: `railway up --service escard-crm --detach` (needs `RAILWAY_TOKEN`).

## Layout

```
app.py               boot, security config, blueprints, scheduler
database.py          connection pool + schema init (SQLite + PG)
routes/
  api.py             REST API consumed by Next.js frontend
  auth.py            legacy Jinja login page
  empresas.py        legacy Jinja UI
  contatos.py        legacy Jinja UI
  sdr_evolutivo.py   legacy Jinja UI
models/              business logic + persistence (per resource)
templates/           legacy Jinja templates (frontend now lives in Next.js)
```

The `api_bp` blueprint (mounted at `/api`) is the only surface used by production. Everything under `routes/{auth,empresas,contatos,sdr_evolutivo}.py` + `templates/**` is legacy and slated for removal.

## Security posture

- Session cookies: `HttpOnly`, `SameSite=Lax`, `Secure` in prod
- CSRF via Flask-WTF on Jinja routes (API blueprint is exempt — protected by SameSite + CORS allowlist)
- Rate limits: global 300/h, login 10/min, IA 60/h, imports 20/h
- Response headers: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` (no geo/mic/cam), HSTS in prod
- Password hashing: bcrypt (cost 12)
- Bruteforce lockout: 5 failed attempts → 15 min lockout (per user)
- SQL: parametrized only. No string interpolation in queries.

## License

Proprietary — Escard Cartões.
