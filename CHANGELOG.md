# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.2] - 2026-09-18

### Added

- In-process 12-hour job that checks elprisenligenu.dk for today and tomorrow, then stores missing or updated hours in PostgreSQL.
- Each run is written to a log file and to `elprisenligenu.job_logs`. Enable/disable is kept in `elprisenligenu.job_state`.
- Jobs page at `/jobs` to start, stop, run now, and read the database log.

## [0.0.1] - 2026-09-18

### Added

- OOP Python package in `script/` for hourly Danish electricity prices.
- Spot prices from the open elprisenligenu.dk JSON API, selected with `PRISKLASSE` (`DK1` or `DK2`).
- Extra kWh costs from Energinet Datahub: staten (elafgift), Energinet (system + transmission), netselskab (Radius Nettarif C by default).
- Optional supplier tillæg (Andel Energi) as env / web settings, because it is not in Datahub.
- FastHTML web interface in `web/` that stores hours in PostgreSQL and lists years, months, days, and hours.
- Docker Compose deploy (existing Postgres on the `home` network, Unraid-friendly) documented in `deploy.md`.
