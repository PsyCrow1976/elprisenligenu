"""Client for elprisenligenu.dk spot prices and Energinet Datahub charges."""

from __future__ import annotations

import json
import time as time_mod
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from script.exceptions import ApiError
from script.models import ChargeBand, HourCost, SpotHour
from script.settings import Settings

DEFAULT_TIMEZONE = ZoneInfo("Europe/Copenhagen")
SPOT_BASE_URL = "https://www.elprisenligenu.dk/api/v1/prices"
DATAHUB_URL = "https://api.energidataservice.dk/dataset/DatahubPricelist"
USER_AGENT = "elprisenligenu/0.0.1 (private home use)"

# Household-facing Energinet kWh charges (excl. VAT).
ENERGINET_SYSTEM_NOTE = "Systemtarif"
ENERGINET_TRANSMISSION_NOTE = "Transmissions nettarif"
ENERGINET_TAX_NOTE = "Elafgift"
ENERGINET_CHARGE_CODES = ("41000", "40000", "EA-001")


class PriceApi:
    """Spot from elprisenligenu.dk, extra charges from Energi Data Service."""

    def __init__(self, settings: Settings, timezone: ZoneInfo | None = None):
        self.settings = settings
        self.timezone = timezone or DEFAULT_TIMEZONE
        self._charge_cache: dict[tuple, list[ChargeBand]] = {}

    @classmethod
    def from_env(cls, timezone: ZoneInfo | None = None) -> PriceApi:
        return cls(Settings.from_env(), timezone=timezone)

    def hours_for_day(self, day: date) -> list[HourCost]:
        """Spot hours for ``day`` with staten, Energinet, and netselskab applied."""
        spots = self.spot_hours(day)
        if not spots:
            raise ApiError(f"No spot prices for {day.isoformat()} in {self.settings.price_area}.")
        staten = self.elafgift(day)
        system = self.energinet_system(day)
        transmission = self.energinet_transmission(day)
        grid = self.netselskab_tariff(day)
        vat = self.settings.vat_rate
        supplier = self.settings.supplier_dkk_kwh
        rows: list[HourCost] = []
        for spot in spots:
            local_start = spot.time_start.astimezone(self.timezone)
            local_hour = local_start.hour
            system_price = system.price_for_hour(local_hour) if system else Decimal("0")
            transmission_price = (
                transmission.price_for_hour(local_hour) if transmission else Decimal("0")
            )
            rows.append(
                HourCost(
                    period_start=spot.time_start,
                    period_end=spot.time_end,
                    local_date=local_start.date(),
                    local_hour=local_hour,
                    price_area=self.settings.price_area,
                    spot_dkk_kwh=spot.dkk_per_kwh,
                    spot_eur_kwh=spot.eur_per_kwh,
                    exr=spot.exr,
                    staten_dkk_kwh=staten.price_for_hour(local_hour) if staten else Decimal("0"),
                    energinet_dkk_kwh=system_price + transmission_price,
                    energinet_system_dkk_kwh=system_price,
                    energinet_transmission_dkk_kwh=transmission_price,
                    netselskab_dkk_kwh=grid.price_for_hour(local_hour) if grid else Decimal("0"),
                    supplier_dkk_kwh=supplier,
                    vat_rate=vat,
                    netselskab_name=self.settings.netselskab_name,
                    supplier_name=self.settings.supplier_name,
                )
            )
        return rows

    def spot_hours(self, day: date) -> list[SpotHour]:
        """Fetch the JSON file for one calendar day and one price area.

        URL shape: ``/api/v1/prices/YYYY/MM-DD_DK2.json``.
        Prices are excl. VAT and excl. taxes. Tomorrow is typically published
        after 13:00 Copenhagen time.
        """
        path = f"{day.year}/{day.month:02d}-{day.day:02d}_{self.settings.price_area}.json"
        url = f"{SPOT_BASE_URL}/{path}"
        payload = self._get_json(url)
        if not isinstance(payload, list):
            raise ApiError(f"Unexpected spot payload for {day.isoformat()}.", body=payload)
        hours: list[SpotHour] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            start = _parse_iso(row.get("time_start"))
            end = _parse_iso(row.get("time_end"))
            dkk = _as_decimal(row.get("DKK_per_kWh"))
            if start is None or end is None or dkk is None:
                continue
            hours.append(
                SpotHour(
                    time_start=start,
                    time_end=end,
                    dkk_per_kwh=dkk,
                    eur_per_kwh=_as_decimal(row.get("EUR_per_kWh")),
                    exr=_as_decimal(row.get("EXR")),
                    raw=row,
                )
            )
        hours.sort(key=lambda item: item.time_start)
        return _hourly_average(hours)

    def elafgift(self, day: date) -> ChargeBand | None:
        return self._pick_charge(
            gln=self.settings.energinet_gln,
            note=ENERGINET_TAX_NOTE,
            charge_type_codes=ENERGINET_CHARGE_CODES,
            day=day,
        )

    def energinet_system(self, day: date) -> ChargeBand | None:
        return self._pick_charge(
            gln=self.settings.energinet_gln,
            note=ENERGINET_SYSTEM_NOTE,
            charge_type_codes=ENERGINET_CHARGE_CODES,
            day=day,
        )

    def energinet_transmission(self, day: date) -> ChargeBand | None:
        return self._pick_charge(
            gln=self.settings.energinet_gln,
            note=ENERGINET_TRANSMISSION_NOTE,
            charge_type_codes=ENERGINET_CHARGE_CODES,
            day=day,
        )

    def netselskab_tariff(self, day: date) -> ChargeBand | None:
        return self._pick_charge(
            gln=self.settings.netselskab_gln,
            charge_type_code=self.settings.netselskab_charge_code,
            charge_type="D03",
            day=day,
        )

    def lookup_charges(self, day: date) -> dict[str, ChargeBand | None]:
        """Current extra-cost bands used for ``day`` (for the web settings page)."""
        return {
            "staten": self.elafgift(day),
            "energinet_system": self.energinet_system(day),
            "energinet_transmission": self.energinet_transmission(day),
            "netselskab": self.netselskab_tariff(day),
        }

    def _pick_charge(
        self,
        *,
        gln: str,
        day: date,
        note: str | None = None,
        charge_type_code: str | None = None,
        charge_type_codes: tuple[str, ...] | None = None,
        charge_type: str | None = None,
    ) -> ChargeBand | None:
        bands = self._charges(
            gln,
            note=note,
            charge_type_code=charge_type_code,
            charge_type_codes=charge_type_codes,
            charge_type=charge_type,
        )
        start = datetime.combine(day, time.min, tzinfo=self.timezone)
        chosen: ChargeBand | None = None
        for band in bands:
            if band.valid_from and band.valid_from > start:
                continue
            if band.valid_to and band.valid_to <= start:
                continue
            if chosen is None or _later(band.valid_from, chosen.valid_from):
                chosen = band
        return chosen

    def _charges(
        self,
        gln: str,
        *,
        note: str | None = None,
        charge_type_code: str | None = None,
        charge_type_codes: tuple[str, ...] | None = None,
        charge_type: str | None = None,
    ) -> list[ChargeBand]:
        codes = charge_type_codes or ((charge_type_code,) if charge_type_code else None)
        all_for_gln = self._charges_for_gln(gln, charge_type_codes=codes, charge_type=charge_type)
        matched = []
        for band in all_for_gln:
            if note and band.note != note:
                continue
            if charge_type_code and band.charge_type_code != charge_type_code:
                continue
            if charge_type and band.charge_type != charge_type:
                continue
            matched.append(band)
        return matched

    def _charges_for_gln(
        self,
        gln: str,
        *,
        charge_type_codes: tuple[str, ...] | None = None,
        charge_type: str | None = None,
    ) -> list[ChargeBand]:
        key = (gln, charge_type_codes, charge_type)
        if key in self._charge_cache:
            return self._charge_cache[key]
        filt: dict[str, list[str]] = {"GLN_Number": [gln]}
        if charge_type_codes:
            filt["ChargeTypeCode"] = list(charge_type_codes)
        if charge_type:
            filt["ChargeType"] = [charge_type]
        params = {
            "limit": "200",
            "sort": "ValidFrom DESC",
            "filter": json.dumps(filt),
        }
        url = DATAHUB_URL + "?" + urllib.parse.urlencode(params)
        payload = self._get_json(url)
        records = payload.get("records") if isinstance(payload, dict) else None
        bands = [_charge_from_record(row) for row in records or [] if isinstance(row, dict)]
        bands = [band for band in bands if band is not None]
        self._charge_cache[key] = bands
        return bands

    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read()
                    status = response.status
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise ApiError(
                        f"Invalid JSON from {url}", status_code=status, body=raw[:500]
                    ) from exc
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                if exc.code == 404:
                    raise ApiError(
                        f"No price file at {url} (404). Tomorrow is published after 13:00.",
                        status_code=404,
                        body=body,
                    ) from exc
                if exc.code == 429 and attempt < 4:
                    time_mod.sleep(2 ** attempt)
                    last_error = exc
                    continue
                raise ApiError(
                    f"HTTP {exc.code} from {url}", status_code=exc.code, body=body
                ) from exc
            except urllib.error.URLError as exc:
                raise ApiError(f"Could not reach {url}: {exc.reason}") from exc
        raise ApiError(f"HTTP 429 from {url}", status_code=429) from last_error


