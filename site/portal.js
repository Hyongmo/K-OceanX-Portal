"use strict";

const el = (id) => document.getElementById(id);
const REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
  "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];
// Rough map order for the region tiles (four columns, north to south).
const TILE_ORDER = ["인천", "서울", "경기", "강원", "충남", "세종", "충북", "경북", "전북", "대전", "대구", "울산",
  "광주", "전남", "경남", "부산", "제주"];
const AGE_LABELS = {prestartup: "예비창업", early: "창업 3년 이내", scaleup: "창업 3~10년"};
const PLANNING = {
  demand: "수요 제안", opinion: "RFP 의견", planning: "기획 지원", joint: "공동기획",
  preview: "공모 예고", application: "본공모",
};
const MARITIME_SOURCES = new Set(["kimst_rnd", "kimst_notice", "komeri", "bisfe", "jcia", "nor_shipping"]);
const MARITIME = /해양|수산|어업|어촌|해운|항만|선박|조선(?!일보|대)|기자재|크루즈|블루\s*바이오|해상\s*풍력|쇄빙|ocean|marine|maritime/i;
const SYNONYMS = [
  ["스마트항만", "스마트 항만", "항만자동화", "항만 자동화"],
  ["스마트양식", "스마트 양식", "지능형양식", "양식 자동화"],
  ["자율운항", "자율 운항", "무인선박", "무인 선박"],
  ["인공지능", "AI"],
  ["사업화", "상용화"],
  ["해상공급망", "해상 공급망", "해운 공급망"],
];
const PAGE = 50;

const today = new Intl.DateTimeFormat("sv-SE", {timeZone: "Asia/Seoul"}).format(new Date());
const nowInSeoul = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
}).format(new Date());

let data = {records: [], sources: {}, support_facets: {}};
let status = "open";
let limit = PAGE;
let eventLimit = 40;
let agencyRegion = "부산";

function addText(parent, tag, value, className) {
  const node = document.createElement(tag);
  if (value) node.textContent = value;
  if (className) node.className = className;
  parent.append(node);
  return node;
}

function addLink(parent, text, url, className) {
  let safe;
  try { safe = new URL(url); } catch { return addText(parent, "span", text, className); }
  if (safe.protocol !== "https:") return addText(parent, "span", text, className);
  const link = addText(parent, "a", text, className);
  link.href = safe.href;
  return link;
}

const normalize = (value) => value.normalize("NFKC").toLowerCase().replace(/\s+/g, "");
const days = (value) => Math.round((Date.parse(value) - Date.parse(today)) / 86400000);
const shortDate = (value) => `${Number(value.slice(5, 7))}.${Number(value.slice(8, 10))}`;
const sourceLabel = (entry) => entry.publisher || data.sources[entry.source] || entry.source;
const typeLabels = (entry) => (entry.support?.types ?? []).map((key) => data.support_facets?.types?.[key]).filter(Boolean);
const regionsOf = (entry) => entry.support?.regions ?? (REGIONS.includes(entry.place) ? [entry.place] : []);
const stagesOf = (entry) => entry.support?.stages ?? [];
const isMaritime = (entry) => Boolean(entry.maritime) || MARITIME_SOURCES.has(entry.source) || MARITIME.test(entry.title);

function isClosed(entry) {
  if (/\[\s*(?:접수\s*)?마감\s*\]/.test(entry.title)) return true;
  if (!entry.deadline) return false;
  return entry.deadline < today || (entry.deadline === today && Boolean(entry.deadline_time) && entry.deadline_time <= nowInSeoul);
}

function statusOf(entry) {
  if (isClosed(entry)) return "closed";
  return entry.deadline ? "open" : "undated";
}

function searchTerms(query) {
  return query.split(/\s+/).filter(Boolean).map(normalize).map((term) => {
    const group = SYNONYMS.find((words) => words.some((word) => normalize(word) === term));
    return group ? group.map(normalize) : [term];
  });
}

function matches(entry, terms) {
  if (!terms.length) return true;
  const subject = normalize([entry.title, entry.publisher, entry.topic, entry.eligibility, entry.place,
    data.sources[entry.source], entry.event_region, ...(entry.event_types ?? []), ...typeLabels(entry),
    PLANNING[entry.planning_stage]].filter(Boolean).join(" "));
  return terms.every((group) => group.some((word) => subject.includes(word)));
}

