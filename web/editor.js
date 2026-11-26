"use strict";

const kinds = {
  daily: {title: "每日事件", empty: "还没有每日事件"},
  annual: {title: "年度事件", empty: "还没有年度事件"},
  custom: {title: "自定义事件", empty: "还没有自定义事件"},
};
const zoneNames = {"Asia/Shanghai": "北京时间", "Asia/Tokyo": "东京时间", local: "跟随 Windows 时间"};
const holidayRegions = {off: "关闭", cn: "中国", jp: "日本"};
const holidayCategories = {public: "法定公休", traditional: "传统节日", popular: "流行节庆", observance: "主题节日"};
const find = (id) => document.getElementById(id);
const editor = find("editor");
const form = find("event-form");
const deleteDialog = find("delete-dialog");
const nameInput = find("event-name");
const description = find("description");
const timeInput = find("event-time");
const dateMode = find("date-mode");
const timeMode = find("time-mode");
const yearSelect = find("calendar-year");
const monthSelect = find("calendar-month");
const dayGrid = find("calendar-days");
const editorError = find("editor-error");
const deleteError = find("delete-error");
const settingsInputs = [...document.querySelectorAll("[data-setting]")];
let activeCharacter = null;
let roleSettings = null;
let readingState = null;
let writing = false;
let today = "";
let editing = null;
let editorCharacterId = null;
let kind = null;
let deleting = null;
let calendar = null;
let holidayState = null;

class RequestError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function node(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text) result.textContent = text;
  return result;
}

function updatePageStatus(text, isError = false) {
  const status = find("status");
  status.textContent = text;
  status.toggleAttribute("data-error", isError);
}

function showError(target, message) {
  target.textContent = message;
  target.hidden = !message;
}

