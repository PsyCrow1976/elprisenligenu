"""PostgreSQL access for stored hourly electricity prices."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
import psycopg
from psycopg.rows import dict_row

from script.models import HourCost

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS elprisenligenu;

CREATE TABLE IF NOT EXISTS elprisenligenu.settings (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS elprisenligenu.hours (
    price_area text NOT NULL,
    period_start timestamptz NOT NULL,
    period_end timestamptz,
    local_date date NOT NULL,
    local_hour smallint NOT NULL,
    spot_dkk_kwh numeric(14, 6) NOT NULL,
    spot_eur_kwh numeric(14, 6),
    exr numeric(12, 6),
    staten_dkk_kwh numeric(14, 6) NOT NULL DEFAULT 0,
    energinet_dkk_kwh numeric(14, 6) NOT NULL DEFAULT 0,
    energinet_system_dkk_kwh numeric(14, 6) NOT NULL DEFAULT 0,
    energinet_transmission_dkk_kwh numeric(14, 6) NOT NULL DEFAULT 0,
    netselskab_dkk_kwh numeric(14, 6) NOT NULL DEFAULT 0,
    supplier_dkk_kwh numeric(14, 6) NOT NULL DEFAULT 0,
    total_ex_vat numeric(14, 6) NOT NULL,
    total_incl_vat numeric(14, 6) NOT NULL,
    vat_rate numeric(8, 4) NOT NULL DEFAULT 0.25,
    netselskab_name text,
    supplier_name text,
    scraped_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (price_area, period_start)
);

CREATE INDEX IF NOT EXISTS hours_local_date_idx
    ON elprisenligenu.hours (price_area, local_date);

CREATE TABLE IF NOT EXISTS elprisenligenu.days (
    price_area text NOT NULL,
    day date NOT NULL,
    hour_count integer NOT NULL,
    avg_total_incl_vat numeric(14, 6),
    min_total_incl_vat numeric(14, 6),
    max_total_incl_vat numeric(14, 6),
    scraped_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (price_area, day)
);

CREATE TABLE IF NOT EXISTS elprisenligenu.months (
    price_area text NOT NULL,
    year integer NOT NULL,
    month integer NOT NULL CHECK (month BETWEEN 1 AND 12),
    day_count integer NOT NULL,
    avg_total_incl_vat numeric(14, 6),
    scraped_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (price_area, year, month)
);

CREATE TABLE IF NOT EXISTS elprisenligenu.years (
    price_area text NOT NULL,
    year integer NOT NULL,
    month_count integer NOT NULL,
    avg_total_incl_vat numeric(14, 6),
    scraped_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (price_area, year)
);
"""


@dataclass
class HourRow:
    price_area: str
    period_start: datetime
    period_end: datetime | None
    local_date: date
    local_hour: int
    spot_dkk_kwh: Decimal
    spot_eur_kwh: Decimal | None
    exr: Decimal | None
    staten_dkk_kwh: Decimal
    energinet_dkk_kwh: Decimal
    energinet_system_dkk_kwh: Decimal
    energinet_transmission_dkk_kwh: Decimal
    netselskab_dkk_kwh: Decimal
    supplier_dkk_kwh: Decimal
    total_ex_vat: Decimal
    total_incl_vat: Decimal
    vat_rate: Decimal
    netselskab_name: str | None
    supplier_name: str | None
    scraped_at: datetime


@dataclass
class DayRow:
    price_area: str
    day: date
    hour_count: int
    avg_total_incl_vat: Decimal | None
    min_total_incl_vat: Decimal | None
    max_total_incl_vat: Decimal | None
    scraped_at: datetime


@dataclass
class MonthRow:
    price_area: str
    year: int
    month: int
    day_count: int
    avg_total_incl_vat: Decimal | None
    scraped_at: datetime


@dataclass
class YearRow:
    price_area: str
    year: int
    month_count: int
    avg_total_incl_vat: Decimal | None
    scraped_at: datetime


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        if default is not None:
            return default
        raise RuntimeError(f"{name} must be set.")
    return value


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=_env("POSTGRES_HOST"),
        port=int(_env("POSTGRES_PORT", "5432")),
        user=_env("POSTGRES_USER"),
        password=_env("POSTGRES_PASSWORD"),
        dbname=_env("POSTGRES_DB", "home"),
        row_factory=dict_row,
        connect_timeout=10,
    )


def ensure_schema() -> None:
    with connect() as conn:
        conn.execute(SCHEMA_SQL)
        conn.commit()


def get_setting(key: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM elprisenligenu.settings WHERE key = %s",
            (key,),
        ).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO elprisenligenu.settings (key, value, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            (key, value),
        )
        conn.commit()