/* ---------- 지원사업 찾기 ---------- */

function supportScope() {
  return data.records.filter((entry) => entry.category === "support" || entry.category === "rnd");
}

function conditionCheck(entry, region, age) {
  const regions = regionsOf(entry);
  const stages = stagesOf(entry);
  const regionKnown = !region || regions.length > 0;
  const regionOk = !region || !regions.length || regions.includes(region) || regions.includes("전국");
  const ageKnown = !age || stages.length > 0;
  const ageOk = !age || !stages.length || stages.includes(age);
  return {regionOk, ageOk, confirmed: regionOk && ageOk && regionKnown && ageKnown, regionKnown, ageKnown};
}

function benefitMatches(entry, benefit) {
  if (!benefit) return true;
  if (benefit === "rnd") return entry.category === "rnd";
  return entry.category === "support" && (entry.support?.types ?? []).includes(benefit);
}

function renderSupport() {
  const region = el("region").value;
  const age = el("age").value;
  const benefit = el("benefit").value;
  const terms = searchTerms(el("query").value.trim());
  const maritimeOnly = el("maritime-only").checked;
  const base = supportScope().filter((entry) => matches(entry, terms) && benefitMatches(entry, benefit) &&
    (!maritimeOnly || isMaritime(entry)));
  let regionOut = 0, ageOut = 0;
  const eligible = [];
  for (const entry of base) {
    const check = conditionCheck(entry, region, age);
    if (!check.regionOk) regionOut += 1;
    else if (!check.ageOk) ageOut += 1;
    else eligible.push(entry);
  }
  const counts = {open: 0, undated: 0, closed: 0};
  eligible.forEach((entry) => { counts[statusOf(entry)] += 1; });
  for (const button of document.querySelectorAll(".status-tabs button")) {
    button.querySelector("span").textContent = counts[button.dataset.status].toLocaleString("ko-KR");
    button.setAttribute("aria-pressed", String(button.dataset.status === status));
  }
  const parts = [];
  if (regionOut) parts.push(`다른 지역 한정 ${regionOut.toLocaleString("ko-KR")}건`);
  if (ageOut) parts.push(`업력 조건 불일치 ${ageOut.toLocaleString("ko-KR")}건`);
  el("excluded-note").textContent = parts.length ? `조건이 맞지 않아 제외: ${parts.join(" · ")}` : "";
  el("eligibility-head").textContent = region || age ?
    `신청 자격 (${[region && region + " 소재", age && AGE_LABELS[age]].filter(Boolean).join(" · ")} 기준)` : "신청 자격";

  const shown = eligible.filter((entry) => statusOf(entry) === status);
  const due = (entry) => entry.deadline + (entry.deadline_time || "23:59");
  if (status === "open") shown.sort((a, b) => due(a).localeCompare(due(b)) || a.title.localeCompare(b.title, "ko"));
  else if (status === "closed") shown.sort((a, b) => due(b).localeCompare(due(a)));
  else shown.sort((a, b) => (b.published || "").localeCompare(a.published || "") || a.title.localeCompare(b.title, "ko"));

  const groups = status === "open" ? [
    ["이번 주 마감", (entry) => days(entry.deadline) <= 7, true],
    ["30일 안에 마감", (entry) => days(entry.deadline) <= 30, false],
    ["30일 이후 마감", () => true, false],
  ] : [[status === "closed" ? "마감된 공고" : "마감일이 공고에 표기되지 않은 공고 (상시·예산 소진 시까지 등)", () => true, false]];
  const container = el("notice-groups");
  container.replaceChildren();
  // Each notice belongs to the first group whose test it passes.
  const groupOf = new Map(shown.map((entry) => [entry.id, groups.findIndex(([, test]) => test(entry))]));
  const visible = shown.slice(0, limit);
  groups.forEach(([title, , urgent], index) => {
    const members = visible.filter((entry) => groupOf.get(entry.id) === index);
    if (!members.length) return;
    const total = shown.filter((entry) => groupOf.get(entry.id) === index).length;
    addText(container, "h2", `${title} · ${total.toLocaleString("ko-KR")}건`, urgent ? "group-title urgent" : "group-title");
    const list = addText(container, "ol", "", "notice-list");
    members.forEach((entry) => appendNotice(list, entry, region, age));
  });
  if (!shown.length) addText(container, "p", "조건에 맞는 공고가 없습니다. 조건이나 검색어를 바꿔 보세요.", "empty");
  el("more").hidden = shown.length <= limit;
  el("more").textContent = `나머지 ${(shown.length - limit).toLocaleString("ko-KR")}건 중 ${Math.min(PAGE, shown.length - limit)}건 더 보기`;
}

