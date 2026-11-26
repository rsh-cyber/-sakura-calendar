"""Persistent launch counts and character-scoped calendar receipts."""

from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3

from calendar_core import default_state, timezone_now


_TIMEZONES = ("Asia/Shanghai", "Asia/Tokyo", "local")
_STATUSES = {"pending", "inflight", "sent", "failed", "suppressed"}
_DATABASE_VERSION = 1
_MIGRATION_KEY = "legacy_receipts"
_TABLES = (
    """CREATE TABLE metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE launch_days (
        zone TEXT NOT NULL,
        local_date TEXT NOT NULL,
        launch_count INTEGER NOT NULL,
        last_boot_id TEXT NOT NULL,
        last_launch_at TEXT NOT NULL,
        PRIMARY KEY (zone, local_date)
    )""",
    """CREATE TABLE observed_boots (
        zone TEXT NOT NULL,
        local_date TEXT NOT NULL,
        boot_id TEXT NOT NULL,
        PRIMARY KEY (zone, local_date, boot_id)
    )""",
    """CREATE TABLE receipts (
        character_id TEXT NOT NULL,
        local_date TEXT NOT NULL,
        event_key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (character_id, local_date, event_key)
    )""",
)


class CalendarLedgerError(ValueError):
    """Calendar state could not be loaded or committed."""


def _nonempty_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CalendarLedgerError(f"{label}不能为空。")


def _iso_date(value: object) -> str:
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.isoformat() == value:
                return value
    raise CalendarLedgerError("日历记录的日期格式无效。")


