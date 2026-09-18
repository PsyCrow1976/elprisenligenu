"""FastHTML interface for Danish hourly electricity prices stored in PostgreSQL."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from fasthtml.common import (
    A,
    Article,
    Button,
    Div,
    Form,
    H1,
    H2,
    Header,
    Input,
    Label,
    Main,
    Nav,
    Option,
    P,
    Pre,
    Select,
    Span,
    Strong,
    Style,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Title,
    Tr,
    fast_app,
)
from starlette.responses import RedirectResponse, PlainTextResponse

from script.exceptions import PriceError
from script.models import ChargeBand
from web import db
from web.ingest import price_api, price_area, pull_day, pull_month, pull_year, reload_settings, settings
from web.jobs import JOB_NAME, instance_name, interval_hours, log_path, scheduler

TIMEZONE = ZoneInfo("Europe/Copenhagen")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

CSS = """
:root { --pico-primary: #b45309; }
body { background: #f4f1ea; }
main.container { max-width: 64rem; padding-bottom: 3rem; }
header.top { display: flex; justify-content: space-between; gap: 1rem;
  align-items: baseline; flex-wrap: wrap; margin-top: 1.2rem; }
header.top h1 { margin: 0; font-size: 1.6rem; }
header.top p { margin: 0; color: #5c5c5c; }
nav.crumbs { margin: 0.6rem 0 1.2rem; display: flex; gap: 0.4rem; flex-wrap: wrap; }
nav.crumbs a, nav.crumbs span { color: #b45309; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
  gap: 0.7rem; }
.cards a, .cal a, .cal span { text-decoration: none; color: inherit; }
.card, .cal a, .cal span {
  background: #fff; border: 1px solid #ddd4c4; border-radius: 0.5rem;
  padding: 0.7rem; display: flex; flex-direction: column; gap: 0.15rem;
}
.card.has, .cal .has { background: #fef3c7; border-color: #f0c674; }
.card:hover, .cal a:hover { border-color: #b45309; }
.card .num, .kwh { font-variant-numeric: tabular-nums; font-weight: 650; }
.muted { color: #6b6b6b; font-size: 0.9rem; }
.cal { display: grid; grid-template-columns: repeat(7, 1fr); gap: 0.4rem; }
.cal .dow { background: transparent; border: 0; padding: 0.2rem; font-size: 0.8rem;
  color: #6b6b6b; }
.cal .empty { background: transparent; border: 0; }
.cal .today { outline: 2px solid #b45309; }
.actions { display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center; }
.actions form { margin: 0; }
button.secondary { background: #fff; color: #b45309; border: 1px solid #b45309; }
article.warn { background: #fff7e8; border-color: #e6c989; }
article.err { background: #fdecec; border-color: #e2a2a2; }
.jump { display: flex; gap: 0.5rem; align-items: end; flex-wrap: wrap; }
.jump input { margin-bottom: 0; }
table { font-variant-numeric: tabular-nums; font-size: 0.92rem; }
.cheap { background: #ecfdf3; }
.now { outline: 2px solid #b45309; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: 0.8rem; }
.legend dt { font-weight: 650; }
nav.top-nav { display: flex; gap: 0.9rem; }
nav.top-nav a { color: #b45309; font-weight: 650; }
.badge { font-size: 0.85rem; font-weight: 650; }
.ok { color: #0f766e; }
.fail { color: #b42318; }
pre.output { white-space: pre-wrap; font-size: 0.85rem; margin: 0;
  font-family: ui-monospace, monospace; }
"""


def on_startup() -> None:
    db.ensure_schema()
    scheduler.restore()


app, rt = fast_app(
    title="Elprisen lige nu",
    pico=True,
    hdrs=(Style(CSS),),
    on_startup=[on_startup],
)


@rt("/health")
def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@rt("/jobs")
def jobs_view(msg: str | None = None, err: str | None = None):
    state = db.get_job_state(JOB_NAME)
    logs = db.list_job_logs(JOB_NAME, limit=100)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    area = price_area()
    counts = db.day_hour_counts(area, [today, tomorrow])
    running = scheduler.running
    enabled = state.enabled if state else False
    status = "running" if running else "stopped"
    last = "never"
    last_cls = "muted"
    if state and state.last_run_at:
        last = fmt_when(state.last_run_at)
        last_cls = "ok" if state.last_success else "fail"
    log_rows = []
    for item in logs:
        log_rows.append(
            Tr(
                Td(fmt_when(item.logged_at)),
                Td(item.instance),
                Td("OK" if item.success else "FAIL", cls="ok" if item.success else "fail"),
                Td(Pre(item.output, cls="output")),
            )
        )
    log_table = (
        Table(
            Thead(Tr(Th("Time"), Th("Instance"), Th("Result"), Th("Output"))),
            Tbody(*log_rows),
        )
        if log_rows
        else P("No job log entries yet.")
    )
    controls = []
    if running:
        controls.append(
            Form(
                Button("Stop job", cls="secondary"),
                method="post",
                action="/jobs/stop",
                enctype="application/x-www-form-urlencoded",
            )
        )
    else:
        controls.append(
            Form(
                Button("Start job"),
                method="post",
                action="/jobs/start",
                enctype="application/x-www-form-urlencoded",
            )
        )
    controls.append(
        Form(
            Button("Run now", cls="secondary"),
            method="post",
            action="/jobs/run",
            enctype="application/x-www-form-urlencoded",
        )
    )
    return _page(
        _crumbs([("Jobs", None)]),
        _flash(msg, err),
        Article(
            H2("Price job"),
            P(
                Strong(status.capitalize(), cls="badge " + ("ok" if running else "fail")),
                Span(
                    f" · enabled in database: {'yes' if enabled else 'no'}"
                    f" · every {interval_hours()} hours"
                    f" · instance {instance_name()}"
                    f" · area {area}",
                    cls="muted",
                ),
            ),
            P(f"Last run: {last}", cls=last_cls),
            P(
                f"Stored hourly prices: today {counts.get(today, 0)} hours, "
                f"tomorrow {counts.get(tomorrow, 0)} hours."
            ),
            P(f"Log file: {log_path()}", cls="muted"),
            Div(*controls, cls="actions"),
            **({"cls": "warn"} if not running else {}),
        ),
        H2("Log"),
        P("Newest first. Each run is written to the log file and to PostgreSQL."),
        log_table,
        title="Jobs",
    )


@rt("/jobs/start", methods=["POST"])
def jobs_start():
    try:
        message = scheduler.start(run_now=True)
    except Exception as exc:
        return _redirect("/jobs", err=str(exc))
    return _redirect("/jobs", msg=message)


@rt("/jobs/stop", methods=["POST"])
def jobs_stop():
    try:
        message = scheduler.stop()
    except Exception as exc:
        return _redirect("/jobs", err=str(exc))
    return _redirect("/jobs", msg=message)


@rt("/jobs/run", methods=["POST"])
def jobs_run():
    try:
        message = scheduler.run_once(trigger="manual")
    except Exception as exc:
        return _redirect("/jobs", err=str(exc))
    return _redirect("/jobs", msg=message)


@rt("/")
def index(go: str | None = None, msg: str | None = None, err: str | None = None):
    if go:
        try:
            chosen = date.fromisoformat(go)
        except ValueError:
            chosen = None
        if chosen:
            return _redirect(_day_href(chosen))
    area = price_area()
    years = db.list_years(area)
    cards = [
        A(
            Div(str(year), cls="num"),
            Div("stored year", cls="muted"),
            href=f"/{year}",
            cls="card",
        )
        for year in years
    ]
    today = date.today()
    body = [
        _flash(msg, err),
        P(
            f"Hourly Danish electricity prices for {area}. "
            "Spot from elprisenligenu.dk, plus staten, Energinet, and netselskab from Datahub."
        ),
        Div(*cards, cls="cards") if cards else P("No prices stored yet. Pick a date and get data."),
        H2("Open a date"),
        Form(
            Div(
                Label("Date", Input(type="date", name="go", value=today.isoformat(), required=True)),
                Button("Open"),
                cls="jump",
            ),
            method="get",
            action="/",
            enctype="application/x-www-form-urlencoded",
        ),
        Div(
            A("Today", href=_day_href(today), cls="secondary"),
            A("Charges / settings", href="/settings"),
            cls="actions",
        ),
    ]
    return _page(*body, title="Elprisen lige nu")


@rt("/settings")
def settings_view(msg: str | None = None, err: str | None = None):
    cfg = settings()
    today = date.today()
    charges = None
    lookup_err = None
    try:
        charges = price_api().lookup_charges(today)
    except PriceError as exc:
        lookup_err = str(exc)
    rows = []
    if charges:
        staten = charges.get("staten")
        system = charges.get("energinet_system")
        trans = charges.get("energinet_transmission")
        grid = charges.get("netselskab")
        energinet = Decimal("0")
        if system:
            energinet += system.price_for_hour(12)
        if trans:
            energinet += trans.price_for_hour(12)
        rows = [
            Tr(Td("Spot"), Td("elprisenligenu.dk"), Td("varies by hour"), Td("API")),
            Tr(
                Td("Staten (elafgift)"),
                Td(_band_label(staten)),
                Td(fmt_kr(staten.price_for_hour(0) if staten else None)),
                Td("Datahub lookup"),
            ),
            Tr(
                Td("Energinet (system + transmission)"),
                Td(_band_label(system) + " + " + _band_label(trans)),
                Td(fmt_kr(energinet)),
                Td("Datahub lookup"),
            ),
            Tr(
                Td("Netselskab"),
                Td(_band_label(grid) or cfg.netselskab_name),
                Td(_grid_summary(grid)),
                Td("Datahub lookup"),
            ),
            Tr(
                Td("Supplier tillæg (optional)"),
                Td(cfg.supplier_name),
                Td(fmt_kr(cfg.supplier_dkk_kwh)),
                Td("env / this page"),
            ),
        ]
    return _page(
        _crumbs([("Settings", None)]),
        _flash(msg, err or lookup_err),
        H2("How the hourly cost is built"),
        P(
            "Spot is the Nord Pool day-ahead price. The three extra costs are looked up "
            "from Energinet Datahub for the date you pull. All stored numbers are kr/kWh "
            "excl. VAT; the table also shows inkl. moms at 25%."
        ),
        Table(
            Thead(Tr(Th("Part"), Th("Source"), Th("Amount excl. VAT"), Th("How"))),
            Tbody(*rows),
        )
        if rows
        else None,
        P(_grid_hours(charges.get("netselskab") if charges else None), cls="muted"),
        H2("Overrides"),
        P(
            f"Prisklasse is {cfg.price_area} from the PRISKLASSE env (DK2 = 2700 Brønshøj). "
            "2700 is Radius Elnet, tariff class C (DT_C_01). Andel Energi is the supplier, "
            "not the grid company — their kWh tillæg is optional because it is not in Datahub."
        ),
        Form(
            Div(
                Label("Supplier name", Input(name="supplier_name", value=cfg.supplier_name)),
                Label(
                    "Supplier tillæg, kr/kWh excl. VAT",
                    Input(name="supplier_dkk_kwh", value=str(cfg.supplier_dkk_kwh), inputmode="decimal"),
                ),
                Label("Netselskab name", Input(name="netselskab_name", value=cfg.netselskab_name)),
                Label("Netselskab GLN", Input(name="netselskab_gln", value=cfg.netselskab_gln)),
                Label(
                    "Netselskab charge code",
                    Input(name="netselskab_charge_code", value=cfg.netselskab_charge_code),
                ),
                Label(
                    "Suggested Andel FlexEnergi tillæg",
                    Select(
                        Option("Keep current", value="", selected=True),
                        Option("0 (spot + public charges only)", value="0"),
                        Option("0.11664 (~14.58 øre/kWh inkl. moms)", value="0.11664"),
                        name="supplier_preset",
                    ),
                ),
                cls="form-grid",
            ),
            Div(Button("Save"), cls="actions"),
            method="post",
            action="/settings",
            enctype="application/x-www-form-urlencoded",
        ),
        title="Settings",
    )


@rt("/settings", methods=["POST"])
def settings_save(
    supplier_name: str = "",
    supplier_dkk_kwh: str = "",
    supplier_preset: str = "",
    netselskab_name: str = "",
    netselskab_gln: str = "",
    netselskab_charge_code: str = "",
):
    if supplier_preset:
        supplier_dkk_kwh = supplier_preset
    try:
        Decimal(supplier_dkk_kwh.replace(",", "."))
    except Exception:
        return _redirect("/settings", err="Supplier tillæg must be a number (kr/kWh excl. VAT).")
    db.set_setting("supplier_name", supplier_name.strip() or "Andel Energi")
    db.set_setting("supplier_dkk_kwh", supplier_dkk_kwh.replace(",", ".").strip() or "0")
    db.set_setting("netselskab_name", netselskab_name.strip())
    db.set_setting("netselskab_gln", netselskab_gln.strip())
    db.set_setting("netselskab_charge_code", netselskab_charge_code.strip())
    reload_settings()
    return _redirect("/settings", msg="Saved. New pulls will use these values.")


@rt("/{year:int}")
def year_view(year: int, msg: str | None = None, err: str | None = None):
    area = price_area()
    stored = {item.month: item for item in db.list_months(area, year)}
    year_row = db.get_year(area, year)
    cards = []
    for month in range(1, 13):
        item = stored.get(month)
        extra = [Div(calendar.month_name[month])]
        if item:
            extra.append(Div(fmt_kr(item.avg_total_incl_vat), cls="kwh"))
            extra.append(Div(f"{item.day_count} days", cls="muted"))
        cards.append(A(*extra, href=f"/{year}/{month:02d}", cls="card" + (" has" if item else "")))
    summary = []
    if year_row:
        summary.append(
            P(
                f"Year average {fmt_kr(year_row.avg_total_incl_vat)} inkl. moms · scraped "
                f"{fmt_when(year_row.scraped_at)}"
            )
        )
    return _page(
        _crumbs([(str(year), None)]),
        _flash(msg, err),
        *summary,
        Div(*cards, cls="cards"),
        _get_data_form(f"/{year}/fetch", "Get data for this year"),
        title=str(year),
    )


@rt("/{year:int}/confirm")
def year_confirm(year: int):
    area = price_area()
    row = db.get_year(area, year)
    if row is None:
        return _redirect(f"/{year}")
    return _confirm_page(
        crumbs=[(str(year), f"/{year}"), ("Confirm", None)],
        heading=f"Year {year} is already stored",
        details=[
            P(f"Average: {fmt_kr(row.avg_total_incl_vat)} inkl. moms"),
            P(f"Months stored: {row.month_count}"),
            P(f"Last scraped: {fmt_when(row.scraped_at)}"),
            P("Pull this year again? Stored days and hours for this year will be replaced where the API has data."),
        ],
        action=f"/{year}/fetch",
        cancel=f"/{year}",
        title=f"Confirm {year}",
    )


@rt("/{year:int}/fetch", methods=["POST"])
def year_fetch(year: int, confirm: str | None = None):
    return _run_pull(lambda: pull_year(year, replace=confirm == "1"), f"/{year}")


@rt("/{year:int}/{month:int}")
def month_view(year: int, month: int, msg: str | None = None, err: str | None = None):
    try:
        _valid_month(year, month)
    except ValueError:
        return _redirect("/")
    area = price_area()
    month_row = db.get_month(area, year, month)
    days = {item.day.day: item for item in db.list_days(area, year, month)}
    cal = calendar.Calendar(firstweekday=0)
    cells = [Div(name, cls="dow") for name in WEEKDAYS]
    today = date.today()
    for current in cal.itermonthdates(year, month):
        if current.month != month:
            cells.append(Div(cls="empty"))
            continue
        item = days.get(current.day)
        classes = ["cal-day"]
        if item:
            classes.append("has")
        if current == today:
            classes.append("today")
        inner = [Div(str(current.day))]
        if item:
            inner.append(Div(fmt_kr(item.avg_total_incl_vat), cls="kwh"))
        cells.append(A(*inner, href=_day_href(current), cls=" ".join(classes)))
    summary = []
    if month_row:
        summary.append(
            P(
                f"Month average {fmt_kr(month_row.avg_total_incl_vat)} inkl. moms · "
                f"{month_row.day_count} days · scraped {fmt_when(month_row.scraped_at)}"
            )
        )
    return _page(
        _crumbs([(str(year), f"/{year}"), (calendar.month_name[month], None)]),
        _flash(msg, err),
        *summary,
        Div(*cells, cls="cal"),
        _get_data_form(f"/{year}/{month:02d}/fetch", "Get data for this month"),
        title=f"{calendar.month_name[month]} {year}",
    )


@rt("/{year:int}/{month:int}/confirm")
def month_confirm(year: int, month: int):
    try:
        _valid_month(year, month)
    except ValueError:
        return _redirect("/")
    area = price_area()
    row = db.get_month(area, year, month)
    if row is None or not db.month_has_row(area, year, month):
        return _redirect(f"/{year}/{month:02d}")
    return _confirm_page(
        crumbs=[
            (str(year), f"/{year}"),
            (calendar.month_name[month], f"/{year}/{month:02d}"),
            ("Confirm", None),
        ],
        heading=f"{calendar.month_name[month]} {year} is already stored",
        details=[
            P(f"Average: {fmt_kr(row.avg_total_incl_vat)} inkl. moms"),
            P(f"Days stored: {row.day_count}"),
            P(f"Last scraped: {fmt_when(row.scraped_at)}"),
            P("Pull this month again? Stored hourly rows for days that the API still has will be replaced."),
        ],
        action=f"/{year}/{month:02d}/fetch",
        cancel=f"/{year}/{month:02d}",
        title=f"Confirm {year}-{month:02d}",
    )


@rt("/{year:int}/{month:int}/fetch", methods=["POST"])
def month_fetch(year: int, month: int, confirm: str | None = None):
    try:
        _valid_month(year, month)
    except ValueError:
        return _redirect("/")
    return _run_pull(
        lambda: pull_month(year, month, replace=confirm == "1"),
        f"/{year}/{month:02d}",
    )


@rt("/{year:int}/{month:int}/{day:int}")
def day_view(year: int, month: int, day: int, msg: str | None = None, err: str | None = None):
    try:
        chosen = date(year, month, day)
    except ValueError:
        return _redirect("/")
    area = price_area()
    row = db.get_day(area, chosen)
    hours = db.list_hours(area, chosen) if row else []
    summary = []
    if row:
        summary.append(
            P(
                f"Average {fmt_kr(row.avg_total_incl_vat)} inkl. moms · "
                f"min {fmt_kr(row.min_total_incl_vat)} · max {fmt_kr(row.max_total_incl_vat)} · "
                f"{row.hour_count} hours · scraped {fmt_when(row.scraped_at)}"
            )
        )
    else:
        summary.append(P("No prices stored for this date yet."))
    table = None
    if hours:
        cheapest = min(item.total_incl_vat for item in hours)
        now = datetime.now(TIMEZONE)
        body_rows = []
        for item in hours:
            classes = []
            if item.total_incl_vat == cheapest:
                classes.append("cheap")
            if item.local_date == now.date() and item.local_hour == now.hour:
                classes.append("now")
            body_rows.append(
                Tr(
                    Td(f"{item.local_hour:02d}:00"),
                    Td(fmt_kr(item.spot_dkk_kwh)),
                    Td(fmt_kr(item.staten_dkk_kwh)),
                    Td(fmt_kr(item.energinet_dkk_kwh)),
                    Td(fmt_kr(item.netselskab_dkk_kwh)),
                    Td(fmt_kr(item.supplier_dkk_kwh)),
                    Td(fmt_kr(item.total_ex_vat)),
                    Td(fmt_kr(item.total_incl_vat)),
                    cls=" ".join(classes) if classes else None,
                )
            )
        table = Table(
            Thead(
                Tr(
                    Th("Hour"),
                    Th("Spot"),
                    Th("Staten"),
                    Th("Energinet"),
                    Th("Netselskab"),
                    Th("Supplier"),
                    Th("Total excl. VAT"),
                    Th("Total inkl. moms"),
                )
            ),
            Tbody(*body_rows),
        )
    button_label = "Get data" if row is None else "Get data again"
    return _page(
        _crumbs(
            [
                (str(year), f"/{year}"),
                (calendar.month_name[month], f"/{year}/{month:02d}"),
                (chosen.isoformat(), None),
            ]
        ),
        _flash(msg, err),
        *summary,
        table,
        P("Amounts are kr/kWh. Cheapest hour is highlighted. Current hour is outlined when viewing today.", cls="muted"),
        _get_data_form(_day_href(chosen) + "/fetch", button_label),
        title=chosen.isoformat(),
    )


@rt("/{year:int}/{month:int}/{day:int}/confirm")
def day_confirm(year: int, month: int, day: int):
    try:
        chosen = date(year, month, day)
    except ValueError:
        return _redirect("/")
    area = price_area()
    row = db.get_day(area, chosen)
    if row is None:
        return _redirect(_day_href(chosen))
    return _confirm_page(
        crumbs=[
            (str(year), f"/{year}"),
            (calendar.month_name[month], f"/{year}/{month:02d}"),
            (chosen.isoformat(), _day_href(chosen)),
            ("Confirm", None),
        ],
        heading=f"{chosen.isoformat()} is already stored",
        details=[
            P(f"Average: {fmt_kr(row.avg_total_incl_vat)} inkl. moms"),
            P(f"Hours stored: {row.hour_count}"),
            P(f"Last scraped: {fmt_when(row.scraped_at)}"),
            P("Pull this date again? Stored hourly prices will be replaced."),
        ],
        action=_day_href(chosen) + "/fetch",
        cancel=_day_href(chosen),
        title=f"Confirm {chosen.isoformat()}",
    )


@rt("/{year:int}/{month:int}/{day:int}/fetch", methods=["POST"])
def day_fetch(year: int, month: int, day: int, confirm: str | None = None):
    try:
        chosen = date(year, month, day)
    except ValueError:
        return _redirect("/")
    return _run_pull(
        lambda: pull_day(chosen, replace=confirm == "1"),
        _day_href(chosen),
    )


def _run_pull(action, fallback: str):
    try:
        result = action()
    except PriceError as exc:
        return _redirect(fallback, err=str(exc))
    except Exception as exc:
        return _redirect(fallback, err=str(exc))
    if result.status == "exists":
        return _redirect(result.location)
    return _redirect(result.location, msg=result.message)


def _get_data_form(action: str, label: str):
    return Div(
        Form(
            Button(label),
            method="post",
            action=action,
            enctype="application/x-www-form-urlencoded",
        ),
        cls="actions",
    )


def _confirm_page(*, crumbs, heading, details, action, cancel, title):
    return _page(
        _crumbs(crumbs),
        Article(
            H2(heading),
            *details,
            Div(
                A("Cancel", href=cancel, cls="secondary"),
                Form(
                    Input(type="hidden", name="confirm", value="1"),
                    Button("Yes, pull again"),
                    method="post",
                    action=action,
                    enctype="application/x-www-form-urlencoded",
                ),
                cls="actions",
            ),
            cls="warn",
        ),
        title=title,
    )


def _page(*content, title: str):
    cfg = None
    try:
        cfg = settings()
    except Exception:
        cfg = None
    subtitle = cfg.price_area if cfg else "Elprisen"
    if cfg:
        subtitle = f"{cfg.price_area} · {cfg.netselskab_name}"
    nodes = [item for item in content if item is not None]
    return (
        Title(title),
        Main(
            Header(
                Div(
                    H1(A("Elprisen lige nu", href="/")),
                    P(subtitle, cls="muted"),
                ),
                Nav(
                    A("Jobs", href="/jobs"),
                    A("Settings", href="/settings"),
                    cls="top-nav",
                ),
                cls="top",
            ),
            *nodes,
            cls="container",
        ),
    )


def _crumbs(parts: list[tuple[str, str | None]]):
    items = [A("Years", href="/")]
    for label, href in parts:
        items.append(Span(" / "))
        items.append(A(label, href=href) if href else Span(label))
    return Nav(*items, cls="crumbs")


def _flash(msg: str | None, err: str | None):
    nodes = []
    if msg:
        nodes.append(Article(P(msg)))
    if err:
        nodes.append(Article(P(err), cls="err"))
    return Div(*nodes) if nodes else None


def _redirect(url: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    params = []
    if msg:
        params.append("msg=" + _query(msg))
    if err:
        params.append("err=" + _query(err))
    if params:
        url = url + ("&" if "?" in url else "?") + "&".join(params)
    return RedirectResponse(url, status_code=303)


def _query(value: str) -> str:
    return quote(value, safe="")


def _day_href(day: date) -> str:
    return f"/{day.year}/{day.month:02d}/{day.day:02d}"


def _valid_month(year: int, month: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError("month")
    date(year, month, 1)


def fmt_kr(value: Decimal | float | None) -> str:
    if value is None:
        return "—"
    number = Decimal(value)
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return f"{text} kr/kWh"


def fmt_when(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=TIMEZONE)
    local = value.astimezone(TIMEZONE)
    return local.strftime("%Y-%m-%d %H:%M") + " Copenhagen"


def _band_label(band: ChargeBand | None) -> str:
    if band is None:
        return "—"
    return band.note or band.charge_type_code or band.owner


def _grid_summary(band: ChargeBand | None) -> str:
    if band is None:
        return "—"
    if len(band.prices) == 1:
        return fmt_kr(band.prices[0])
    low = min(band.prices)
    high = max(band.prices)
    return f"{fmt_kr(low)} – {fmt_kr(high)} (time-of-use)"


def _grid_hours(band: ChargeBand | None) -> str:
    if band is None or len(band.prices) <= 1:
        return ""
    parts = []
    current = None
    start = 0
    for hour, price in enumerate(list(band.prices) + [None]):
        if price != current:
            if current is not None:
                parts.append(f"{start:02d}–{hour:02d}: {fmt_kr(current)}")
            current = price
            start = hour
    return "Radius Nettarif C excl. VAT today: " + " · ".join(parts)
