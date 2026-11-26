"""Calendar companion adapter for Sakura Plugin API v4."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
import time
from typing import Any, Mapping
from uuid import uuid4
import webbrowser

from calendar_core import (
    CalendarSettingsError,
    EVENT_TYPES,
    due_events,
    timezone_now,
)
from calendar_ledger import CalendarLedger
from calendar_profiles import CalendarProfiles
from calendar_web import CalendarProfileChanged, CalendarWeb
from holidays import HOLIDAY_IDS, HOLIDAY_REGIONS, holiday_catalog
from host_boot import windows_host_boot_id


PROVIDER_ID = "calendar.awareness"
GREETING_MARKER = "（日历问候）"
CHECK_INTERVAL = 2.0
JOB_TIMEOUT = 120.0
SETTING_KEYS = ("enabled", *(f"{kind}_enabled" for kind in EVENT_TYPES), "timezone")
BEGIN_REJECTIONS = {
    "ASSISTANT_NOT_READY", "CHAT_BUSY", "CHAT_CHARACTER_NOT_CURRENT", "CHAT_SESSION_STALE",
    "CHAT_START_FAILED", "INVALID_CHAT_PAYLOAD", "CHAT_EXECUTION_LIMIT_EXCEEDED",
    "RUNTIME_UPDATE_BUSY", "CHARACTER_SWITCH_IN_PROGRESS",
}
FAILED_TURNS = {
    "ASSISTANT_NOT_READY", "CHAT_FAILED", "OPERATION_CANCELLED", "PROVIDER_REQUEST_FAILED",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _character_info(facts):
    character_id = facts.get("characterId")
    if not isinstance(character_id, str) or not character_id.strip():
        return None
    name = facts.get("characterName")
    return {"id": character_id, "name": name if isinstance(name, str) and name.strip() else character_id}


@dataclass
class Greeting:
    character_id: str
    session_id: str
    date: str
    events: list[dict[str, Any]]
    job_id: str = ""
    deadline: float = 0.0


class CalendarPlugin:
    def __init__(self, *, boot_id=None, clock=_now, start_worker=True):
        self._boot_id = boot_id
        self._clock = clock
        self._start_worker = start_worker
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._pending: Greeting | None = None
        self._worker: threading.Thread | None = None
        self._web: CalendarWeb | None = None
        self._role_status: dict[str, str] = {}
        self._legacy_adopted = False

    def setup(self, context):
        self._profiles = CalendarProfiles(context.config)
        self._chat = context.get("sakura.host.chat")
        self._conversation = context.get("sakura.host.conversation")
        self._log = context.get("sakura.host.logging")
        if self._boot_id is None:
            self._boot_id = windows_host_boot_id(Path(sys.executable).parent.parent)
        self._ledger = None
        self._status = "无法识别 Sakura 应用进程，主动问候已暂停。"
        if self._boot_id:
            try:
                ledger = CalendarLedger(
                    context.data_path("calendar.sqlite3"), context.data_path("state.json"), self._boot_id,
                    legacy_timezone=self._profiles.legacy_timezone,
                )
                ledger.observe(self._clock())
                self._ledger = ledger
                self._status = "日历已就绪。"
            except (OSError, ValueError) as error:
                self._status = "无法读取或保存日历状态，主动问候已暂停。"
                self._warn(error)

        context.get("sakura.host.context").register(
            {"providerId": PROVIDER_ID, "scope": "turn", "order": 87, "failurePolicy": "skip"},
            self._context_fragment,
        )
        context.get("sakura.host.settings").register(
            self.descriptor(), load=self.load_settings,
            actions={"openEvents": self.open_events},
        )
        context.effect(self.close)
        if self._start_worker:
            self._worker = threading.Thread(target=self._run, name="SakuraCalendar", daemon=True)
            self._worker.start()

    @staticmethod
    def descriptor():
        fields = [
            {"key": "characterName", "label": "当前角色", "type": "readonly", "default": "—"},
            {"key": "status", "label": "运行状态", "type": "readonly", "default": ""},
            {"key": "todayLaunchCount", "label": "今日启动次数", "type": "readonly", "default": "—"},
        ]
        return {
            "sectionId": "calendar", "title": "日历感知", "order": 87, "fields": fields,
            "actions": [{"actionId": "openEvents", "label": "管理日历事件"}],
        }

    def load_settings(self):
        character = _character_info(self._chat.current())
        with self._lock:
            character_id = character["id"] if character else ""
            settings = self._settings_for(character_id)
            state = self._ledger.view(character_id, settings["timezone"], self._clock()) if self._ledger and character else None
            count = state["launchCount"] if state else 0
            return {
                "characterName": character["name"] if character else "—",
                "todayLaunchCount": str(count) if count else "—",
                "status": self._role_status.get(character_id, self._status) if self._ledger else self._status,
            }

    def _settings_for(self, character_id):
        if character_id and not self._legacy_adopted:
            owner = self._profiles.adopt_legacy(character_id)
            if self._ledger is not None and owner:
                self._ledger.adopt_legacy(owner)
            self._legacy_adopted = True
        return self._profiles.settings_for(character_id)

    def _editable_character(self, expected_character_id):
        character = _character_info(self._chat.current())
        if not character or (expected_character_id is not None and character["id"] != expected_character_id):
            raise CalendarProfileChanged("当前角色已切换，请在新角色的日历中重新操作。")
        return character

    def save_settings(self, values, expected_character_id=None):
        character = self._editable_character(expected_character_id)
        with self._lock:
            if not isinstance(values, Mapping) or not values or set(values) - set(SETTING_KEYS):
                raise CalendarSettingsError("角色日历设置无效。")
            self._settings_for(character["id"])
            self._save_profile(character["id"], values)
            return {"applicationState": "applied"}

    def open_events(self, _values):
        with self._lock:
            if self._closed.is_set():
                return {"message": "日历插件已关闭。"}
            if self._web is None:
                self._web = CalendarWeb(
                    self.event_state, self.save_event, self.delete_event,
                    save_holidays=self.save_holidays, save_settings=self.save_settings,
                )
            url = self._web.url
        if webbrowser.open(url):
            return {"message": "已在浏览器打开日历事件管理。"}
        return {"message": f"请在浏览器打开 {url}"}

    def event_state(self):
        character = _character_info(self._chat.current())
        with self._lock:
            return self._event_snapshot(character)

    def _event_snapshot(self, character):
        settings = self._settings_for(character["id"] if character else "")
        zone = settings["timezone"]
        today = timezone_now(zone, self._clock()).date()
        return {
            "character": character,
            "settings": {key: settings[key] for key in SETTING_KEYS},
            "events": {kind: settings[f"{kind}_events"] for kind in EVENT_TYPES},
            "timezone": zone,
            "today": today.isoformat(),
            "holidays": {
                "region": settings["holiday_region"],
                "reminders": settings["holiday_reminders"],
                "catalogs": {region: holiday_catalog(region, today.year) for region in ("cn", "jp")},
            },
        }

    def _save_profile(self, character_id, changes):
        if self._closed.is_set():
            raise CalendarSettingsError("日历插件已关闭。")
        if self._profiles.update(character_id, changes) != "applied":
            raise RuntimeError("Calendar profile settings could not be applied.")

    def save_holidays(self, values, expected_character_id=None):
        character = self._editable_character(expected_character_id)
        character_id = character["id"]
        with self._lock:
            settings = self._settings_for(character_id)
            if set(values) == {"region"}:
                region = values["region"]
                if region not in HOLIDAY_REGIONS:
                    raise CalendarSettingsError("请选择关闭、中国或日本。")
                changes = {"holiday_region": region}
            elif set(values) == {"id", "enabled"}:
                holiday_id = values["id"]
                if not isinstance(holiday_id, str) or holiday_id not in HOLIDAY_IDS:
                    raise CalendarSettingsError("找不到这个节日。")
                if holiday_id.split(".", 1)[0] != settings["holiday_region"]:
                    raise CalendarSettingsError("请先选择这个节日所在的国家。")
                enabled = values["enabled"]
                if type(enabled) is not bool:
                    raise CalendarSettingsError("节日提醒的开关无效。")
                reminders = set(settings["holiday_reminders"])
                if enabled:
                    reminders.add(holiday_id)
                else:
                    reminders.discard(holiday_id)
                changes = {"holiday_reminders": sorted(reminders)}
            else:
                raise CalendarSettingsError("节日提醒设置无效。")
            self._save_profile(character_id, changes)
            return self._event_snapshot(character)

    def save_event(self, kind, event, expected_character_id=None):
        character = self._editable_character(expected_character_id)
        with self._lock:
            event_list = self._editable_events(character["id"], kind)
            existing = None
            index = len(event_list)
            if "id" in event:
                index = self._event_index(event_list, event["id"])
                existing = event_list[index]
            message = event.get("message")
            if not isinstance(message, str) or not message.strip():
                field = "日子的意义" if kind == "annual" else "描述"
                raise CalendarSettingsError(f"请填写{field}。")
            item = {
                "id": existing["id"] if existing else uuid4().hex,
                "enabled": event.get("enabled", existing["enabled"] if existing else True),
                "message": message,
            }
            if kind == "daily":
                item.update(label="每日提醒", time=event.get("time"))
            elif kind == "annual":
                label = event.get("label")
                if not isinstance(label, str) or not label.strip():
                    raise CalendarSettingsError("请填写日子的名称。")
                item.update(label=label, date=event.get("date"), time=existing["time"] if existing else None)
            else:
                if "time" not in event:
                    raise CalendarSettingsError("请选择指定时间或任意时间。")
                item.update(label=event.get("label", ""), date=event.get("date"), time=event["time"])
                if existing and existing.get("repeatAnnually") and event.get("repeatAnnually") is True:
                    item["repeatAnnually"] = True
            event_list[index:index + 1] = [item]
            self._save_profile(character["id"], {f"{kind}_events": event_list})
            return self._event_snapshot(character)

    def delete_event(self, kind, event_id, expected_character_id=None):
        character = self._editable_character(expected_character_id)
        with self._lock:
            event_list = self._editable_events(character["id"], kind)
            del event_list[self._event_index(event_list, event_id)]
            self._save_profile(character["id"], {f"{kind}_events": event_list})
            return self._event_snapshot(character)

    def _editable_events(self, character_id, kind):
        if kind not in EVENT_TYPES:
            raise CalendarSettingsError("请选择事件类别。")
        return self._settings_for(character_id)[f"{kind}_events"]

    @staticmethod
    def _event_index(events, event_id):
        for index, item in enumerate(events):
            if item["id"] == event_id:
                return index
        raise CalendarSettingsError("找不到这个事件，请刷新列表。")

    def _context_fragment(self, request):
        character_id = request.get("character_id")
        if not isinstance(character_id, str) or not character_id:
            return []
        with self._lock:
            # Context can be requested for an older turn. The request identity
            # determines its settings and it cannot claim the legacy profile.
            settings = self._profiles.settings_for(character_id)
            if not settings["enabled"]:
                return []
            now = self._clock()
            local = timezone_now(settings["timezone"], now)
            today = local.date().isoformat()
            state = self._ledger.view(character_id, settings["timezone"], now) if self._ledger else None
            count = state["launchCount"] if state and state["localDate"] == today else 0
            pending = self._pending
            is_current_greeting = (
                pending is not None and request.get("current_input") == GREETING_MARKER
                and character_id == pending.character_id and pending.date == today
            )
            lines = []
            if is_current_greeting:
                lines.extend((
                    "本轮是你自己想起来并主动开口。",
                    f"「{GREETING_MARKER}」是本轮的触发标记。用户这轮没有提起下面的事项，也没有提出要你回答的问题。",
                    "用角色平时的语气和第一人称直接向用户说出你刚想起的事。自然地祝福、提醒或分享感受。",
                ))
            lines.append(f"当前本地时间 {local:%Y-%m-%d %H:%M}（{settings['timezone']}）。")
            if count:
                lines.append(f"今天是 Sakura 第 {count} 次启动。")
            else:
                lines.append("今日启动次数暂时无法确认。")
            if is_current_greeting:
                lines.append(
                    "启动次数只用来判断是否需要开机寒暄，与交谈、提醒或见面次数无关。不要向用户报出这个次数。"
                )
                if count > 1:
                    lines.append("今天已启动过，省去开机寒暄，直接说想起的事。")
                lines.append("你刚想起的事项：")
                for event in pending.events:
                    label, message = event["label"], event["message"]
                    if message and (not label or event["kind"] == "daily"):
                        lines.append(f"- {message}")
                    else:
                        lines.append(f"- {label}（{message}）" if message else f"- {label}")
                lines.append(
                    "以主动开口的角度自然说一句或几句。避免说成「又是那件事吗」「你又提了」或「谢谢提醒」。"
                    "沿用桌面回复格式。保留已知事实，不编造用户先开口或此前提醒过的次数，不复述触发标记或内部说明。"
                )
            else:
                lines.append("日历事实供当前对话参考。请按当前话题回复，避免自行发起启动问候。")
        content = "\n".join(lines)
        return [{"id": PROVIDER_ID, "content": content, "priority": 87,
                 "budgetHint": len(content) + 16, "sensitivity": "private"}]

    def _run(self):
        while not self._closed.wait(CHECK_INTERVAL):
            try:
                self._tick()
            except (OSError, ValueError) as error:
                with self._lock:
                    self._ledger = None
                    pending, self._pending = self._pending, None
                    self._status = "无法读取或保存日历状态，主动问候已暂停。"
                if pending:
                    self._release(pending.job_id)
                self._warn(error)
            except Exception as error:
                self._warn(error)

    def _tick(self):
        with self._lock:
            if self._closed.is_set() or self._ledger is None:
                return
        facts = self._chat.current()
        character = _character_info(facts)
        character_id = character["id"] if character else ""
        session_id = facts.get("sessionId")
        now = self._clock()
        with self._lock:
            if self._closed.is_set() or self._ledger is None:
                return
            self._ledger.observe(now)
            pending = self._pending
            poll_existing = pending is not None
            settings = self._settings_for(character_id)
            if not poll_existing and (not character_id or not session_id or not facts.get("idle")
                                      or not settings["enabled"]):
                return
            state = self._ledger.view(character_id, settings["timezone"], now) if character_id else None
            if pending:
                # A category change applies to the next submission. Cancel the
                # old job if its owning character or conversation has changed.
                can_poll = bool(
                    settings["enabled"] and character_id == pending.character_id and session_id == pending.session_id
                    and state and state["localDate"] == pending.date
                )
            elif state:
                pending = self._reserve_greeting(character_id, session_id, settings, state, now)
                if pending is None:
                    return
                can_poll = True
            else:
                return
        if poll_existing:
            self._poll(pending, now, can_poll)
        else:
            self._begin(pending, now)

    def _reserve_greeting(self, character_id, session_id, settings, state, now):
        events = due_events(settings, state, now=now)
        if not events:
            return None
        # Use the latest built-in greeting if its time window overlaps another.
        # User-authored reminders are independent even when several are due.
        daily = [item for item in events if item["kind"] == "daily" and not item["message"]]
        obsolete = sorted(daily, key=lambda item: (item["time"], item["id"]))[:-1]
        selected = [item for item in events if item not in obsolete][:4]
        if obsolete:
            self._ledger.record(character_id, [item["eventKey"] for item in obsolete], status="suppressed", now=now)
        self._ledger.record(character_id, [item["eventKey"] for item in selected], status="inflight", now=now)
        self._pending = Greeting(character_id, session_id, state["localDate"], selected)
        return self._pending

    def _begin(self, greeting, now):
        try:
            accepted = self._conversation.begin(greeting.character_id, GREETING_MARKER, None, "queued")
        except Exception as error:
            self._fail(greeting, now, error, BEGIN_REJECTIONS)
            return
        job_id = accepted.get("jobId") if isinstance(accepted, Mapping) else None
        if not isinstance(job_id, str) or not job_id:
            self._finish(greeting, now, None, "宿主回执缺少任务编号，今日暂不重发。")
            return
        with self._lock:
            if not self._closed.is_set() and self._pending is greeting:
                greeting.job_id = job_id
                greeting.deadline = time.monotonic() + JOB_TIMEOUT
                self._role_status[greeting.character_id] = "等待角色完成日历问候。"
                return
        self._release(job_id)

    def _poll(self, greeting, now, enabled):
        if not enabled:
            self._release(greeting.job_id)
            self._finish(greeting, now, None, "问候已停止，原事件今日暂不重发。")
            return
        try:
            result = self._conversation.poll(greeting.job_id)
        except Exception as error:
            self._fail(greeting, self._clock(), error, FAILED_TURNS)
            return
        if not isinstance(result, Mapping):
            self._release(greeting.job_id)
            self._finish(greeting, now, None, "宿主回执格式无效，今日暂不重发。")
            return
        if result.get("status") == "running":
            if time.monotonic() >= greeting.deadline:
                self._release(greeting.job_id)
                self._finish(greeting, now, None, "未收到完成回执，今日暂不重发。")
            return
        reply = result.get("result")
        if result.get("status") == "completed" and isinstance(reply, Mapping) and all(
            isinstance(reply.get(key), str) and reply[key].strip() for key in ("reply", "historyEntryId")
        ):
            self._finish(greeting, now, "sent", "日历问候已完成。")
        else:
            self._finish(greeting, now, None, "未确认问候已保存，今日暂不重发。")

    def _fail(self, greeting, now, error, retryable_codes):
        self._warn(error)
        if getattr(error, "code", "") in retryable_codes:
            self._finish(greeting, now, "failed", "问候失败，一分钟后可重新尝试。")
        else:
            self._finish(greeting, now, None, "问候结果无法确认，今日暂不重发。")

    def _finish(self, greeting, now, status, message):
        with self._lock:
            if self._pending is not greeting:
                return
            self._pending = None
            self._role_status[greeting.character_id] = message
            if status and self._ledger is not None:
                self._ledger.record(
                    greeting.character_id, [event["eventKey"] for event in greeting.events],
                    status=status, now=now,
                )

    def _warn(self, error):
        self._log.warning("日历插件发生错误", fields={
            "error_type": type(error).__name__, "reason_code": getattr(error, "code", ""),
        })

    def _release(self, job_id):
        if job_id:
            try:
                self._conversation.release(job_id)
            except Exception as error:
                self._warn(error)

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1.0)
        with self._lock:
            pending, self._pending = self._pending, None
            web, self._web = self._web, None
        if web:
            web.close()
        if pending:
            self._release(pending.job_id)
