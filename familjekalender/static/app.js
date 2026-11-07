"use strict";

/* ------------------------------------------------------------------ hjälpare */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(method, url, data) {
  const opts = { method, headers: {} };
  if (data instanceof FormData) {
    opts.body = data;
  } else if (data !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(data);
  }
  const res = await fetch(url, opts);
  if (res.status === 204) return null;
  let json = null;
  try { json = await res.json(); } catch { /* inget JSON-svar */ }
  if (!res.ok) throw new Error((json && json.error) || `Något gick fel (${res.status})`);
  return json;
}

function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), isError ? 6000 : 2500);
}

function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem("fk." + key));
    localStorage.setItem("fk." + key, JSON.stringify(value));
  } catch { return null; }
  return value;
}

/* ------------------------------------------------------------------ datum */

const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseDay = (s) => { const [y, m, d] = s.slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const addDaysIso = (s, n) => iso(addDays(parseDay(s), n));
const startOfWeek = (d) => addDays(d, -((d.getDay() + 6) % 7));
const todayIso = () => iso(new Date());
const MONTHS = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober", "november", "december"];
const WEEKDAYS = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];

function dayHeading(dayIso) {
  const t = todayIso();
  if (dayIso === t) return "Idag";
  if (dayIso === addDaysIso(t, 1)) return "Imorgon";
  if (dayIso === addDaysIso(t, -1)) return "Igår";
  const d = parseDay(dayIso);
  const s = d.toLocaleDateString("sv-SE", { weekday: "long", day: "numeric", month: "long" });
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function weekNumber(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - y0) / 86400000 + 1) / 7);
}

/** Vilka dagar (ISO) en händelse syns på. */
function eventDays(ev) {
  // Ett nattpass hör till dagen det börjar, även om det slutar efter midnatt.
  if (ev.source === "shift") return [ev.date];
  const startDay = ev.start.slice(0, 10);
  let lastDay;
  if (ev.all_day) {
    lastDay = ev.end > startDay ? addDaysIso(ev.end, -1) : startDay;
  } else {
    lastDay = ev.end.slice(0, 10);
    if (lastDay > startDay && ev.end.slice(11, 16) === "00:00") lastDay = addDaysIso(lastDay, -1);
    if (lastDay < startDay) lastDay = startDay;
  }
  const days = [];
  for (let d = startDay; d <= lastDay && days.length < 62; d = addDaysIso(d, 1)) days.push(d);
  return days;
}

function timeLabel(ev) {
  if (ev.all_day) return "Heldag";
  const s = ev.start.slice(11, 16), e = ev.end.slice(11, 16);
  return ev.end === ev.start ? s : `${s}–${e}`;
}

/* ------------------------------------------------------------------ tillstånd */

const state = {
  view: store("view") || "agenda",
  members: [],
  calendars: [],
  shiftTypes: [],
  hidden: new Set(store("hidden") || []),
  agendaWeeks: 4,
  month: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  monthSelected: todayIso(),
  sched: {
    member: store("schedMember"),
    month: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
    selected: null,
    shifts: {},
  },
};

const memberById = (id) => state.members.find((m) => m.id === id);
const memberKey = (id) => (id == null ? "none" : String(id));
const visible = (ev) => !state.hidden.has(memberKey(ev.member_id));

async function loadBase() {
  [state.members, state.calendars, state.shiftTypes] = await Promise.all([
    api("GET", "/api/members"),
    api("GET", "/api/calendars"),
    api("GET", "/api/shift-types"),
  ]);
}

async function loadEvents(start, end) {
  return api("GET", `/api/events?start=${start}&end=${end}`);
}

/* ------------------------------------------------------------------ filter */

function renderFilters() {
  const el = $("#filters");
  const showFilters = ["agenda", "month"].includes(state.view) && state.members.length > 0;
  el.hidden = !showFilters;
  if (!showFilters) return;
  const chips = state.members.map((m) => ({ key: String(m.id), name: m.name, color: m.color }));
  if (state.calendars.some((c) => c.member_id == null)) chips.push({ key: "none", name: "Gemensamt", color: "#6b7280" });
  el.innerHTML = chips
    .map((c) => `<button class="chip ${state.hidden.has(c.key) ? "off" : ""}" data-key="${esc(c.key)}" style="--c:${esc(c.color)}" aria-pressed="${!state.hidden.has(c.key)}"><span class="dot"></span>${esc(c.name)}</button>`)
    .join("");
}

