"""In-process scheduler for the today/tomorrow price pull."""

from __future__ import annotations

import os
import socket
import threading
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from web import db
from web.ingest import pull_today_and_tomorrow

TIMEZONE = ZoneInfo("Europe/Copenhagen")
JOB_NAME = "prices"
DEFAULT_INTERVAL_HOURS = 12
DEFAULT_LOG_PATH = "/var/log/elprisenligenu/prices.log"


def instance_name() -> str:
    return os.environ.get("JOB_INSTANCE", "").strip() or socket.gethostname()


def interval_hours() -> int:
    raw = os.environ.get("JOB_INTERVAL_HOURS", str(DEFAULT_INTERVAL_HOURS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_INTERVAL_HOURS
    return value if value >= 1 else DEFAULT_INTERVAL_HOURS


def log_path() -> Path:
    configured = Path(os.environ.get("JOB_LOG_PATH", DEFAULT_LOG_PATH))
    try:
        configured.parent.mkdir(parents=True, exist_ok=True)
        configured.touch(exist_ok=True)
        return configured
    except OSError:
        fallback = Path(__file__).resolve().parents[1] / "logs" / "prices.log"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.touch(exist_ok=True)
        return fallback


class PriceJob:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def restore(self) -> None:
        state = db.ensure_job_state(JOB_NAME, interval_hours())
        if state.enabled:
            self.start(run_now=True)

    def start(self, *, run_now: bool = True) -> str:
        with self._lock:
            db.ensure_job_state(JOB_NAME, interval_hours())
            db.set_job_enabled(JOB_NAME, True)
            if self.running:
                return "Price job is already running."
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="elprisenligenu-prices",
                kwargs={"run_now": run_now},
                daemon=True,
            )
            self._thread.start()
            return "Price job started."

    def stop(self) -> str:
        with self._lock:
            db.set_job_enabled(JOB_NAME, False)
            self._stop.set()
            thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        return "Price job stopped."

    def run_once(self, trigger: str = "manual") -> str:
        if not self._run_lock.acquire(blocking=False):
            return "Price job is already running a pull."
        try:
            try:
                message = pull_today_and_tomorrow()
                self._record(True, f"trigger={trigger} {message}")
                return message
            except Exception as exc:
                detail = f"trigger={trigger} {type(exc).__name__}: {exc}"
                tb = traceback.format_exc()
                self._record(False, f"{detail}\n{tb}")
                raise
        finally:
            self._run_lock.release()

    def _loop(self, run_now: bool) -> None:
        wait_seconds = interval_hours() * 3600
        if run_now and not self._stop.is_set():
            try:
                self.run_once(trigger="schedule")
            except Exception:
                pass
        while not self._stop.wait(wait_seconds):
            try:
                self.run_once(trigger="schedule")
            except Exception:
                pass

    def _record(self, success: bool, output: str) -> None:
        now = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
        status = "OK" if success else "FAIL"
        line = (
            f"{now} {status} instance={instance_name()} job={JOB_NAME} {output}".rstrip()
            + "\n"
        )
        path = log_path()
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
        except OSError as exc:
            output = f"{output}\nAlso failed to write {path}: {exc}"
        try:
            db.insert_job_log(
                instance=instance_name(),
                job_name=JOB_NAME,
                success=success,
                output=output,
            )
            db.touch_job_run(JOB_NAME, success)
        except Exception:
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        f"{now} FAIL instance={instance_name()} job={JOB_NAME} "
                        f"database log write failed\n{traceback.format_exc()}\n"
                    )
            except OSError:
                pass


scheduler = PriceJob()
