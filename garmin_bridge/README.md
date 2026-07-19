# garmin_bridge

Companion service for the a2zwarehouse platform. Pulls health/fitness data from
Garmin (and other wearables via an aggregator) and correlates it with LoRa
sensor data from the `lora_gateway`-based network.

## Architecture

```
Garmin watch → Garmin Connect cloud ─┐
                                     │ webhooks (PING) + REST
Fitbit/Oura/Apple ─→ Terra API ──────┤
                                     ▼
                            ┌─────────────────┐
                            │  garmin_bridge  │  (FastAPI, this repo)
                            └────────┬────────┘
                                     │
                            ┌────────▼────────┐
                            │ Postgres +      │
                            │ TimescaleDB     │
                            └────────┬────────┘
                                     │
LoRa devices → packet_forwarder → ChirpStack → app webhook ┘
```

## Providers

`app/providers/` implements a common `Provider` interface with two concrete
adapters:

- **`terra`** — via [Terra API](https://tryterra.co). Self-serve signup, works
  today. Use this while the direct Garmin approval is pending.
- **`garmin`** — direct Garmin Health API (OAuth 1.0a). Stubbed; enable once
  consumer key/secret arrive from `developer.garmin.com`.

Swap providers with `WEARABLE_PROVIDER=terra|garmin` in `.env`. Ingested data
lands in the same schema regardless of source.

## Layout

```
garmin_bridge/
├── app/
│   ├── main.py              FastAPI entrypoint
│   ├── config.py            Pydantic settings
│   ├── db.py                async SQLAlchemy engine + session
│   ├── models.py            ORM models (users, tokens, timeseries)
│   ├── schemas.py           Pydantic request/response models
│   ├── providers/
│   │   ├── base.py          Provider interface
│   │   ├── terra.py         Terra adapter
│   │   └── garmin.py        Direct Garmin OAuth1 adapter
│   ├── routers/
│   │   ├── oauth.py         Connect/callback/disconnect
│   │   ├── webhooks.py      PING receivers
│   │   ├── health.py        Liveness/readiness
│   │   └── dashboard.py     Minimal HTMX dashboard
│   ├── fetchers.py          Background upsert workers
│   ├── correlator.py        Time-window Garmin × LoRa joins
│   └── alerts.py            Rule engine + notifier stubs
├── alembic/                 DB migrations
├── systemd/                 VPS deploy unit
├── docker-compose.yml       Local dev (postgres+timescale+app)
├── pyproject.toml
└── .env.example
```

## Local dev

```bash
cp .env.example .env
docker compose up -d db
uv sync            # or: pip install -e .
alembic upgrade head
uvicorn app.main:app --reload
```

Expose the dev server to the internet (for provider webhooks) with:

```bash
ngrok http 8000
# then set PUBLIC_BASE_URL=https://<subdomain>.ngrok.app in .env
```

Register the ngrok URL as your Terra/Garmin webhook endpoint in their portal.

## Production (a2zwarehouse VPS)

The `systemd/garmin-bridge.service` unit runs uvicorn behind whatever reverse
proxy is already fronting the VPS (Caddy/nginx). See that file's comments for
socket + user setup.

## Status

Scaffolded, not wired to live credentials. Fill in:

1. `TERRA_DEV_ID` / `TERRA_API_KEY` in `.env` (Terra dashboard signup is free).
2. `GARMIN_CONSUMER_KEY` / `GARMIN_CONSUMER_SECRET` once developer.garmin.com
   approves the application.
3. `PUBLIC_BASE_URL` — publicly reachable HTTPS URL of this service.
4. `DATABASE_URL` — Postgres with TimescaleDB extension enabled.

Then run migrations and start the service.
