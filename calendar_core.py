"""Pure calendar and startup-state logic for the Sakura calendar prototype.

The module deliberately has no Sakura imports.  The host adapter supplies the
current time, a stable host boot id, and the persisted state path.  This keeps
the rules deterministic and makes them testable before installing the plugin.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from holidays import HOLIDAY_IDS, HOLIDAY_REGIONS, holiday_catalog


SCHEMA_VERSION = 1
EVENT_TYPES = ("daily", "annual", "custom")
RETRY_DELAY = timedelta(seconds=60)
REMINDER_WINDOW = timedelta(minutes=10)
DEFAULT_TIMEZONE = "Asia/Shanghai"
FIXED_TIMEZONE_HOURS = {"Asia/Shanghai": 8, "Asia/Tokyo": 9}
DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "daily_enabled": False,
    "annual_enabled": False,
    "custom_enabled": False,
    "timezone": DEFAULT_TIMEZONE,
    "daily_events": [
        {"id": "morning", "label": "早安", "time": "08:00", "enabled": True},
        {"id": "noon", "label": "午安", "time": "12:00", "enabled": True},
        {"id": "evening", "label": "晚安", "time": "21:00", "enabled": True},
    ],
    "annual_events": [],
    "custom_events": [],
    "holiday_region": "off",
    "holiday_reminders": [],
}


class CalendarSettingsError(ValueError):
    """Raised when a settings object cannot be used safely."""


def _copy_default_settings() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_SETTINGS)


def _string(value: Any, field: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str):
        raise CalendarSettingsError(f"{field} 必须是文本。")
    value = value.strip()
    if not value or len(value) > maximum:
        raise CalendarSettingsError(f"{field} 不能为空且最多 {maximum} 个字符。")
    return value


def _optional_string(value: Any, field: str, *, maximum: int = 200) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CalendarSettingsError(f"{field} 必须是文本。")
    value = value.strip()
    if len(value) > maximum:
        raise CalendarSettingsError(f"{field} 最多 {maximum} 个字符。")
    return value


def _parse_time(value: Any, field: str) -> time:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value.strip()):
        raise CalendarSettingsError(f"{field} 必须是 HH:MM 格式。")
    hour, minute = (int(part) for part in value.split(":", 1))
    return time(hour, minute)


def _parse_month_day(value: Any, field: str) -> tuple[int, int]:
    if isinstance(value, str):
        match = re.fullmatch(r"([0-9]{2})-([0-9]{2})", value.strip())
        if match:
            month, day = int(match.group(1)), int(match.group(2))
        else:
            raise CalendarSettingsError(f"{field} 必须是 MM-DD 格式。")
    elif isinstance(value, Mapping):
        month, day = value.get("month"), value.get("day")
        if type(month) is not int or type(day) is not int:
            raise CalendarSettingsError(f"{field} 的月份和日期必须是整数。")
    else:
        raise CalendarSettingsError(f"{field} 必须是 MM-DD 格式。")
    try:
        date(2024, month, day)
    except ValueError as error:
        raise CalendarSettingsError(f"{field} 不是有效日期。") from error
    return month, day


def _normalize_event(raw: Any, kind: str, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CalendarSettingsError(f"{kind} 事件 {index + 1} 必须是对象。")
    event_id = _string(raw.get("id", f"{kind}-{index + 1}"), f"{kind} 事件编号", maximum=80)
    label_field = f"{kind} 事件名称"
    if kind == "custom":
        label = _optional_string(raw.get("label"), label_field, maximum=120)
    else:
        label = _string(raw.get("label", raw.get("id", "日历事件")), label_field, maximum=120)
    enabled = raw.get("enabled", True)
    if type(enabled) is not bool:
        raise CalendarSettingsError(f"{kind} 事件 {event_id} 的启用状态无效。")
    result: dict[str, Any] = {"id": event_id, "label": label, "enabled": enabled}
    if kind == "annual":
        month, day = _parse_month_day(raw.get("date"), f"年度事件 {event_id} 的日期")
        result["date"] = f"{month:02d}-{day:02d}"
    elif kind == "custom":
        event_date = _string(raw.get("date"), f"自定义事件 {event_id} 的日期", maximum=10)
        repeat_annually = raw.get("repeatAnnually", False)
        if type(repeat_annually) is not bool:
            raise CalendarSettingsError(f"自定义事件 {event_id} 的重复设置无效。")
        if event_date == "daily":
            result["date"] = "daily"
            repeat_annually = False
        elif repeat_annually:
            month, day = _parse_month_day(event_date, f"自定义事件 {event_id} 的日期")
            result["date"] = f"{month:02d}-{day:02d}"
        else:
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", event_date):
                    raise ValueError("Expected YYYY-MM-DD")
                result["date"] = date.fromisoformat(event_date).isoformat()
            except ValueError as error:
                raise CalendarSettingsError(f"自定义事件 {event_id} 的日期必须是 YYYY-MM-DD。") from error
        result["repeatAnnually"] = repeat_annually
    if kind == "daily":
        result["time"] = _parse_time(raw.get("time"), f"每日事件 {event_id} 的时间").isoformat(timespec="minutes")
    else:
        value = raw.get("time", "09:00")
        result["time"] = None if value is None else _parse_time(value, f"{kind} 事件 {event_id} 的时间").isoformat(
            timespec="minutes",
        )
    result["message"] = _optional_string(raw.get("message", ""), f"{kind} 事件 {event_id} 的提醒内容", maximum=500)
    if "id" not in raw:
        identity_parts = [kind, label, result.get("date"), result["time"]]
        if kind == "custom" and not label:
            identity_parts.append(result["message"])
        identity = json.dumps(identity_parts, ensure_ascii=False)
        result["id"] = f"{kind}-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
    return result


def normalize_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return validated settings with defaults filled in."""

    result = _copy_default_settings()
    if raw is not None:
        if not isinstance(raw, Mapping):
            raise CalendarSettingsError("日历设置必须是对象。")
        result.update({key: raw[key] for key in DEFAULT_SETTINGS if key in raw})
    for key in ("enabled", "daily_enabled", "annual_enabled", "custom_enabled"):
        if type(result[key]) is not bool:
            raise CalendarSettingsError(f"{key} 必须是布尔值。")
    timezone_name = _string(result.get("timezone", DEFAULT_TIMEZONE), "时区", maximum=80)
    _timezone(timezone_name)
    result["timezone"] = timezone_name
    if result["holiday_region"] not in HOLIDAY_REGIONS:
        raise CalendarSettingsError("请选择关闭、中国或日本作为节日来源。")
    reminders = result["holiday_reminders"]
    if not isinstance(reminders, list) or any(
        not isinstance(item, str) or item not in HOLIDAY_IDS for item in reminders
    ):
        raise CalendarSettingsError("节日提醒设置包含未知节日。")
    result["holiday_reminders"] = sorted(set(reminders))
    for key, kind in (("daily_events", "daily"), ("annual_events", "annual"), ("custom_events", "custom")):
        values = result.get(key, [])
        if not isinstance(values, list):
            raise CalendarSettingsError(f"{key} 必须是数组。")
        normalized = [_normalize_event(value, kind, index) for index, value in enumerate(values)]
        ids = [value["id"] for value in normalized]
        if len(ids) != len(set(ids)):
            raise CalendarSettingsError(f"{key} 中的事件编号不能重复。")
        result[key] = normalized
    return result


