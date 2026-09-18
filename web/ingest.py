"""Pull spot prices and extra charges into PostgreSQL."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from script.client import PriceApi
from script.exceptions import ApiError, PriceError
from script.settings import Settings
from web import db

TIMEZONE = ZoneInfo("Europe/Copenhagen")

_api: PriceApi | None = None
_settings: Settings | None = None


@dataclass
class PullResult:
    status: str
    message: str
    location: str


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
        supplier = db.get_setting("supplier_dkk_kwh")
        if supplier not in (None, ""):
            _settings.supplier_dkk_kwh = Decimal(supplier.replace(",", "."))
        name = db.get_setting("supplier_name")
        if name:
            _settings.supplier_name = name
        gln = db.get_setting("netselskab_gln")
        if gln:
            _settings.netselskab_gln = gln
        nname = db.get_setting("netselskab_name")
        if nname:
            _settings.netselskab_name = nname
        code = db.get_setting("netselskab_charge_code")
        if code:
            _settings.netselskab_charge_code = code
    return _settings


def reload_settings() -> Settings:
    global _settings, _api
    _settings = None
    _api = None
    return settings()


def price_api() -> PriceApi:
    global _api
    if _api is None:
        _api = PriceApi(settings(), timezone=TIMEZONE)
    return _api


def price_area() -> str:
    return settings().price_area


def pull_day(day: date, *, replace: bool = False) -> PullResult:
    location = _day_path(day)
    area = price_area()
    existing = db.get_day(area, day)
    if existing is not None and not replace:
        return PullResult("exists", "already stored", f"{location}/confirm")
    hours = price_api().hours_for_day(day)
    if not hours:
        raise ApiError(f"No hourly prices returned for {day.isoformat()}.")
    db.replace_day(area, day, hours)
    cheapest = min(hours, key=lambda item: item.total_incl_vat)
    return PullResult(
        "ok",
        (
            f"Stored {day.isoformat()} ({area}): {len(hours)} hours. "
            f"Cheapest {cheapest.local_hour:02d}:00 at "
            f"{cheapest.total_incl_vat} kr/kWh inkl. moms."
        ),
        location,
    )


def pull_month(year: int, month: int, *, replace: bool = False) -> PullResult:
    location = f"/{year}/{month:02d}"
    area = price_area()
    if db.month_has_row(area, year, month) and not replace:
        return PullResult("exists", "already stored", f"{location}/confirm")
    last = calendar.monthrange(year, month)[1]
    stored = 0
    errors: list[str] = []
    for day_num in range(1, last + 1):
        day = date(year, month, day_num)
        if db.get_day(area, day) is not None and not replace:
            stored += 1
            continue
        try:
            hours = price_api().hours_for_day(day)
            db.replace_day(area, day, hours)
            stored += 1
        except PriceError as exc:
            errors.append(f"{day.isoformat()}: {exc}")
    if stored == 0:
        raise ApiError(
            f"No prices stored for {year}-{month:02d}. "
            + (errors[0] if errors else "Nothing returned.")
        )
    extra = f" Skipped {len(errors)} days without data." if errors else ""
    return PullResult("ok", f"Stored {stored} days for {year}-{month:02d}.{extra}", location)


def pull_year(year: int, *, replace: bool = False) -> PullResult:
    location = f"/{year}"
    area = price_area()
    if db.year_has_row(area, year) and not replace:
        return PullResult("exists", "already stored", f"{location}/confirm")
    stored_months = 0
    for month in range(1, 13):
        result = pull_month(year, month, replace=replace)
        if result.status == "ok":
            stored_months += 1
    if stored_months == 0:
        raise ApiError(f"No prices stored for {year}.")
    return PullResult("ok", f"Stored {stored_months} months for {year}.", location)


def _day_path(day: date) -> str:
    return f"/{day.year}/{day.month:02d}/{day.day:02d}"