def list_years(price_area: str) -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT year FROM (
                SELECT year FROM elprisenligenu.years WHERE price_area = %s
                UNION
                SELECT year FROM elprisenligenu.months WHERE price_area = %s
                UNION
                SELECT EXTRACT(YEAR FROM day)::int
                FROM elprisenligenu.days WHERE price_area = %s
                UNION
                SELECT EXTRACT(YEAR FROM local_date)::int
                FROM elprisenligenu.hours WHERE price_area = %s
            ) years
            ORDER BY year DESC
            """,
            (price_area, price_area, price_area, price_area),
        ).fetchall()
    return [int(row["year"]) for row in rows]


def get_year(price_area: str, year: int) -> YearRow | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT price_area, year, month_count, avg_total_incl_vat, scraped_at
            FROM elprisenligenu.years
            WHERE price_area = %s AND year = %s
            """,
            (price_area, year),
        ).fetchone()
    return _year_row(row) if row else None


def list_months(price_area: str, year: int) -> list[MonthRow]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT price_area, year, month, day_count, avg_total_incl_vat, scraped_at
            FROM elprisenligenu.months
            WHERE price_area = %s AND year = %s
            ORDER BY month
            """,
            (price_area, year),
        ).fetchall()
    stored = [_month_row(row) for row in rows]
    have = {item.month for item in stored}
    with connect() as conn:
        extra = conn.execute(
            """
            SELECT EXTRACT(MONTH FROM day)::int AS month,
                   COUNT(*) AS day_count,
                   AVG(avg_total_incl_vat) AS avg_total_incl_vat,
                   MAX(scraped_at) AS scraped_at
            FROM elprisenligenu.days
            WHERE price_area = %s AND EXTRACT(YEAR FROM day) = %s
            GROUP BY 1
            ORDER BY 1
            """,
            (price_area, year),
        ).fetchall()
    for row in extra:
        month = int(row["month"])
        if month in have:
            continue
        stored.append(
            MonthRow(
                price_area=price_area,
                year=year,
                month=month,
                day_count=int(row["day_count"]),
                avg_total_incl_vat=row["avg_total_incl_vat"],
                scraped_at=row["scraped_at"],
            )
        )
        have.add(month)
    stored.sort(key=lambda item: item.month)
    return stored


def get_month(price_area: str, year: int, month: int) -> MonthRow | None:
    months = [item for item in list_months(price_area, year) if item.month == month]
    return months[0] if months else None


def month_has_row(price_area: str, year: int, month: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM elprisenligenu.months
            WHERE price_area = %s AND year = %s AND month = %s
            """,
            (price_area, year, month),
        ).fetchone()
    return row is not None


def year_has_row(price_area: str, year: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM elprisenligenu.years
            WHERE price_area = %s AND year = %s
            """,
            (price_area, year),
        ).fetchone()
    return row is not None


def list_days(price_area: str, year: int, month: int) -> list[DayRow]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT price_area, day, hour_count, avg_total_incl_vat,
                   min_total_incl_vat, max_total_incl_vat, scraped_at
            FROM elprisenligenu.days
            WHERE price_area = %s
              AND EXTRACT(YEAR FROM day) = %s
              AND EXTRACT(MONTH FROM day) = %s
            ORDER BY day
            """,
            (price_area, year, month),
        ).fetchall()
    return [_day_row(row) for row in rows]


def get_day(price_area: str, day: date) -> DayRow | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT price_area, day, hour_count, avg_total_incl_vat,
                   min_total_incl_vat, max_total_incl_vat, scraped_at
            FROM elprisenligenu.days
            WHERE price_area = %s AND day = %s
            """,
            (price_area, day),
        ).fetchone()
    return _day_row(row) if row else None


def list_hours(price_area: str, day: date) -> list[HourRow]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT price_area, period_start, period_end, local_date, local_hour,
                   spot_dkk_kwh, spot_eur_kwh, exr, staten_dkk_kwh,
                   energinet_dkk_kwh, energinet_system_dkk_kwh,
                   energinet_transmission_dkk_kwh, netselskab_dkk_kwh,
                   supplier_dkk_kwh, total_ex_vat, total_incl_vat, vat_rate,
                   netselskab_name, supplier_name, scraped_at
            FROM elprisenligenu.hours
            WHERE price_area = %s AND local_date = %s
            ORDER BY period_start
            """,
            (price_area, day),
        ).fetchall()
    return [_hour_row(row) for row in rows]