function appendNotice(list, entry, region, age) {
  const item = addText(list, "li", "", "notice");
  const due = addText(item, "div", "", "due");
  if (entry.deadline) {
    const left = days(entry.deadline);
    const closed = isClosed(entry);
    if (!closed && left <= 7) due.classList.add("urgent");
    addText(due, "strong", closed ? "마감" : left === 0 ? "오늘" : `D-${left}`);
    addText(due, "span", shortDate(entry.deadline) + (entry.deadline_time ? " " + entry.deadline_time : ""));
    if (entry.opens && entry.opens > today) addText(due, "span", `${shortDate(entry.opens)} 접수 시작`);
  } else {
    addText(due, "strong", "상시");
    if (entry.published) addText(due, "span", `${shortDate(entry.published)} 게시`);
  }

  const kind = addText(item, "div", "", "kind");
  if (entry.category === "rnd") {
    kind.textContent = "R&D 과제";
    if (PLANNING[entry.planning_stage]) addText(kind, "span", PLANNING[entry.planning_stage], "sub");
  } else {
    const labels = typeLabels(entry);
    kind.textContent = labels[0] ?? "분류 전";
    if (labels.length > 1) addText(kind, "span", labels.slice(1, 3).join(" · "), "sub");
  }

  const title = addText(item, "div", "", "title");
  addLink(title, entry.title, entry.url);
  const sub = addText(title, "span", "", "sub");
  const regions = regionsOf(entry);
  sub.textContent = [sourceLabel(entry), regions.length ? regions.join("·") : ""].filter(Boolean).join(" · ");
  if (isMaritime(entry)) {
    sub.append(" · ");
    addText(sub, "span", "해양수산 특화", "maritime");
  }

  const check = conditionCheck(entry, region, age);
  const box = addText(item, "div", "", "eligibility");
  const detail = entry.eligibility && entry.eligibility.length > 90 ? entry.eligibility.slice(0, 89) + "…" : entry.eligibility;
  if ((region || age) && check.confirmed) {
    box.classList.add("ok");
    const span = addText(box, "span", "");
    addText(span, "strong", "해당");
    span.append(detail || [regions.includes("전국") ? "전국 대상" : regions.join("·") + " 대상",
      stagesOf(entry).map((key) => AGE_LABELS[key]).filter(Boolean).join("·")].filter(Boolean).join(" · "));
  } else if (region || age) {
    const missing = [region && !check.regionKnown ? "지역" : "", age && !check.ageKnown ? "업력" : ""].filter(Boolean);
    addText(box, "span", `${missing.length ? missing.join("·") + " 조건 " : ""}공고문 확인 필요${detail ? " · " + detail : ""}`);
  } else {
    addText(box, "span", detail || (regions.length ? `${regions.join("·")} 대상` : "공고문에서 자격 확인"));
  }
}

/* ---------- 행사 일정 ---------- */

const started = (entry) => Boolean(entry.event_start) && entry.event_start < today;

function upcomingEvents() {
  return data.records.filter((entry) => ["domestic", "international"].includes(entry.category))
    .filter((entry) => {
      const last = entry.event_end || entry.event_start;
      return last ? last >= today : !isClosed(entry);
    })
    // Events still to start come first by date; long programs already under way follow.
    .sort((a, b) => Number(started(a)) - Number(started(b)) ||
      (a.event_start || "9999").localeCompare(b.event_start || "9999") || a.title.localeCompare(b.title, "ko"));
}

function fillSelect(select, label, values) {
  const current = select.value;
  select.replaceChildren();
  addText(select, "option", label).value = "";
  [...values].sort((a, b) => a.localeCompare(b, "ko")).forEach((value) => { addText(select, "option", value).value = value; });
  select.value = values.has(current) ? current : "";
}