function parseDate(value) {
  if (typeof value !== "string") return null;
  const match = /^(?:(\d{4})-)?(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const [, year, month, day] = match.map(Number);
  if (month < 1 || month > 12 || day < 1 || day > monthLength(year || 2024, month)) return null;
  return {year, month, day};
}

function displayDate(value) {
  const date = parseDate(value);
  if (!date) return "";
  const year = date.year ? date.year + "年" : "";
  return year + date.month + "月" + date.day + "日";
}

function eventTitle(type, event) {
  if (type === "daily") return event.message || event.label || "每日提醒";
  return event.label || event.message || kinds[type].title;
}

function eventSchedule(type, event) {
  if (type === "daily") return "每日 " + event.time;
  if (type === "annual") return "每年 " + displayDate(event.date) + (event.time ? " · " + event.time : "");
  const date = event.date === "daily" ? "每日" :
    (event.repeatAnnually ? "每年 " : "") + displayDate(event.date);
  return date + " · " + (event.time || "任意时间");
}

function eventRow(type, event, characterId) {
  const row = node("li", "event-row");
  const details = node("div");
  const schedule = node("div", "event-schedule");
  schedule.append(node("span", "", eventSchedule(type, event)));
  if (event.enabled === false) schedule.append(node("span", "", "已停用"));
  details.append(schedule, node("p", "event-title", eventTitle(type, event)));
  if (type !== "daily" && event.label && event.message) {
    details.append(node("p", "event-description", event.message));
  }

  const actions = node("div", "event-actions");
  const edit = node("button", "link-button", "编辑");
  edit.type = "button";
  edit.addEventListener("click", () => openEditor(type, event, characterId));
  const remove = node("button", "link-button remove", "删除");
  remove.type = "button";
  remove.addEventListener("click", () => openDelete(type, event, characterId));
  actions.append(edit, remove);
  row.append(details, actions);
  return row;
}

function renderDate(state) {
  today = state.today || "";
  const todayLabel = find("today");
  const facts = [displayDate(today), zoneNames[state.settings?.timezone || state.timezone]].filter(Boolean);
  todayLabel.textContent = facts.join(" · ");
  todayLabel.hidden = !facts.length;
}

function renderEvents(state) {
  if (!state?.events || typeof state.events !== "object") {
    throw new Error("无法读取事件资料。");
  }

  const groups = find("groups");
  groups.replaceChildren();
  for (const [type, meta] of Object.entries(kinds)) {
    const group = node("section", "group " + type);
    const heading = node("h2", "", meta.title);
    heading.id = "heading-" + type;
    group.setAttribute("aria-labelledby", heading.id);
    group.append(heading);
    const entries = state.events[type];
    if (Array.isArray(entries) && entries.length) {
      const list = node("ul", "event-list");
      for (const event of entries) list.append(eventRow(type, event, activeCharacter.id));
      group.append(list);
    } else {
      group.append(node("p", "", meta.empty));
    }
    groups.append(group);
  }
  groups.hidden = false;
}

function holidayDate(event) {
  if (event.dateStatus === "not_occurring") return "今年无此日期";
  const additional = Array.isArray(event.additionalDates) ? event.additionalDates : [];
  const dates = [event.date, ...additional].map(displayDate).filter(Boolean);
  const date = [...new Set(dates)].join("、");
  if (date && event.dateStatus === "official") return date;
  if (date && event.dateStatus === "forecast") return "预计 " + date;
  return "暂未收录日期";
}

function setHolidayStatus(text, isError = false) {
  const status = find("holiday-status");
  status.textContent = text;
  status.toggleAttribute("data-error", isError);
}

function holidayRow(event, selected, index, characterId) {
  const row = node("li");
  const label = node("label", "holiday-option");
  const details = node("span", "holiday-details");
  const heading = node("span", "holiday-heading");
  heading.append(node("span", "holiday-title", event.label));
  const describedBy = [];
  if (Object.hasOwn(holidayCategories, event.category)) {
    const category = node("span", "holiday-category", holidayCategories[event.category]);
    category.id = "holiday-category-" + index;
    describedBy.push(category.id);
    heading.append(category);
  }
  const date = node("span", "holiday-date", holidayDate(event));
  date.id = "holiday-date-" + index;
  describedBy.push(date.id);
  heading.append(date);
  details.append(heading);
  if (typeof event.message === "string" && event.message.trim()) {
    const description = node("span", "holiday-description", event.message.trim());
    description.id = "holiday-description-" + index;
    describedBy.push(description.id);
    details.append(description);
  }

  const check = node("input");
  check.type = "checkbox";
  check.dataset.holidayId = event.id;
  check.checked = selected.has(event.id);
  check.setAttribute("role", "switch");
  check.setAttribute("aria-label", event.label);
  check.setAttribute("aria-describedby", describedBy.join(" "));
  check.addEventListener("change", () => saveHoliday({id: event.id, enabled: check.checked}, check, characterId));
  label.append(details, check);
  row.append(label);
  return row;
}

function renderHolidays(holidays) {
  const section = find("holidays");
  if (!holidays || !Object.hasOwn(holidayRegions, holidays.region)) {
    holidayState = null;
    find("holiday-list").replaceChildren();
    section.hidden = true;
    return;
  }
  holidayState = holidays;
  section.hidden = false;
  find("holiday-region").value = holidays.region;
  const list = find("holiday-list");
  list.replaceChildren();
  const active = holidays.region === "off" ? [] : holidays.catalogs?.[holidays.region] || [];
  const selected = new Set(holidays.reminders || []);
  active.forEach((event, index) => list.append(holidayRow(event, selected, index, activeCharacter.id)));
  list.hidden = holidays.region === "off";
  if (!list.hidden && !active.length) list.append(node("li", "section-note", "暂无可选节日。"));
}

async function saveHoliday(preference, source, characterId = activeCharacter?.id) {
  if (!beginWrite(characterId)) return;
  find("holidays").setAttribute("aria-busy", "true");
  setHolidayStatus("正在保存…");
  try {
    const state = await request("api/holidays", {characterId, ...preference});
    if (!matchesWrittenRole(state, characterId)) return;
    if (!state?.holidays || !Object.hasOwn(holidayRegions, state.holidays.region)) {
      throw new Error("没有收到更新后的节日设置，请重新打开事件管理。");
    }
    renderHolidays(state.holidays);
    setHolidayStatus("已保存节日设置。");
  } catch (error) {
    if (!await recoverRoleConflict(error)) {
      renderHolidays(holidayState);
      setHolidayStatus(error.message, true);
    }
  } finally {
    find("holidays").removeAttribute("aria-busy");
    finishWrite();
    if (activeCharacter?.id === characterId &&
        (document.activeElement === source || document.activeElement === document.body)) {
      const next = preference.id
        ? [...find("holiday-list").querySelectorAll("input")].find((check) => check.dataset.holidayId === preference.id)
        : find("holiday-region");
      next?.focus({preventScroll: true});
    }
  }
}

async function request(path, data, signal) {
  const options = data === undefined ? {signal} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data),
  };
  let response;
  let result;
  try {
    response = await fetch(path, options);
    result = await response.json();
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error("无法连接日历插件，请从 Sakura 重新打开事件管理。");
  }
  if (!response.ok) throw new RequestError(result?.error || "操作失败，请重试。", response.status);
  return result;
}

