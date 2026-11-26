"""Per-character calendar preferences stored through the Sakura config SDK."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from threading import RLock

from calendar_core import CalendarSettingsError, DEFAULT_SETTINGS, normalize_settings


AVAILABLE_TIME_ZONES = ("Asia/Shanghai", "Asia/Tokyo", "local")
_PROFILES_KEY = "profiles"
_LEGACY_OWNER_KEY = "legacy_profile_owner"


def _role_id(value) -> str:
    return value if isinstance(value, str) and value.strip() else ""


def _timezone_for(values: Mapping) -> str:
    timezone = values.get("timezone", DEFAULT_SETTINGS["timezone"])
    return timezone if isinstance(timezone, str) and timezone in AVAILABLE_TIME_ZONES else "local"


def _safe_settings(values) -> dict:
    if not isinstance(values, Mapping):
        return normalize_settings(None)
    try:
        return normalize_settings({**values, "timezone": _timezone_for(values)})
    except CalendarSettingsError:
        # Keep an invalid profile inactive. In particular, fallback events
        # should not be sent just because an invalid profile had enabled=True.
        return normalize_settings(None)


class CalendarProfiles:
    """Read and write per-character settings, with one-time legacy adoption."""

    def __init__(self, config):
        self._config = config
        self._lock = RLock()
        self._accept_config(config.get())
        config.on_change(self._accept_config)

    def _accept_config(self, values) -> str:
        # SDK configuration callbacks can run synchronously inside update().
        with self._lock:
            self._raw = deepcopy(dict(values)) if isinstance(values, Mapping) else {}
        return "applied"

    def _profiles(self) -> dict:
        raw = self._raw.get(_PROFILES_KEY)
        return dict(raw) if isinstance(raw, Mapping) else {}

    @property
    def legacy_timezone(self) -> str:
        with self._lock:
            return _timezone_for(self._raw)

    def adopt_legacy(self, character_id: str) -> str:
        """Return the original owner, assigning unclaimed legacy settings once."""
        with self._lock:
            self._accept_config(self._config.get())
            owner = _role_id(self._raw.get(_LEGACY_OWNER_KEY))
            character = _role_id(character_id)
            if owner or not character:
                return owner
            profiles = self._profiles()
            inherited = _safe_settings(self._raw)
            existing = profiles.get(character)
            if isinstance(existing, Mapping):
                inherited = {**existing, **_safe_settings({**inherited, **existing})}
            profiles[character] = inherited
            result = self._config.update({_PROFILES_KEY: profiles, _LEGACY_OWNER_KEY: character})
            if result != "applied":
                raise CalendarSettingsError("无法保存旧日历设置的角色绑定。")
            return character

    def settings_for(self, character_id: str) -> dict:
        """Return detached, validated values for a role or inactive defaults."""
        with self._lock:
            character = _role_id(character_id)
            raw = self._profiles().get(character) if character else None
            return _safe_settings(raw)

    def update(self, character_id: str, changes: Mapping) -> str:
        """Validate and apply a patch to one role, leaving other settings intact."""
        character = _role_id(character_id)
        if not character:
            raise CalendarSettingsError("当前角色尚未就绪。")
        if not isinstance(changes, Mapping) or any(key not in DEFAULT_SETTINGS for key in changes):
            raise CalendarSettingsError("角色日历设置包含未知字段。")
        if "timezone" in changes and changes["timezone"] not in AVAILABLE_TIME_ZONES:
            raise CalendarSettingsError("时区请选择北京、东京或跟随 Windows 时间。")
        if not changes:
            return "applied"
        with self._lock:
            self._accept_config(self._config.get())
            profiles = self._profiles()
            current = profiles.get(character)
            candidate = normalize_settings({**_safe_settings(current), **changes})
            profiles[character] = {**current, **candidate} if isinstance(current, Mapping) else candidate
            return self._config.update({_PROFILES_KEY: profiles})