function appendEvent(list, entry, compact = false) {
  const item = addText(list, "li", "", "event");
  const when = addText(item, "div", "", "when");
  if (started(entry)) {
    addText(when, "span", "진행 중");
    addText(when, "strong", entry.event_end ? `~${shortDate(entry.event_end)}` : "–");
  } else if (entry.event_start) {
    addText(when, "span", `${entry.event_start.slice(0, 4)}.${Number(entry.event_start.slice(5, 7))}월`);
    addText(when, "strong", String(Number(entry.event_start.slice(8, 10))));
  } else {
    addText(when, "strong", "–");
  }
  const body = addText(item, "div", "");
  addLink(body, entry.title, entry.url);
  if (compact) return;
  const end = entry.event_end && entry.event_end !== entry.event_start ? ` ~ ${shortDate(entry.event_end)}` : "";
  addText(body, "span", [entry.event_region || entry.place, (entry.event_types ?? []).join("·"),
    entry.event_start ? `${shortDate(entry.event_start)}${end}` : "",
    entry.deadline ? `신청 마감 ${shortDate(entry.deadline)}${entry.deadline_time ? " " + entry.deadline_time : ""}` : "",
    sourceLabel(entry)].filter(Boolean).join(" · "), "sub");
}

function renderEvents() {
  const events = upcomingEvents();
  const regionSelect = el("event-region");
  const typeSelect = el("event-type");
  if (!regionSelect.options.length) {
    fillSelect(regionSelect, "전체 지역", new Set(events.map((entry) => entry.event_region || entry.place).filter(Boolean)));
    fillSelect(typeSelect, "전체 유형", new Set(events.flatMap((entry) => entry.event_types ?? [])));
  }
  const shown = events.filter((entry) =>
    (!regionSelect.value || (entry.event_region || entry.place) === regionSelect.value) &&
    (!typeSelect.value || (entry.event_types ?? []).includes(typeSelect.value)));
  const list = el("event-list");
  list.replaceChildren();
  shown.slice(0, eventLimit).forEach((entry) => appendEvent(list, entry));
  if (!shown.length) addText(list, "li", "조건에 맞는 행사가 없습니다.", "empty");
  el("more-events").hidden = shown.length <= eventLimit;
}

/* ---------- 산업·기술 동향 ---------- */

function trendColumns(container, size) {
  container.replaceChildren();
  const byDate = (a, b) => (b.published || "").localeCompare(a.published || "");
  const columns = [
    ["산업·시장", data.records.filter((entry) => entry.category === "industry").sort(byDate)],
    ["특허·기술", data.records.filter((entry) => entry.category === "patent").sort(byDate)],
  ];
  for (const [title, entries] of columns) {
    const column = addText(container, "div", "", "column");
    addText(column, "h3", title);
    entries.slice(0, size).forEach((entry) => {
      const link = addLink(column, "", entry.url, "item");
      link.append(entry.title);
      addText(link, "span", [sourceLabel(entry), ...(entry.industry_sectors ?? []), entry.published && shortDate(entry.published)]
        .filter(Boolean).join(" · "));
    });
    if (title === "특허·기술") addText(column, "p", "특허 동향은 특허 데이터 연계 후 제공 예정");
  }
  const supply = addText(container, "div", "", "column");
  addText(supply, "h3", "공급망");
  const briefing = addLink(supply, "KMI 글로벌 공급망 AI 일일 브리핑 →", "https://scm-briefing.kmi.re.kr/", "item");
  addText(briefing, "span", "매일 갱신 · 해상 공급망 위기 모니터링");
  const events = addText(container, "div", "", "column");
  addText(events, "h3", "다가오는 행사");
  const list = addText(events, "ol", "", "plain-list");
  upcomingEvents().filter((entry) => entry.event_start && isMaritime(entry)).slice(0, size)
    .forEach((entry) => appendEvent(list, entry, true));
  if (!list.childElementCount) upcomingEvents().filter((entry) => entry.event_start).slice(0, size)
    .forEach((entry) => appendEvent(list, entry, true));
}

/* ---------- 지원기관 안내 ---------- */