def replace_day(price_area: str, day: date, hours: list[HourCost]) -> None:
    with connect() as conn:
        conn.execute(
            """
            DELETE FROM elprisenligenu.hours
            WHERE price_area = %s AND local_date = %s
            """,
            (price_area, day),
        )
        for hour in hours:
            conn.execute(
                """
                INSERT INTO elprisenligenu.hours (
                    price_area, period_start, period_end, local_date, local_hour,
                    spot_dkk_kwh, spot_eur_kwh, exr, staten_dkk_kwh,
                    energinet_dkk_kwh, energinet_system_dkk_kwh,
                    energinet_transmission_dkk_kwh, netselskab_dkk_kwh,
                    supplier_dkk_kwh, total_ex_vat, total_incl_vat, vat_rate,
                    netselskab_name, supplier_name, scraped_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
                )
                """,
                (
                    price_area,
                    hour.period_start,
                    hour.period_end,
                    hour.local_date,
                    hour.local_hour,
                    hour.spot_dkk_kwh,
                    hour.spot_eur_kwh,
                    hour.exr,
                    hour.staten_dkk_kwh,
                    hour.energinet_dkk_kwh,
                    hour.energinet_system_dkk_kwh,
                    hour.energinet_transmission_dkk_kwh,
                    hour.netselskab_dkk_kwh,
                    hour.supplier_dkk_kwh,
                    hour.total_ex_vat,
                    hour.total_incl_vat,
                    hour.vat_rate,
                    hour.netselskab_name,
                    hour.supplier_name,
                ),
            )
        _rollup_day(conn, price_area, day)
        conn.commit()


def _rollup_day(conn, price_area: str, day: date) -> None:
    conn.execute(
        """
        INSERT INTO elprisenligenu.days (
            price_area, day, hour_count, avg_total_incl_vat,
            min_total_incl_vat, max_total_incl_vat, scraped_at
        )
        SELECT
            price_area, local_date, COUNT(*), AVG(total_incl_vat),
            MIN(total_incl_vat), MAX(total_incl_vat), now()
        FROM elprisenligenu.hours
        WHERE price_area = %s AND local_date = %s
        GROUP BY price_area, local_date
        ON CONFLICT (price_area, day) DO UPDATE SET
            hour_count = EXCLUDED.hour_count,
            avg_total_incl_vat = EXCLUDED.avg_total_incl_vat,
            min_total_incl_vat = EXCLUDED.min_total_incl_vat,
            max_total_incl_vat = EXCLUDED.max_total_incl_vat,
            scraped_at = now()
        """,
        (price_area, day),
    )
    conn.execute(
        """
        INSERT INTO elprisenligenu.months (
            price_area, year, month, day_count, avg_total_incl_vat, scraped_at
        )
        SELECT
            price_area,
            EXTRACT(YEAR FROM day)::int,
            EXTRACT(MONTH FROM day)::int,
            COUNT(*),
            AVG(avg_total_incl_vat),
            now()
        FROM elprisenligenu.days
        WHERE price_area = %s
          AND EXTRACT(YEAR FROM day) = %s
          AND EXTRACT(MONTH FROM day) = %s
        GROUP BY 1, 2, 3
        ON CONFLICT (price_area, year, month) DO UPDATE SET
            day_count = EXCLUDED.day_count,
            avg_total_incl_vat = EXCLUDED.avg_total_incl_vat,
            scraped_at = now()
        """,
        (price_area, day.year, day.month),
    )
    conn.execute(
        """
        INSERT INTO elprisenligenu.years (
            price_area, year, month_count, avg_total_incl_vat, scraped_at
        )
        SELECT
            price_area,
            year,
            COUNT(*),
            AVG(avg_total_incl_vat),
            now()
        FROM elprisenligenu.months
        WHERE price_area = %s AND year = %s
        GROUP BY 1, 2
        ON CONFLICT (price_area, year) DO UPDATE SET
            month_count = EXCLUDED.month_count,
            avg_total_incl_vat = EXCLUDED.avg_total_incl_vat,
            scraped_at = now()
        """,
        (price_area, day.year),
    )


def _hour_row(row: dict[str, Any]) -> HourRow:
    return HourRow(**row)


def _day_row(row: dict[str, Any]) -> DayRow:
    return DayRow(**row)


def _month_row(row: dict[str, Any]) -> MonthRow:
    return MonthRow(
        price_area=row["price_area"],
        year=int(row["year"]),
        month=int(row["month"]),
        day_count=int(row["day_count"]),
        avg_total_incl_vat=row["avg_total_incl_vat"],
        scraped_at=row["scraped_at"],
    )


def _year_row(row: dict[str, Any]) -> YearRow:
    return YearRow(
        price_area=row["price_area"],
        year=int(row["year"]),
        month_count=int(row["month_count"]),
        avg_total_incl_vat=row["avg_total_incl_vat"],
        scraped_at=row["scraped_at"],
    )
