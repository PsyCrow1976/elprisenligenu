"""Dataclasses for spot hours and extra charges."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def as_date_str(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@dataclass
class SpotHour:
    """One hour of day-ahead spot from elprisenligenu.dk (excl. VAT and taxes)."""

    time_start: datetime
    time_end: datetime
    dkk_per_kwh: Decimal
    eur_per_kwh: Decimal | None
    exr: Decimal | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChargeBand:
    """Hourly DKK/kWh excl. VAT for a Datahub tariff (Price1=00:00 local)."""

    owner: str
    gln: str
    charge_type: str
    charge_type_code: str
    note: str
    description: str
    valid_from: datetime | None
    valid_to: datetime | None
    prices: list[Decimal]
    resolution: str | None = None
    tax_indicator: bool = False

    def price_for_hour(self, local_hour: int) -> Decimal:
        if not self.prices:
            return Decimal("0")
        if len(self.prices) == 1:
            return self.prices[0]
        index = max(0, min(local_hour, len(self.prices) - 1))
        return self.prices[index]


@dataclass
class HourCost:
    """Spot plus staten, Energinet, and netselskab for one local hour."""

    period_start: datetime
    period_end: datetime
    local_date: date
    local_hour: int
    price_area: str
    spot_dkk_kwh: Decimal
    spot_eur_kwh: Decimal | None
    exr: Decimal | None
    staten_dkk_kwh: Decimal
    energinet_dkk_kwh: Decimal
    energinet_system_dkk_kwh: Decimal
    energinet_transmission_dkk_kwh: Decimal
    netselskab_dkk_kwh: Decimal
    supplier_dkk_kwh: Decimal
    vat_rate: Decimal
    netselskab_name: str
    supplier_name: str

    @property
    def extra_dkk_kwh(self) -> Decimal:
        return (
            self.staten_dkk_kwh
            + self.energinet_dkk_kwh
            + self.netselskab_dkk_kwh
            + self.supplier_dkk_kwh
        )

    @property
    def total_ex_vat(self) -> Decimal:
        return self.spot_dkk_kwh + self.extra_dkk_kwh

    @property
    def vat_dkk_kwh(self) -> Decimal:
        return (self.total_ex_vat * self.vat_rate).quantize(Decimal("0.000001"))

    @property
    def total_incl_vat(self) -> Decimal:
        return (self.total_ex_vat * (Decimal("1") + self.vat_rate)).quantize(
            Decimal("0.000001")
        )