function characterOf(state) {
  const character = state?.character;
  return typeof character?.id === "string" && character.id ? character : null;
}

function setSettingsStatus(text, isError = false) {
  const status = find("settings-status");
  status.textContent = text;
  status.toggleAttribute("data-error", isError);
}

function renderSettings(settings) {
  roleSettings = settings;
  for (const control of settingsInputs) {
    const value = settings[control.dataset.setting];
    if (control.type === "checkbox") control.checked = value === true;
    else control.value = value;
  }
}

function closeDrafts() {
  const wasOpen = editor.open || deleteDialog.open;
  if (editor.open) editor.close();
  if (deleteDialog.open) deleteDialog.close();
  editorCharacterId = null;
  editing = null;
  kind = null;
  deleting = null;
  return wasOpen;
}

function renderState(state) {
  const character = characterOf(state);
  if (character && (!state.settings || !state.events)) {
    throw new Error("无法读取当前角色的日历设置。");
  }
  const changedRole = activeCharacter?.id !== character?.id;
  const discarded = changedRole && closeDrafts();
  activeCharacter = character;
  find("character-name").textContent = character?.name || character?.id || "";
  find("no-character").hidden = Boolean(character);
  find("role-settings").hidden = !character;
  if (changedRole) {
    setSettingsStatus("");
    setHolidayStatus("");
  }
  if (character) {
    renderDate(state);
    renderSettings(state.settings);
    renderEvents(state);
    renderHolidays(state.holidays);
  } else {
    roleSettings = null;
    renderDate({});
    find("groups").replaceChildren();
    find("groups").hidden = true;
    renderHolidays(null);
  }
  updateControlAvailability();
  return discarded;
}

function announceRoleChange(state) {
  const discarded = renderState(state);
  find("retry").hidden = true;
  updatePageStatus(discarded ? "已切换角色，旧角色未保存的修改已关闭。" : "");
}

function updateControlAvailability() {
  const disabled = !activeCharacter || writing;
  find("add-event").disabled = disabled;
  find("holiday-region").disabled = disabled;
  for (const control of settingsInputs) control.disabled = disabled;
  for (const control of document.querySelectorAll("#groups .event-actions button, #holiday-list input")) {
    control.disabled = disabled;
  }
}

function beginWrite(characterId) {
  if (writing || !characterId || activeCharacter?.id !== characterId) return false;
  writing = true;
  readingState?.abort();
  readingState = null;
  updateControlAvailability();
  return true;
}

function finishWrite() {
  writing = false;
  updateControlAvailability();
  pollRole();
}

function matchesWrittenRole(state, characterId) {
  if (characterOf(state)?.id === characterId) return true;
  announceRoleChange(state);
  return false;
}

async function recoverRoleConflict(error) {
  if (!(error instanceof RequestError) || error.status !== 409) return false;
  const discarded = renderState({character: null});
  const explanation = discarded ? "旧角色未保存的修改已关闭。" : "";
  try {
    await readRole({replace: true, duringWrite: true});
    find("retry").hidden = true;
    updatePageStatus(error.message + " " + explanation + "已刷新角色资料。", true);
  } catch {
    updatePageStatus(error.message + " " + explanation + "暂时无法刷新角色资料。", true);
    find("retry").hidden = false;
  }
  return true;
}

async function readRole({replace = false, duringWrite = false} = {}) {
  if (readingState || (writing && !duringWrite)) return;
  const controller = new AbortController();
  readingState = controller;
  try {
    const state = await request("api/state", undefined, controller.signal);
    if (readingState !== controller || controller.signal.aborted) return;
    if (replace) renderState(state);
    else if (characterOf(state)?.id !== activeCharacter?.id) announceRoleChange(state);
    else if (activeCharacter && state.character.name !== activeCharacter.name) {
      activeCharacter = state.character;
      find("character-name").textContent = activeCharacter.name || activeCharacter.id;
    }
  } finally {
    if (readingState === controller) readingState = null;
  }
}

function pollRole() {
  if (!document.hidden) void readRole().catch(() => {});
}

async function load() {
  find("retry").hidden = true;
  updatePageStatus("正在读取角色和事件…");
  try {
    readingState?.abort();
    readingState = null;
    await readRole({replace: true});
    updatePageStatus("");
  } catch (error) {
    updatePageStatus(error.message, true);
    find("retry").hidden = false;
  }
}