def default_state() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "localDate": "",
        "launchCount": 0,
        "lastBootId": "",
        "lastLaunchAt": "",
        "sentEvents": {},
    }


def normalize_state(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    result = default_state()
    if isinstance(raw, Mapping):
        result.update({key: raw[key] for key in result if key in raw})
    if type(result["launchCount"]) is not int or result["launchCount"] < 0:
        result["launchCount"] = 0
    if not isinstance(result["sentEvents"], Mapping):
        result["sentEvents"] = {}
    else:
        result["sentEvents"] = {
            str(key): dict(value) if isinstance(value, Mapping) else {"status": str(value)}
            for key, value in result["sentEvents"].items()
        }
    return result


class JsonStateStore:
    """Small atomic JSON store used by the plugin adapter."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return default_state()
        if (
            not isinstance(raw, Mapping)
            or raw.get("schemaVersion", SCHEMA_VERSION) != SCHEMA_VERSION
            or not isinstance(raw.get("sentEvents", {}), Mapping)
        ):
            raise ValueError("日历状态文件格式无效。")
        return normalize_state(raw)

    def save(self, state: Mapping[str, Any]) -> None:
        normalized = normalize_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(normalized, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _timezone(name: str) -> tzinfo | None:
    if name == "local":
        return None
    if name == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        if name in FIXED_TIMEZONE_HOURS:
            # Sakura's embedded Windows Python has no IANA time zone database.
            return timezone(timedelta(hours=FIXED_TIMEZONE_HOURS[name]), name)
        raise CalendarSettingsError(f"不支持的时区 {name}。") from error


def timezone_now(timezone_name: str, now: datetime | None = None) -> datetime:
    """Convert a timestamp to the configured timezone."""

    zone = _timezone(timezone_name)
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone)


def register_startup(
    state: Mapping[str, Any] | None,
    *,
    boot_id: str | None,
    timezone_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record one Sakura application startup.

    ``boot_id`` must identify the host application lifetime.  Calling this
    repeatedly with the same id models plugin reloads and does not increment
    the count.  A missing id is replaced with a per-process value for the
    standalone prototype, while the Sakura adapter should pass a stable host
    identity when one is available.
    """

    result = normalize_state(state)
    local_now = timezone_now(timezone_name, now)
    today = local_now.date().isoformat()
    effective_boot_id = str(boot_id or f"process:{os.getpid()}")
    if result["localDate"] != today:
        result["localDate"] = today
        result["launchCount"] = 1
        result["sentEvents"] = {}
    elif result["lastBootId"] != effective_boot_id:
        result["launchCount"] += 1
    else:
        return result
    result["lastBootId"] = effective_boot_id
    result["lastLaunchAt"] = local_now.isoformat()
    return result


def _event_key(local_date: str, kind: str, event_id: str) -> str:
    return f"{local_date}|{kind}|{event_id}"


def _enabled_for_kind(settings: Mapping[str, Any], kind: str) -> bool:
    return bool(settings.get("enabled")) and bool(settings.get(f"{kind}_enabled"))


def _matches_date(event: Mapping[str, Any], kind: str, local_date: date) -> bool:
    event_date = event.get("date")
    if kind == "daily" or event_date == "daily":
        return True
    if kind == "annual" or event.get("repeatAnnually"):
        return event_date == f"{local_date.month:02d}-{local_date.day:02d}"
    return event_date == local_date.isoformat()


def _already_reserved(record: Mapping[str, Any], now: datetime) -> bool:
    status = record.get("status")
    if status in {"sent", "inflight", "suppressed"}:
        return True
    if status == "failed":
        updated_at = record.get("updatedAt")
        if isinstance(updated_at, str):
            try:
                failed_at = datetime.fromisoformat(updated_at)
            except ValueError:
                return False
            if failed_at.tzinfo is not None:
                # Compare instants even if the local clock crossed a DST transition.
                elapsed = now.astimezone(timezone.utc) - failed_at.astimezone(timezone.utc)
                return elapsed < RETRY_DELAY
    return False


def due_events(
    settings: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    now: datetime | None = None,
    include_future: bool = False,
) -> list[dict[str, Any]]:
    """Return enabled, due, unsent events for the local date.

    Preset daily greetings are limited to the first launch of the local day.
    Daily events and timed custom events are eligible within ten minutes of
    their scheduled local time, on the event's local date.
    A settings preview may set ``include_future`` to bypass time and launch gates.
    """

    normalized = normalize_settings(settings)
    local_now = timezone_now(normalized["timezone"], now)
    local_date = local_now.date()
    today = local_date.isoformat()
    state_view = normalize_state(state)
    first_launch = state_view["localDate"] == today and state_view["launchCount"] == 1
    local_wall_time = local_now.replace(tzinfo=None)
    result: list[dict[str, Any]] = []

    def add_if_unsent(event, kind):
        event_key = _event_key(today, kind, event["id"])
        record = state_view["sentEvents"].get(event_key)
        if record is None or not _already_reserved(record, local_now):
            result.append({
                **event, "kind": kind, "eventKey": event_key, "localDate": today,
                "launchCount": state_view["launchCount"],
            })

    for kind, key in (("daily", "daily_events"), ("annual", "annual_events"), ("custom", "custom_events")):
        if not _enabled_for_kind(normalized, kind):
            continue
        for event in normalized[key]:
            if not event["enabled"] or not _matches_date(event, kind, local_date):
                continue
            if kind == "daily" and not include_future and not first_launch and not event["message"]:
                continue
            event_time = event["time"]
            if not include_future and event_time is not None:
                scheduled_time = time.fromisoformat(event_time)
                if kind == "annual":
                    if local_now.time() < scheduled_time:
                        continue
                elif abs(local_wall_time - datetime.combine(local_date, scheduled_time)) > REMINDER_WINDOW:
                    continue
            add_if_unsent(event, kind)
    if normalized["enabled"] and normalized["holiday_reminders"]:
        selected_ids = set(normalized["holiday_reminders"])
        for event in holiday_catalog(normalized["holiday_region"], local_date.year):
            if (event["date"] == today or today in event.get("additionalDates", ())) and event["id"] in selected_ids:
                add_if_unsent({**event, "time": None, "enabled": True}, "holiday")
    return result


def mark_event(
    state: Mapping[str, Any],
    event_key: str,
    *,
    status: str,
    now: datetime | None = None,
    detail: str = "",
) -> dict[str, Any]:
    """Record an event state. Confirmed failures can be retried after a delay."""

    if status not in {"pending", "inflight", "sent", "failed", "suppressed"}:
        raise ValueError("事件状态无效。")
    result = normalize_state(state)
    record: dict[str, Any] = {"status": status}
    if now is not None:
        record["updatedAt"] = now.isoformat()
    if detail:
        record["detail"] = detail[:500]
    result["sentEvents"][str(event_key)] = record
    return result


def clear_day(state: Mapping[str, Any]) -> dict[str, Any]:
    """Clear today's startup and send records for a manual test reset."""

    result = normalize_state(state)
    result["launchCount"] = 0
    result["lastBootId"] = ""
    result["lastLaunchAt"] = ""
    result["sentEvents"] = {}
    return result


def build_context(settings: Mapping[str, Any], state: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Build the private context fragment exposed to Sakura turns."""

    normalized = normalize_settings(settings)
    state_view = normalize_state(state)
    local_now = timezone_now(normalized["timezone"], now)
    return {
        "date": local_now.date().isoformat(),
        "time": local_now.strftime("%H:%M"),
        "timezone": normalized["timezone"],
        "launchCount": state_view["launchCount"],
        "isFirstLaunchToday": state_view["launchCount"] == 1,
        "enabled": normalized["enabled"],
        "enabledEventTypes": [kind for kind in EVENT_TYPES if _enabled_for_kind(normalized, kind)],
        "sentEventCount": sum(1 for record in state_view["sentEvents"].values() if record.get("status") == "sent"),
        "dueEvents": due_events(normalized, state_view, now=now),
    }


def new_boot_id() -> str:
    """Generate an explicit boot id for standalone tests and host adapters."""

    return uuid.uuid4().hex


__all__ = [
    "CalendarSettingsError",
    "DEFAULT_SETTINGS",
    "EVENT_TYPES",
    "JsonStateStore",
    "build_context",
    "clear_day",
    "default_state",
    "due_events",
    "mark_event",
    "new_boot_id",
    "normalize_settings",
    "normalize_state",
    "register_startup",
    "timezone_now",
]