$("#filters").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  const key = chip.dataset.key;
  state.hidden.has(key) ? state.hidden.delete(key) : state.hidden.add(key);
  store("hidden", [...state.hidden]);
  render();
});

/* ------------------------------------------------------------------ händelserader & detaljer */

const eventCache = new Map();

function eventRow(ev) {
  eventCache.set(ev.key, ev);
  const who = memberById(ev.member_id);
  const meta = [who ? who.name : null, ev.calendar_name, ev.location].filter(Boolean).map(esc).join(" · ");
  const time = ev.all_day || ev.end === ev.start
    ? esc(timeLabel(ev))
    : `${esc(ev.start.slice(11, 16))}<small>${esc(ev.end.slice(11, 16))}</small>`;
  return `<button class="event ${ev.source}" data-key="${esc(ev.key)}" style="--c:${esc(ev.color)}">
      <span class="ev-time">${time}</span>
      <span class="ev-body"><span class="ev-title">${esc(ev.title)}</span><span class="ev-meta">${meta}</span></span>
    </button>`;
}

function openSheet(html) {
  $("#sheet-body").innerHTML = html;
  $("#sheet").hidden = false;
}
function closeSheet() { $("#sheet").hidden = true; }
$("#sheet").addEventListener("click", (e) => {
  if (e.target.id === "sheet" || e.target.closest(".sheet-close")) closeSheet();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });

function linkify(text) {
  return esc(text).replace(/https?:\/\/[^\s<]+/g, (u) => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`);
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest(".event");
  if (!btn) return;
  const ev = eventCache.get(btn.dataset.key);
  if (!ev) return;
  const who = memberById(ev.member_id);
  const sameDay = ev.all_day ? eventDays(ev).length === 1 : ev.start.slice(0, 10) === ev.end.slice(0, 10) || ev.end.slice(11) === "00:00";
  let when = `${dayHeading(ev.start.slice(0, 10))}, ${timeLabel(ev)}`;
  if (!sameDay) {
    const last = eventDays(ev).at(-1);
    when = ev.all_day
      ? `${dayHeading(ev.start.slice(0, 10))} – ${dayHeading(last)}`
      : `${dayHeading(ev.start.slice(0, 10))} ${ev.start.slice(11, 16)} – ${dayHeading(ev.end.slice(0, 10))} ${ev.end.slice(11, 16)}`;
  }
  openSheet(`
    <div class="sheet-head" style="--c:${esc(ev.color)}"><span class="dot big"></span><h2>${esc(ev.title)}</h2></div>
    <p class="when">${esc(when)}</p>
    ${who ? `<p><b>Vem:</b> ${esc(who.name)}</p>` : ""}
    <p><b>Kalender:</b> ${esc(ev.calendar_name)}</p>
    ${ev.location ? `<p><b>Plats:</b> <a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(ev.location)}" target="_blank" rel="noopener">${esc(ev.location)}</a></p>` : ""}
    ${ev.description ? `<p class="desc">${linkify(ev.description)}</p>` : ""}
  `);
});

/* ------------------------------------------------------------------ Kommande */

async function renderAgenda() {
  const start = todayIso();
  const end = addDaysIso(start, state.agendaWeeks * 7);
  const events = (await loadEvents(start, end)).filter(visible);
  const byDay = new Map();
  for (const ev of events) {
    for (const d of eventDays(ev)) {
      if (d < start || d >= end) continue;
      if (!byDay.has(d)) byDay.set(d, []);
      byDay.get(d).push(ev);
    }
  }
  const days = [...byDay.keys()].sort();
  const list = $("#agenda-list");
  if (!state.members.length) {
    list.innerHTML = `<div class="empty"><p>Välkommen! Börja med att lägga till familjen och lagens kalendrar under <b>Inställningar</b>.</p><button class="btn" data-goto="settings">Kom igång</button></div>`;
  } else if (!days.length) {
    list.innerHTML = `<div class="empty"><p>Inget planerat de närmaste ${state.agendaWeeks} veckorna.</p></div>`;
  } else {
    let lastWeek = null;
    list.innerHTML = days
      .map((d) => {
        const w = weekNumber(parseDay(d));
        const weekHead = w !== lastWeek ? `<div class="week-label">Vecka ${w}</div>` : "";
        lastWeek = w;
        const evs = byDay.get(d).sort((a, b) => (b.all_day - a.all_day) || a.start.localeCompare(b.start));
        return `${weekHead}<div class="day ${d === todayIso() ? "today" : ""}"><h3>${esc(dayHeading(d))}</h3>${evs.map(eventRow).join("")}</div>`;
      })
      .join("");
  }
  $("#agenda-more").hidden = !state.members.length;
}

$("#agenda-more").addEventListener("click", () => {
  state.agendaWeeks += 4;
  renderAgenda().catch(showError);
});

/* ------------------------------------------------------------------ Månad */

function monthGridDays(first) {
  const gridStart = startOfWeek(first);
  return Array.from({ length: 42 }, (_, i) => iso(addDays(gridStart, i)));
}

function gridHeader() {
  return WEEKDAYS.map((w) => `<div class="wd">${w}</div>`).join("");
}

async function renderMonth() {
  const first = state.month;
  $("#month-title").textContent = `${MONTHS[first.getMonth()]} ${first.getFullYear()}`;
  const days = monthGridDays(first);
  const events = (await loadEvents(days[0], addDaysIso(days[41], 1))).filter(visible);
  const byDay = new Map(days.map((d) => [d, []]));
  for (const ev of events) for (const d of eventDays(ev)) if (byDay.has(d)) byDay.get(d).push(ev);
  const t = todayIso();
  const month = first.getMonth();

  $("#month-grid").innerHTML = gridHeader() + days
    .map((d) => {
      const evs = byDay.get(d).sort((a, b) => (b.all_day - a.all_day) || a.start.localeCompare(b.start));
      const out = parseDay(d).getMonth() !== month;
      const chips = evs.slice(0, 3).map((ev) => `<span class="mchip ${ev.source}" style="--c:${esc(ev.color)}">${esc(ev.short || ev.title)}</span>`).join("");
      const more = evs.length > 3 ? `<span class="more">+${evs.length - 3}</span>` : "";
      return `<button class="cell ${out ? "out" : ""} ${d === t ? "today" : ""} ${d === state.monthSelected ? "selected" : ""}" data-day="${d}">
          <span class="num">${parseDay(d).getDate()}</span>${chips}${more}</button>`;
    })
    .join("");

  const sel = state.monthSelected;
  const selEvents = (byDay.get(sel) || []).sort((a, b) => (b.all_day - a.all_day) || a.start.localeCompare(b.start));
  $("#month-day").innerHTML = byDay.has(sel)
    ? `<h3>${esc(dayHeading(sel))}</h3>${selEvents.length ? selEvents.map(eventRow).join("") : `<p class="hint">Inget planerat.</p>`}`
    : "";
}

$("#month-grid").addEventListener("click", (e) => {
  const cell = e.target.closest(".cell");
  if (!cell) return;
  state.monthSelected = cell.dataset.day;
  const d = parseDay(cell.dataset.day);
  if (d.getMonth() !== state.month.getMonth()) state.month = new Date(d.getFullYear(), d.getMonth(), 1);
  renderMonth().catch(showError);
});
$$("[data-month-step]").forEach((b) => b.addEventListener("click", () => {
  const m = state.month;
  state.month = new Date(m.getFullYear(), m.getMonth() + Number(b.dataset.monthStep), 1);
  state.monthSelected = iso(state.month);
  renderMonth().catch(showError);
}));
$("#month-today").addEventListener("click", () => {
  const n = new Date();
  state.month = new Date(n.getFullYear(), n.getMonth(), 1);
  state.monthSelected = todayIso();
  renderMonth().catch(showError);
});

/* ------------------------------------------------------------------ Schema (arbetspass) */

const typesFor = (memberId) => state.shiftTypes.filter((t) => t.member_id === memberId);

function shiftMinutes(t) {
  if (!t.start_time || !t.end_time) return 0;
  const [sh, sm] = t.start_time.split(":").map(Number);
  const [eh, em] = t.end_time.split(":").map(Number);
  let m = eh * 60 + em - (sh * 60 + sm);
  if (m <= 0) m += 24 * 60;
  return m;
}

const typeTimes = (t) => (t.start_time ? `${t.start_time}–${t.end_time}` : "Heldag");

async function renderSchedule() {
  const hasMembers = state.members.length > 0;
  $("#schedule-empty").hidden = hasMembers;
  $("#schedule-main").hidden = !hasMembers;
  if (!hasMembers) return;

  const s = state.sched;
  if (!memberById(s.member)) {
    // Förvalt: den första personen som har passtyper (den som har ett arbetsschema).
    s.member = (state.members.find((m) => typesFor(m.id).length) || state.members[0]).id;
  }
  $("#schedule-member").innerHTML = state.members
    .map((m) => `<option value="${m.id}" ${m.id === s.member ? "selected" : ""}>${esc(m.name)}</option>`)
    .join("");

  const types = typesFor(s.member);
  if (s.selected !== "erase" && !types.some((t) => t.id === s.selected)) s.selected = types[0]?.id ?? null;

  $("#schedule-hint").textContent = types.length
    ? "Välj ett pass och tryck på dagarna i kalendern. Tryck igen för att ta bort."
    : "Skapa passtyper först (längre ner), t.ex. Dag, Kväll och Natt.";
  $("#palette").innerHTML = types
    .map((t) => `<button class="pal ${s.selected === t.id ? "active" : ""}" data-type="${t.id}" style="--c:${esc(t.color)}">
        <b>${esc(t.short || t.name)}</b><span>${esc(t.name)}<br><small>${esc(typeTimes(t))}</small></span></button>`)
    .join("") + (types.length ? `<button class="pal erase ${s.selected === "erase" ? "active" : ""}" data-type="erase"><b>⌫</b><span>Sudda</span></button>` : "");

  $("#shift-type-list").innerHTML = types.length
    ? types.map((t) => `<li><span class="swatch" style="background:${esc(t.color)}"></span>
        <span class="grow"><b>${esc(t.name)}</b> (${esc(t.short || "")}) · ${esc(typeTimes(t))}</span>
        <button class="btn small ghost danger" data-del-type="${t.id}">Ta bort</button></li>`).join("")
    : `<li class="hint">Inga passtyper ännu.</li>`;
  $("#shift-defaults").hidden = types.length > 0;

  // Kalendergrid
  const first = s.month;
  $("#sched-title").textContent = `${MONTHS[first.getMonth()]} ${first.getFullYear()}`;
  const days = monthGridDays(first);
  const shifts = await api("GET", `/api/shifts?member_id=${s.member}&start=${days[0]}&end=${addDaysIso(days[41], 1)}`);
  s.shifts = Object.fromEntries(shifts.map((x) => [x.date, x]));
  drawScheduleGrid();

  const rf = $("#repeat-form");
  if (!rf.start.value) {
    rf.start.value = iso(startOfWeek(first));
    rf.until.value = iso(new Date(first.getFullYear(), 11, 31));
  }
}

function drawScheduleGrid() {
  const s = state.sched;
  const first = s.month;
  const days = monthGridDays(first);
  const typeMap = Object.fromEntries(state.shiftTypes.map((t) => [t.id, t]));
  const t0 = todayIso();
  let count = 0, minutes = 0;
  $("#sched-grid").innerHTML = gridHeader() + days
    .map((d) => {
      const sh = s.shifts[d];
      const type = sh && typeMap[sh.shift_type_id];
      const out = parseDay(d).getMonth() !== first.getMonth();
      if (type && !out) { count++; minutes += shiftMinutes(type); }
      return `<button class="cell ${out ? "out" : ""} ${d === t0 ? "today" : ""} ${type ? "has" : ""}" data-day="${d}" ${type ? `style="--c:${esc(type.color)}"` : ""}>
          <span class="num">${parseDay(d).getDate()}</span>
          ${type ? `<span class="shift-badge">${esc(type.short || type.name)}</span><span class="shift-time">${esc(type.start_time || "")}</span>` : ""}
        </button>`;
    })
    .join("");
  const h = Math.floor(minutes / 60), m = minutes % 60;
  $("#sched-summary").textContent = count
    ? `${MONTHS[first.getMonth()]}: ${count} pass, ${h} tim${m ? ` ${m} min` : ""}`
    : "";
}

$("#schedule-member").addEventListener("change", (e) => {
  state.sched.member = Number(e.target.value);
  state.sched.selected = null;
  store("schedMember", state.sched.member);
  renderSchedule().catch(showError);
});

$("#palette").addEventListener("click", (e) => {
  const b = e.target.closest(".pal");
  if (!b) return;
  state.sched.selected = b.dataset.type === "erase" ? "erase" : Number(b.dataset.type);
  $$(".pal").forEach((x) => x.classList.toggle("active", x === b));
});

$("#sched-grid").addEventListener("click", async (e) => {
  const cell = e.target.closest(".cell");
  if (!cell) return;
  const s = state.sched;
  if (s.selected == null) { toast("Välj ett pass först.", true); return; }
  const day = cell.dataset.day;
  const current = s.shifts[day];
  const typeId = s.selected === "erase" || (current && current.shift_type_id === s.selected) ? null : s.selected;
  const before = current;
  if (typeId == null) delete s.shifts[day];
  else s.shifts[day] = { date: day, shift_type_id: typeId, member_id: s.member };
  drawScheduleGrid();
  try {
    await api("PUT", "/api/shifts", { member_id: s.member, date: day, shift_type_id: typeId });
  } catch (err) {
    if (before) s.shifts[day] = before; else delete s.shifts[day];
    drawScheduleGrid();
    showError(err);
  }
});

$$("[data-sched-step]").forEach((b) => b.addEventListener("click", () => {
  const m = state.sched.month;
  state.sched.month = new Date(m.getFullYear(), m.getMonth() + Number(b.dataset.schedStep), 1);
  renderSchedule().catch(showError);
}));

$("#shift-type-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    const t = await api("POST", "/api/shift-types", {
      member_id: state.sched.member,
      name: f.name.value, short: f.short.value,
      start_time: f.start_time.value, end_time: f.end_time.value, color: f.color.value,
    });
    state.shiftTypes.push(t);
    state.sched.selected = t.id;
    f.reset();
    renderSchedule();
  } catch (err) { showError(err); }
});

$("#shift-defaults").addEventListener("click", async () => {
  const defaults = [
    { name: "Dag", short: "D", start_time: "07:00", end_time: "16:00", color: "#0ea5e9" },
    { name: "Kväll", short: "K", start_time: "14:00", end_time: "22:00", color: "#f97316" },
    { name: "Natt", short: "N", start_time: "21:30", end_time: "07:00", color: "#6d28d9" },
  ];
  try {
    for (const d of defaults) state.shiftTypes.push(await api("POST", "/api/shift-types", { member_id: state.sched.member, ...d }));
    toast("Passtyper tillagda – ändra tider genom att ta bort och lägga till nya.");
    renderSchedule();
  } catch (err) { showError(err); }
});

$("#shift-type-list").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-del-type]");
  if (!b) return;
  if (!confirm("Ta bort passtypen? Alla inlagda pass av den typen försvinner också.")) return;
  try {
    await api("DELETE", `/api/shift-types/${b.dataset.delType}`);
    state.shiftTypes = state.shiftTypes.filter((t) => t.id !== Number(b.dataset.delType));
    renderSchedule();
  } catch (err) { showError(err); }
});

$("#repeat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const start = iso(startOfWeek(parseDay(f.start.value)));
  if (!confirm(`Kopiera ${f.weeks.value} veckor från vecka ${weekNumber(parseDay(start))} framåt till ${f.until.value}? Befintliga pass efter mönstret skrivs över.`)) return;
  try {
    const r = await api("POST", "/api/shifts/repeat", { member_id: state.sched.member, start, weeks: Number(f.weeks.value), until: f.until.value });
    toast(`${r.created} pass inlagda.`);
    renderSchedule();
  } catch (err) { showError(err); }
});

/* ------------------------------------------------------------------ Inställningar */

function memberOptions(selected) {
  return `<option value="">Gemensamt</option>` + state.members
    .map((m) => `<option value="${m.id}" ${m.id === selected ? "selected" : ""}>${esc(m.name)}</option>`)
    .join("");
}

function fmtFetched(c) {
  if (c.kind === "file") return `Uppladdad fil · ${c.event_count} händelser`;
  if (!c.last_fetched) return "Inte hämtad än";
  return `Hämtad ${c.last_fetched.replace("T", " ")} · ${c.event_count} händelser`;
}

function renderSettings() {
  $("#member-list").innerHTML = state.members.length
    ? state.members.map((m) => `<li>
        <input type="color" value="${esc(m.color)}" data-member-color="${m.id}" aria-label="Färg för ${esc(m.name)}">
        <span class="grow">${esc(m.name)}</span>
        <button class="btn small ghost" data-rename="${m.id}">Byt namn</button>
        <button class="btn small ghost danger" data-del-member="${m.id}">Ta bort</button></li>`).join("")
    : `<li class="hint">Lägg till alla i familjen – varje person får en egen färg.</li>`;

  $$(".member-select").forEach((s) => (s.innerHTML = memberOptions(null)));

  $("#calendar-list").innerHTML = state.calendars.length
    ? state.calendars.map((c) => {
        const color = c.color || memberById(c.member_id)?.color || "#6b7280";
        return `<li class="cal">
          <span class="swatch" style="background:${esc(color)}"></span>
          <div class="grow">
            <b>${esc(c.name)}</b>
            <div class="hint">${esc(fmtFetched(c))}</div>
            ${c.last_error ? `<div class="err">⚠ ${esc(c.last_error)}</div>` : ""}
            <div class="cal-actions">
              <select data-cal-member="${c.id}" aria-label="Vems kalender">${memberOptions(c.member_id)}</select>
              <input type="color" value="${esc(color)}" data-cal-color="${c.id}" aria-label="Färg">
              ${c.kind === "url" ? `<button class="btn small ghost" data-cal-refresh="${c.id}">Uppdatera</button>` : ""}
              <button class="btn small ghost" data-cal-rename="${c.id}">Byt namn</button>
              <button class="btn small ghost danger" data-cal-del="${c.id}">Ta bort</button>
            </div>
          </div></li>`;
      }).join("")
    : `<li class="hint">Inga kalendrar ännu.</li>`;

  const base = location.origin;
  const webcal = (path) => base.replace(/^https?:/, "webcal:") + path;
  const feeds = [{ name: "Hela familjen", path: "/kalender.ics" }, ...state.members.map((m) => ({ name: m.name, path: `/kalender/${m.id}.ics` }))];
  $("#feed-list").innerHTML = feeds.map((f) => `<li>
      <span class="grow"><b>${esc(f.name)}</b><br><code>${esc(base + f.path)}</code></span>
      <a class="btn small ghost" href="${esc(webcal(f.path))}">Öppna</a>
      <button class="btn small ghost" data-copy="${esc(base + f.path)}">Kopiera</button></li>`).join("");
}

$("#member-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    state.members.push(await api("POST", "/api/members", { name: f.name.value, color: f.color.value }));
    f.name.value = "";
    const palette = ["#2563eb", "#db2777", "#16a34a", "#ea580c", "#7c3aed", "#0891b2", "#ca8a04"];
    f.color.value = palette[state.members.length % palette.length];
    renderSettings();
  } catch (err) { showError(err); }
});

async function updateCalendar(id, data) {
  const updated = await api("PUT", `/api/calendars/${id}`, data);
  state.calendars = state.calendars.map((c) => (c.id === updated.id ? updated : c));
  renderSettings();
}

$("#view-settings").addEventListener("change", async (e) => {
  const t = e.target;
  try {
    if (t.dataset.memberColor) {
      const updated = await api("PUT", `/api/members/${t.dataset.memberColor}`, { color: t.value });
      state.members = state.members.map((m) => (m.id === updated.id ? updated : m));
      renderSettings();
    } else if (t.dataset.calMember) {
      await updateCalendar(t.dataset.calMember, { member_id: t.value || null });
    } else if (t.dataset.calColor) {
      await updateCalendar(t.dataset.calColor, { color: t.value });
    }
  } catch (err) { showError(err); }
});

$("#view-settings").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  try {
    if (b.dataset.rename) {
      const m = memberById(Number(b.dataset.rename));
      const name = prompt("Nytt namn", m.name);
      if (!name) return;
      const updated = await api("PUT", `/api/members/${m.id}`, { name });
      state.members = state.members.map((x) => (x.id === updated.id ? updated : x));
      renderSettings();
    } else if (b.dataset.delMember) {
      const m = memberById(Number(b.dataset.delMember));
      if (!confirm(`Ta bort ${m.name}? Personens arbetsschema tas också bort. Kalendrar blir "Gemensamt".`)) return;
      await api("DELETE", `/api/members/${m.id}`);
      await loadBase();
      renderSettings();
    } else if (b.dataset.calRefresh) {
      b.disabled = true;
      b.textContent = "Hämtar…";
      try {
        await api("POST", `/api/calendars/${b.dataset.calRefresh}/refresh`);
        toast("Kalendern är uppdaterad.");
      } finally {
        state.calendars = await api("GET", "/api/calendars");
        renderSettings();
      }
    } else if (b.dataset.calRename) {
      const c = state.calendars.find((x) => x.id === Number(b.dataset.calRename));
      const name = prompt("Nytt namn", c.name);
      if (name) await updateCalendar(c.id, { name });
    } else if (b.dataset.calDel) {
      const c = state.calendars.find((x) => x.id === Number(b.dataset.calDel));
      if (!confirm(`Ta bort kalendern "${c.name}"?`)) return;
      await api("DELETE", `/api/calendars/${c.id}`);
      state.calendars = state.calendars.filter((x) => x.id !== c.id);
      renderSettings();
    } else if (b.dataset.copy) {
      try {
        await navigator.clipboard.writeText(b.dataset.copy);
        toast("Länken är kopierad.");
      } catch {
        prompt("Kopiera länken:", b.dataset.copy);
      }
    }
  } catch (err) { showError(err); }
});

$("#calendar-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const btn = f.querySelector("button[type=submit]");
  btn.disabled = true;
  btn.textContent = "Hämtar kalendern…";
  try {
    const c = await api("POST", "/api/calendars", {
      url: f.url.value,
      name: f.name.value,
      member_id: f.member_id.value || null,
      color: f.use_color.checked ? f.color.value : null,
    });
    state.calendars.push(c);
    f.reset();
    toast(`"${c.name}" tillagd med ${c.event_count} händelser.`);
    renderSettings();
  } catch (err) {
    showError(err);
  } finally {
    btn.disabled = false;
    btn.textContent = "Lägg till";
  }
});

$("#upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    const c = await api("POST", "/api/calendars/upload", new FormData(f));
    state.calendars.push(c);
    f.reset();
    toast(`"${c.name}" tillagd med ${c.event_count} händelser.`);
    renderSettings();
  } catch (err) { showError(err); }
});

/* ------------------------------------------------------------------ navigering */

function showError(err) {
  console.error(err);
  toast(err.message || String(err), true);
}

function render() {
  $$(".view").forEach((v) => (v.hidden = v.id !== `view-${state.view}`));
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === state.view));
  renderFilters();
  const fn = { agenda: renderAgenda, month: renderMonth, schedule: renderSchedule, settings: renderSettings }[state.view];
  Promise.resolve(fn()).catch(showError);
}

function go(view) {
  state.view = view;
  store("view", view);
  window.scrollTo(0, 0);
  render();
}

$(".tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-view]");
  if (b) go(b.dataset.view);
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-goto]");
  if (b) go(b.dataset.goto);
});

$("#refresh-btn").addEventListener("click", async () => {
  const b = $("#refresh-btn");
  b.classList.add("spin");
  try {
    const r = await api("POST", "/api/calendars/refresh");
    const errs = Object.keys(r.errors).length;
    toast(errs ? `${errs} kalender(er) kunde inte hämtas – se Inställningar.` : "Allt är uppdaterat.", errs > 0);
    await loadBase();
    render();
  } catch (err) {
    showError(err);
  } finally {
    b.classList.remove("spin");
  }
});

(async function init() {
  try {
    await loadBase();
    if (!state.members.length) state.view = "settings";
    render();
  } catch (err) {
    showError(err);
  }
})();