async function saveRoleSetting(control) {
  const characterId = activeCharacter?.id;
  const key = control.dataset.setting;
  const value = control.type === "checkbox" ? control.checked : control.value;
  if (!beginWrite(characterId)) return;
  setSettingsStatus("正在保存…");
  try {
    const state = await request("api/settings", {characterId, settings: {[key]: value}});
    if (!matchesWrittenRole(state, characterId)) return;
    if (!state.settings) throw new Error("没有收到更新后的日历设置。");
    renderSettings(state.settings);
    renderDate(state);
    renderHolidays(state.holidays);
    setSettingsStatus("已保存。");
  } catch (error) {
    if (!await recoverRoleConflict(error)) {
      renderSettings(roleSettings);
      setSettingsStatus(error.message, true);
    }
  } finally {
    finishWrite();
    if (activeCharacter?.id === characterId && document.activeElement === document.body) {
      control.focus({preventScroll: true});
    }
  }
}

function monthLength(year, month) {
  if (month === 2) {
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    return leap ? 29 : 28;
  }
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function padded(value, width = 2) {
  return String(value).padStart(width, "0");
}

function calendarDate(day) {
  const monthDay = padded(calendar.month) + "-" + padded(day);
  return calendar.annual ? monthDay : padded(calendar.year, 4) + "-" + monthDay;
}

function resetCalendar(annual, selection) {
  const selected = parseDate(selection);
  const systemDate = new Date();
  const current = parseDate(today) || {year: systemDate.getFullYear(), month: systemDate.getMonth() + 1};
  const year = annual ? 2024 : selected?.year || current.year;
  calendar = {
    annual, year,
    minYear: Math.min(year, Math.max(1, current.year - 100)),
    maxYear: Math.max(year, Math.min(9999, current.year + 100)),
    month: selected?.month || current.month,
    selected: selected && Boolean(selected.year) !== annual ? selection : "",
  };
  find("date-label").textContent = annual ? "每年月日（必选）" : "日期（必选）";
  yearSelect.hidden = annual;
  find("weekdays").hidden = annual;
  yearSelect.replaceChildren();
  if (!annual) {
    for (let option = calendar.minYear; option <= calendar.maxYear; option += 1) {
      yearSelect.add(new Option(option + "年", option));
    }
  }
  showCalendar();
}

function showCalendar() {
  if (!calendar.annual) yearSelect.value = calendar.year;
  monthSelect.value = calendar.month;
  const prev = find("month-prev");
  const next = find("month-next");
  prev.disabled = !calendar.annual && calendar.year === calendar.minYear && calendar.month === 1;
  next.disabled = !calendar.annual && calendar.year === calendar.maxYear && calendar.month === 12;
  dayGrid.replaceChildren();
  if (!calendar.annual) {
    const first = new Date(0);
    first.setUTCFullYear(calendar.year, calendar.month - 1, 1);
    const leading = (first.getUTCDay() + 6) % 7;
    for (let index = 0; index < leading; index += 1) {
      const blank = node("span");
      blank.setAttribute("aria-hidden", "true");
      dayGrid.append(blank);
    }
  }

  const total = monthLength(calendar.year, calendar.month);
  const selected = parseDate(calendar.selected);
  const activeDay = selected && (calendar.annual || selected.year === calendar.year) &&
    selected.month === calendar.month ? selected.day : 1;
  for (let day = 1; day <= total; day += 1) {
    const value = calendarDate(day);
    const button = node("button", "day", String(day));
    button.type = "button";
    button.dataset.date = value;
    button.tabIndex = day === activeDay ? 0 : -1;
    button.setAttribute("aria-label", displayDate(value));
    button.setAttribute("aria-pressed", String(value === calendar.selected));
    if (value === today) button.setAttribute("aria-current", "date");
    button.addEventListener("click", () => {
      calendar.selected = value;
      showCalendar();
      dayGrid.querySelector('[tabindex="0"]').focus();
      showError(editorError, "");
    });
    dayGrid.append(button);
  }
  const label = find("date-choice");
  label.textContent = calendar.selected ? "已选 " + displayDate(calendar.selected) : "请选择日期";
}

function moveMonth(offset) {
  const target = calendar.month + offset;
  if (target >= 1 && target <= 12) {
    calendar.month = target;
  } else if (calendar.annual) {
    calendar.month = target < 1 ? 12 : 1;
  } else {
    const year = calendar.year + offset;
    if (year < calendar.minYear || year > calendar.maxYear) return;
    calendar.year = year;
    calendar.month = target < 1 ? 12 : 1;
  }
  showCalendar();
}

function navigateDays(event) {
  const delta = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7}[event.key];
  if (delta === undefined || !event.target.matches(".day")) return;
  event.preventDefault();
  const days = [...dayGrid.querySelectorAll(".day")];
  const destination = days[days.indexOf(event.target) + delta];
  if (destination) {
    const active = dayGrid.querySelector('[tabindex="0"]');
    active.tabIndex = -1;
    destination.tabIndex = 0;
    destination.focus();
  }
}

