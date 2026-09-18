# Web interface

A small [FastHTML](https://fastht.ml) app that stores hourly prices in an existing PostgreSQL database.

Run from the repository root. API code stays in `script/`. This app lives in `web/`.

## Layout

| Path | Role |
| --- | --- |
| `web/app.py` | FastHTML routes and pages |
| `web/db.py` | PostgreSQL schema and queries |
| `web/ingest.py` | Pulls APIs into the tables |
| `web/__main__.py` | `python -m web` |
| `Dockerfile` / `docker-compose.yml` | Unraid / Docker deploy |
| `.env.example` | Environment template |

## Environment

Copy `.env.example` to `.env` (gitignored). Required:

- `PRISKLASSE` — `DK1` or `DK2`
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`

PostgreSQL is **not** started by compose. Point the variables at the server you already run. On the shared Unraid `home` network that host is usually `homepostgresql-db`.

On startup the app creates schema `elprisenligenu` and these tables:

- `elprisenligenu.hours` — one row per hour, with the four (plus optional supplier) kWh parts and totals
- `elprisenligenu.days` / `months` / `years` — averages for browsing
- `elprisenligenu.settings` — UI overrides for supplier tillæg and netselskab

## Get data

- **Day**: pulls that day’s spot file and the Datahub charges valid on that date.
- If the day is already stored, the UI asks whether to pull again.
- **Month** / **Year**: pull each missing (or all, if confirmed) calendar days the spot API still has.

## Charges / settings

`/settings` shows the looked-up staten, Energinet, and Radius values for today, and lets you set Andel Energi’s kWh tillæg. That tillæg is not published in Datahub, so it is a variable.

## Run locally

```bash
cp .env.example .env
# fill in PRISKLASSE and Postgres settings
python -m web
```

Open http://127.0.0.1:8088

## Docker / Unraid

Unraid steps are in [deploy.md](deploy.md).

```bash
docker compose up -d --build
```

The container listens on port `8088`.