function renderAgencies() {
  const open = supportScope().filter((entry) => !isClosed(entry));
  const inRegion = (entry, region) => region === "전국" ?
    regionsOf(entry).includes("전국") || !regionsOf(entry).length : regionsOf(entry).includes(region);
  const tiles = el("region-tiles");
  tiles.replaceChildren();
  for (const region of [...TILE_ORDER, "전국"]) {
    const agencies = new Set(open.filter((entry) => inRegion(entry, region)).map(sourceLabel));
    const button = addText(tiles, "button", "", region === "전국" ? "national" : "");
    button.type = "button";
    button.append(region === "전국" ? "전국 단위 기관" : region);
    addText(button, "small", `기관 ${agencies.size}`);
    button.setAttribute("aria-pressed", String(region === agencyRegion));
    button.addEventListener("click", () => { agencyRegion = region; renderAgencies(); });
  }
  const counts = new Map();
  open.filter((entry) => inRegion(entry, agencyRegion)).forEach((entry) => {
    counts.set(sourceLabel(entry), (counts.get(sourceLabel(entry)) ?? 0) + 1);
  });
  el("agency-region").textContent = agencyRegion === "전국" ? "전국 단위 기관" : agencyRegion;
  const rows = el("agency-rows");
  rows.replaceChildren();
  [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ko")).forEach(([name, count]) => {
    const row = addText(rows, "li", "", "agency");
    addText(row, "strong", name);
    addText(row, "span", `공고 ${count}건`);
  });
  if (!counts.size) addText(rows, "li", "이 지역에서 지금 수집된 공고가 없습니다.", "empty");
}

/* ---------- 화면 전환 ---------- */

function currentView() {
  const view = location.hash.replace("#", "");
  return ["support", "events", "trends", "agencies"].includes(view) ? view : "support";
}

function show() {
  const view = currentView();
  for (const name of ["support", "events", "trends", "agencies"]) el(`view-${name}`).hidden = name !== view;
  for (const link of document.querySelectorAll(".main-nav a")) {
    if (link.dataset.view === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  el("digest").hidden = view === "trends";
  if (view === "support") renderSupport();
  if (view === "events") renderEvents();
  if (view === "trends") trendColumns(el("trend-columns"), 20);
  if (view === "agencies") renderAgencies();
  trendColumns(el("digest-columns"), 3);
}

function resetSupport() {
  limit = PAGE;
  renderSupport();
}

function setup() {
  addText(el("region"), "option", "전체 지역").value = "";
  REGIONS.forEach((region) => { addText(el("region"), "option", region).value = region; });
  addText(el("benefit"), "option", "모든 지원").value = "";
  addText(el("benefit"), "option", "R&D 과제").value = "rnd";
  Object.entries(data.support_facets?.types ?? {}).forEach(([key, label]) => {
    addText(el("benefit"), "option", label).value = key;
  });
  for (const id of ["region", "age", "benefit", "maritime-only"]) el(id).addEventListener("change", resetSupport);
  el("query").addEventListener("input", resetSupport);
  for (const button of document.querySelectorAll(".status-tabs button")) {
    button.addEventListener("click", () => { status = button.dataset.status; resetSupport(); });
  }
  el("preset-koceanx").addEventListener("click", () => {
    el("region").value = "부산";
    el("age").value = "";
    resetSupport();
  });
  el("more").addEventListener("click", () => { limit += PAGE; renderSupport(); });
  el("event-region").addEventListener("change", () => { eventLimit = 40; renderEvents(); });
  el("event-type").addEventListener("change", () => { eventLimit = 40; renderEvents(); });
  el("more-events").addEventListener("click", () => { eventLimit += 40; renderEvents(); });
  window.addEventListener("hashchange", show);

  const timestamp = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short",
  }).format(new Date(data.updated_at));
  const agencies = new Set(supportScope().map(sourceLabel));
  el("support-meta").textContent =
    `지원기관 ${agencies.size.toLocaleString("ko-KR")}곳 · 공고 ${supportScope().length.toLocaleString("ko-KR")}건 · ${timestamp} 갱신`;
  el("updated").textContent = data.sample ? "저장된 응답으로 만든 시험 데이터" : `마지막 갱신 ${timestamp}`;
}

const dataUrl = new URL("./data.json", document.currentScript.src);
dataUrl.search = new URL(document.currentScript.src).search;
fetch(dataUrl, {cache: "no-cache"})
  .then((response) => {
    if (!response.ok) throw new Error("Data unavailable");
    return response.json();
  })
  .then((payload) => {
    data = payload;
    setup();
    show();
  })
  .catch(() => {
    el("support-meta").textContent = "정보를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.";
  });