function updateScheduleFields() {
  const custom = kind === "custom";
  const dateVisible = kind === "annual" || (custom && dateMode.value !== "daily");
  const timeVisible = kind === "daily" || (custom && timeMode.value === "specific");
  find("calendar").hidden = !dateVisible;
  find("time-row").hidden = !timeVisible;
  timeInput.disabled = !timeVisible;
  if (dateVisible) {
    const annual = kind === "annual" || dateMode.value === "annual";
    if (calendar.annual !== annual) resetCalendar(annual, calendar.selected);
  }
}

function showTypeOptions() {
  kind = null;
  find("editor-title").textContent = "添加事件";
  find("choose-type").hidden = false;
  find("event-fields").hidden = true;
  find("event-save").hidden = true;
  find("editor-back").hidden = true;
  nameInput.disabled = true;
  timeInput.disabled = true;
  description.disabled = true;
  showError(editorError, "");
}

function showFields(type, event) {
  kind = type;
  find("editor-title").textContent = (event ? "编辑" : "添加") + kinds[type].title;
  find("choose-type").hidden = true;
  find("event-fields").hidden = false;
  find("event-save").hidden = false;
  find("editor-back").hidden = Boolean(event);

  const custom = type === "custom";
  const annual = type === "annual";
  find("date-mode-row").hidden = !custom;
  find("time-mode-row").hidden = !custom;
  find("name-row").hidden = !custom && !annual;
  nameInput.disabled = !custom && !annual;
  nameInput.required = annual;
  find("name-label").textContent = annual ? "日子名称（必填）" : "日子名称（选填）";
  description.disabled = false;
  find("description-label").textContent = annual ? "这个日子的意义（必填）" : "描述（必填）";

  const legacyAnnual = custom && Boolean(event?.repeatAnnually);
  const option = find("legacy-annual");
  option.hidden = !legacyAnnual;
  option.disabled = !legacyAnnual;
  dateMode.value = event?.date === "daily" ? "daily" : legacyAnnual ? "annual" : "specific";
  timeMode.value = custom && event && event.time === null ? "any" : "specific";
  nameInput.value = event?.label || "";
  description.value = event?.message || (type === "daily" ? event?.label || "" : "");
  timeInput.value = event?.time || "";
  find("enabled-row").hidden = !event;
  find("event-enabled").checked = event?.enabled !== false;
  resetCalendar(annual || legacyAnnual, event?.date);
  updateScheduleFields();
  showError(editorError, "");
}

function openEditor(type = null, event = null, characterId = activeCharacter?.id) {
  if (writing || !characterId || activeCharacter?.id !== characterId) return;
  editorCharacterId = characterId;
  editing = event;
  if (type) showFields(type, event);
  else showTypeOptions();
  editor.showModal();
  if (type) focusFields();
}

function focusFields() {
  if (!find("date-mode-row").hidden) dateMode.focus();
  else if (!find("calendar").hidden) monthSelect.focus();
  else timeInput.focus();
}

function buildEvent() {
  const event = {};
  if (editing) {
    event.id = editing.id;
    event.enabled = find("event-enabled").checked;
  }
  if (kind === "annual" || kind === "custom") event.label = nameInput.value.trim();
  if (kind === "annual" && !event.label) throw new Error("请填写这个日子的名称。");
  event.message = description.value.trim();
  if (!event.message) {
    throw new Error(kind === "annual" ? "请填写这个日子的意义。" : "请填写描述。");
  }

  if (kind === "annual") {
    if (!calendar.selected) throw new Error("请在日历中选一个月日。");
    event.date = calendar.selected;
  }
  if (kind === "custom") {
    if (dateMode.value !== "daily" && !calendar.selected) throw new Error("请在日历中选一个日期。");
    event.date = dateMode.value === "daily" ? "daily" : calendar.selected;
    event.repeatAnnually = dateMode.value === "annual";
    event.time = timeMode.value === "any" ? null : timeInput.value;
  } else if (kind === "daily") {
    event.time = timeInput.value;
  }
  return event;
}