def _event_date(event_key: str) -> str:
    if isinstance(event_key, str):
        parts = event_key.split("|", 2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return _iso_date(parts[0])
    raise CalendarLedgerError("日历事件编号格式无效。")


def _encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _read_legacy(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        raise CalendarLedgerError("无法读取旧版日历状态。") from error

    try:
        state = json.loads(text)
        if not isinstance(state, dict) or state.get("schemaVersion") != 1:
            raise ValueError("invalid legacy version")
        count = state["launchCount"]
        local_date, boot_id, launch_at = state["localDate"], state["lastBootId"], state["lastLaunchAt"]
        if type(count) is not int or count < 0 or not all(isinstance(value, str) for value in (local_date, boot_id, launch_at)):
            raise ValueError("invalid launch state")
        if local_date or count:
            _iso_date(local_date)
        if count:
            _nonempty_id(boot_id, "旧版启动标识")
        if launch_at:
            datetime.fromisoformat(launch_at)
        receipts = state["sentEvents"]
        if not isinstance(receipts, dict):
            raise ValueError("invalid receipts")
        for key, receipt in receipts.items():
            _event_date(key)
            if isinstance(receipt, str):
                receipt = receipts[key] = {"status": receipt}
            if not isinstance(receipt, dict) or receipt.get("status") not in _STATUSES:
                raise ValueError("invalid receipt status")
            if "updatedAt" in receipt:
                datetime.fromisoformat(receipt["updatedAt"])
        _encoded(receipts)
    except (KeyError, TypeError, ValueError) as error:
        raise CalendarLedgerError("旧版日历状态格式无效。") from error
    return state


class CalendarLedger:
    """Track physical application starts per timezone and receipts per character."""

    def __init__(self, path: Path, legacy_path: Path, boot_id: str, *, legacy_timezone: str):
        _nonempty_id(boot_id, "应用启动标识")
        timezone_now(legacy_timezone)
        self._path = Path(path)
        self._boot_id = boot_id
        self._timezones = tuple(dict.fromkeys((*_TIMEZONES, legacy_timezone)))
        self._last_observed_dates: tuple[str, ...] = ()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise CalendarLedgerError("无法创建日历状态目录。") from error

        with self._database(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                for statement in _TABLES:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {_DATABASE_VERSION}")
            elif version != _DATABASE_VERSION:
                raise CalendarLedgerError("不支持此版本的日历状态库。")

            marker = connection.execute(
                "SELECT value FROM metadata WHERE key = ?", (_MIGRATION_KEY,),
            ).fetchone()
            if marker is None:
                self._stage_legacy(connection, Path(legacy_path), legacy_timezone)

    @contextmanager
    def _database(self, *, write=False):
        try:
            with closing(sqlite3.connect(self._path, timeout=5.0)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
        except sqlite3.Error as error:
            raise CalendarLedgerError("无法读取或保存日历状态库。") from error

    @staticmethod
    def _stage_legacy(connection, legacy_path: Path, timezone_name: str) -> None:
        legacy = _read_legacy(legacy_path)
        pending = None if legacy is None else legacy["sentEvents"] or None
        if legacy and legacy["launchCount"]:
            zone_date_boot = (timezone_name, legacy["localDate"], legacy["lastBootId"])
            connection.execute(
                "INSERT INTO observed_boots (zone, local_date, boot_id) VALUES (?, ?, ?)",
                zone_date_boot,
            )
            connection.execute(
                """INSERT INTO launch_days (zone, local_date, launch_count, last_boot_id, last_launch_at)
                    VALUES (?, ?, ?, ?, ?)""",
                (timezone_name, legacy["localDate"], legacy["launchCount"], legacy["lastBootId"], legacy["lastLaunchAt"]),
            )
        connection.execute("INSERT INTO metadata (key, value) VALUES (?, ?)", (_MIGRATION_KEY, _encoded(pending)))

    def observe(self, now: datetime) -> None:
        """Count this boot once for each supported timezone's current local date."""
        local_times = [(zone, timezone_now(zone, now)) for zone in self._timezones]
        dates = tuple(local_now.date().isoformat() for _, local_now in local_times)
        if dates == self._last_observed_dates:
            return
        with self._database(write=True) as connection:
            for (zone, local_now), local_date in zip(local_times, dates):
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO observed_boots (zone, local_date, boot_id) VALUES (?, ?, ?)",
                    (zone, local_date, self._boot_id),
                )
                if inserted.rowcount:
                    connection.execute(
                        """INSERT INTO launch_days (zone, local_date, launch_count, last_boot_id, last_launch_at)
                            VALUES (?, ?, 1, ?, ?)
                            ON CONFLICT (zone, local_date) DO UPDATE SET
                                launch_count = launch_count + 1,
                                last_boot_id = excluded.last_boot_id,
                                last_launch_at = excluded.last_launch_at""",
                        (zone, local_date, self._boot_id, local_now.isoformat()),
                    )
        self._last_observed_dates = dates

    def view(self, character_id: str, timezone_name: str, now: datetime) -> dict:
        """Read the launch count and the character's receipts for the requested local day."""
        if not isinstance(character_id, str):
            raise CalendarLedgerError("角色编号格式无效。")
        local_date = timezone_now(timezone_name, now).date().isoformat()
        state = default_state()
        state["localDate"] = local_date
        with self._database() as connection:
            launch = connection.execute(
                """SELECT launch_count, last_boot_id, last_launch_at FROM launch_days
                    WHERE zone = ? AND local_date = ?""",
                (timezone_name, local_date),
            ).fetchone()
            if launch is not None:
                state["launchCount"], state["lastBootId"], state["lastLaunchAt"] = launch
            if character_id:
                receipts = connection.execute(
                    "SELECT event_key, value FROM receipts WHERE character_id = ? AND local_date = ?",
                    (character_id, local_date),
                )
                state["sentEvents"] = {key: json.loads(value) for key, value in receipts}
        return state

    def record(self, character_id: str, event_keys: list[str], *, status: str, now: datetime) -> None:
        """Atomically save the batch for its original character and dates."""
        _nonempty_id(character_id, "角色编号")
        if status not in _STATUSES:
            raise CalendarLedgerError("日历事件状态无效。")
        value = _encoded({"status": status, "updatedAt": timezone_now("UTC", now).isoformat()})
        receipts = [(character_id, _event_date(key), key, value) for key in event_keys]
        with self._database(write=True) as connection:
            connection.executemany(
                """INSERT INTO receipts (character_id, local_date, event_key, value)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (character_id, local_date, event_key) DO UPDATE SET value = excluded.value""",
                receipts,
            )

    def adopt_legacy(self, character_id: str) -> None:
        """Assign the staged legacy receipts to the first actual character, once."""
        _nonempty_id(character_id, "角色编号")
        with self._database(write=True) as connection:
            marker = connection.execute(
                "SELECT value FROM metadata WHERE key = ?", (_MIGRATION_KEY,),
            ).fetchone()
            if marker is None:
                raise CalendarLedgerError("日历状态库缺少迁移记录。")
            pending = json.loads(marker[0])
            if pending is None:
                return
            connection.executemany(
                "INSERT OR IGNORE INTO receipts (character_id, local_date, event_key, value) VALUES (?, ?, ?, ?)",
                ((character_id, _event_date(key), key, _encoded(value)) for key, value in pending.items()),
            )
            connection.execute("UPDATE metadata SET value = ? WHERE key = ?", ("null", _MIGRATION_KEY))