def _hourly_average(hours: list[SpotHour]) -> list[SpotHour]:
    """Collapse 15-minute market records into clock hours when needed."""
    if len(hours) <= 24:
        return hours
    buckets: dict[datetime, list[SpotHour]] = {}
    for hour in hours:
        local = hour.time_start.astimezone(DEFAULT_TIMEZONE)
        key = local.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(key, []).append(hour)
    averaged: list[SpotHour] = []
    for start, group in sorted(buckets.items()):
        dkk = sum((item.dkk_per_kwh for item in group), Decimal("0")) / Decimal(len(group))
        eurs = [item.eur_per_kwh for item in group if item.eur_per_kwh is not None]
        eur = sum(eurs, Decimal("0")) / Decimal(len(eurs)) if eurs else None
        averaged.append(
            SpotHour(
                time_start=group[0].time_start,
                time_end=group[-1].time_end,
                dkk_per_kwh=dkk,
                eur_per_kwh=eur,
                exr=group[0].exr,
            )
        )
        _ = start
    return averaged


def _charge_from_record(row: dict[str, Any]) -> ChargeBand | None:
    prices: list[Decimal] = []
    for index in range(1, 25):
        value = _as_decimal(row.get(f"Price{index}"))
        if value is None:
            break
        prices.append(value)
    if not prices:
        return None
    resolution = str(row.get("ResolutionDuration") or "")
    rest_zero = all(price == 0 for price in prices[1:])
    if rest_zero or resolution in {"P1D", "P1M", "P1Y"}:
        prices = [prices[0]]
    elif len(prices) < 24:
        while len(prices) < 24:
            prices.append(prices[-1])
    return ChargeBand(
        owner=str(row.get("ChargeOwner") or ""),
        gln=str(row.get("GLN_Number") or ""),
        charge_type=str(row.get("ChargeType") or ""),
        charge_type_code=str(row.get("ChargeTypeCode") or ""),
        note=str(row.get("Note") or ""),
        description=str(row.get("Description") or ""),
        valid_from=_parse_naive(row.get("ValidFrom")),
        valid_to=_parse_naive(row.get("ValidTo")),
        prices=prices,
        resolution=row.get("ResolutionDuration"),
        tax_indicator=bool(row.get("TaxIndicator")),
    )


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DEFAULT_TIMEZONE)
    return parsed


def _parse_naive(value: Any) -> datetime | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=DEFAULT_TIMEZONE) if parsed.tzinfo is None else parsed.astimezone(
        DEFAULT_TIMEZONE
    )


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _later(left: datetime | None, right: datetime | None) -> bool:
    if left is None:
        return False
    if right is None:
        return True
    return left > right


def next_local_day(day: date) -> date:
    return day + timedelta(days=1)