function setDialogButtons(isWaiting, buttons) {
  for (const [button, idleText, workingText] of buttons) {
    button.disabled = isWaiting;
    if (idleText) button.textContent = isWaiting ? workingText : idleText;
  }
}

async function save(event) {
  event.preventDefault();
  if (!editor.open || !kind || writing) return;
  const characterId = editorCharacterId;
  const wasEditing = Boolean(editing);
  let payload;
  try {
    payload = {characterId, kind, event: buildEvent()};
  } catch (error) {
    showError(editorError, error.message);
    return;
  }
  if (!beginWrite(characterId)) return;
  showError(editorError, "");
  const buttons = [[find("event-save"), "保存事件", "正在保存…"], [find("editor-cancel")], [find("editor-back")]];
  setDialogButtons(true, buttons);
  let saved = false;
  try {
    const state = await request("api/events", payload);
    if (!matchesWrittenRole(state, characterId)) return;
    renderEvents(state);
    closeDrafts();
    updatePageStatus(wasEditing ? "事件已更新。" : "事件已添加。");
    saved = true;
  } catch (error) {
    if (!await recoverRoleConflict(error)) showError(editorError, error.message);
  } finally {
    setDialogButtons(false, buttons);
    finishWrite();
    if (saved) find("add-event").focus();
  }
}

function openDelete(type, event, characterId) {
  if (writing || !characterId || activeCharacter?.id !== characterId) return;
  deleting = {characterId, kind: type, id: event.id};
  find("delete-message").textContent = "确定删除「" + eventTitle(type, event) + "」？";
  showError(deleteError, "");
  deleteDialog.showModal();
}

async function remove() {
  if (!deleteDialog.open || !deleting || !beginWrite(deleting.characterId)) return;
  const payload = deleting;
  showError(deleteError, "");
  const buttons = [[find("delete-confirm"), "删除事件", "正在删除…"], [find("delete-cancel")]];
  setDialogButtons(true, buttons);
  let removed = false;
  try {
    const state = await request("api/events/delete", payload);
    if (!matchesWrittenRole(state, payload.characterId)) return;
    renderEvents(state);
    closeDrafts();
    updatePageStatus("事件已删除。");
    removed = true;
  } catch (error) {
    if (!await recoverRoleConflict(error)) showError(deleteError, error.message);
  } finally {
    setDialogButtons(false, buttons);
    finishWrite();
    if (removed) find("add-event").focus();
  }
}

for (let month = 1; month <= 12; month += 1) monthSelect.add(new Option(month + "月", month));
find("add-event").addEventListener("click", () => openEditor());
find("retry").addEventListener("click", load);
for (const control of settingsInputs) control.addEventListener("change", () => saveRoleSetting(control));
find("holiday-region").addEventListener("change", (event) => {
  saveHoliday({region: event.target.value}, event.target);
});
for (const button of document.querySelectorAll(".type-choice")) {
  button.addEventListener("click", () => {
    showFields(button.dataset.kind, null);
    focusFields();
  });
}
find("editor-back").addEventListener("click", () => {
  showTypeOptions();
  find("choose-type").querySelector("button").focus();
});
find("editor-cancel").addEventListener("click", () => editor.close());
find("delete-cancel").addEventListener("click", () => deleteDialog.close());
find("delete-confirm").addEventListener("click", remove);
for (const dialog of [editor, deleteDialog]) {
  dialog.addEventListener("cancel", (event) => {
    if (writing) event.preventDefault();
  });
}
dateMode.addEventListener("change", updateScheduleFields);
timeMode.addEventListener("change", updateScheduleFields);
find("month-prev").addEventListener("click", () => moveMonth(-1));
find("month-next").addEventListener("click", () => moveMonth(1));
yearSelect.addEventListener("change", () => {
  calendar.year = Number(yearSelect.value);
  showCalendar();
});
monthSelect.addEventListener("change", () => {
  calendar.month = Number(monthSelect.value);
  showCalendar();
});
dayGrid.addEventListener("keydown", navigateDays);
form.addEventListener("submit", save);
document.addEventListener("visibilitychange", pollRole);
setInterval(pollRole, 2000);
load();
