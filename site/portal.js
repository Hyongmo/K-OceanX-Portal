"use strict";

const el = (id) => document.getElementById(id);
const REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
  "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];
// Rough map order for the region tiles (four columns, north to south).
const TILE_ORDER = ["인천", "서울", "경기", "강원", "충남", "세종", "충북", "경북", "전북", "대전", "대구", "울산",
  "광주", "전남", "경남", "부산", "제주"];
// Company age bands follow the SME Startup Support Act (startup: 7 years, early: 3 years,
// new-industry startups: up to 10 years). Keys match target_rules.AGE_BANDS.
const AGE_LIST = [["prestartup", "예비창업"], ["y0_3", "3년 이내"], ["y3_7", "3~7년"], ["y7_10", "7~10년"], ["y10_plus", "10년 이상"]];
const AGE_LABELS = Object.fromEntries(AGE_LIST);
const PLANNING = {
  demand: "수요 제안", opinion: "RFP 의견", planning: "기획 지원", joint: "공동기획",
  preview: "공모 예고", application: "본공모",
};
const SYNONYMS = [
  ["스마트항만", "스마트 항만", "항만자동화", "항만 자동화"],
  ["스마트양식", "스마트 양식", "지능형양식", "양식 자동화"],
  ["자율운항", "자율 운항", "무인선박", "무인 선박"],
  ["인공지능", "AI"],
  ["사업화", "상용화"],
  ["해상공급망", "해상 공급망", "해운 공급망"],
];

const today = new Intl.DateTimeFormat("sv-SE", {timeZone: "Asia/Seoul"}).format(new Date());
const nowInSeoul = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
}).format(new Date());

let data = {records: [], sources: {}, support_facets: {}};
let limit = 30;
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
// Regions come from the notice's own text (collected into support.regions), not from its publisher.
const regionsOf = (entry) => entry.support?.regions ?? [];
const agesOf = (entry) => entry.ages ?? [];
// Ocean events and notices are marked by the collector's judging step (judging.py), one rule for all.

function isClosed(entry) {
  if (/\[\s*(?:접수\s*)?마감\s*\]/.test(entry.title)) return true;
  if (!entry.deadline) return false;
  return entry.deadline < today || (entry.deadline === today && Boolean(entry.deadline_time) && entry.deadline_time <= nowInSeoul);
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

// Industries: the nine top-level classes of the ocean and fisheries industry classification
// (Statistics Korea, 2018). Keys match target_rules.INDUSTRIES.
const INDUSTRY_LIST = [
  ["resource", "해양자원 개발·건설"], ["port", "해운·항만"], ["ship", "선박·해양플랜트 건조·수리"],
  ["fish_catch", "수산물 생산(어업·양식)"], ["fish_process", "수산물 가공"], ["fish_trade", "수산물 유통"],
  ["leisure", "해양수산 레저·관광"], ["equipment", "해양수산 기자재 제조"], ["service", "해양수산 관련 서비스"],
];
const ALL_MARITIME = "maritime_all";
const FISHERIES = ["fish_catch", "fish_process", "fish_trade"];
// Ocean and fisheries technology: the 13 top-level classes of the KIMST classification (2024).
const MARINE_TECH_LIST = [
  ["m_resource", "해양자원"], ["m_environment", "해양환경"], ["m_life", "해양수산생명"],
  ["m_observation", "해양관측·예보"], ["m_engineering", "해양공학"], ["m_disaster", "해양재해·방재"],
  ["m_coast_port", "해안·항만"], ["m_safety", "해양안전·교통"], ["m_polar", "극지과학"],
  ["m_aquaculture", "수산양식"], ["m_stock", "수산자원·어장환경"], ["m_fishing", "어업생산·이용가공"],
  ["m_infra", "해양수산 연구인프라"],
];
// Innovative technology: the 12 new industries of the Ministry of SMEs and Startups (2026).
const INNOVATION_LIST = [
  ["ai", "AI 모델·인프라"], ["semiconductor", "반도체"], ["mobility", "모빌리티"],
  ["quantum_security", "양자·보안·네트워크"], ["robotics", "로보틱스"], ["life", "생명·신약"],
  ["healthcare", "헬스케어"], ["content", "콘텐츠"], ["defense_space", "방산·우주항공·해양"],
  ["green", "친환경"], ["energy", "에너지·원자력·핵융합"], ["advanced_manufacturing", "첨단제조"],
];
const LABELS = Object.fromEntries([...INDUSTRY_LIST, ...MARINE_TECH_LIST, ...INNOVATION_LIST, [ALL_MARITIME, "해양수산 전체"]]);
// Manufacturing programs fit these industries; for the others they need a check.
const MAKERS = new Set(["resource", "ship", "fish_process", "equipment"]);
const BENEFITS = [
  ["rnd", "R&D 과제", []], ["fund", "자금·투자", ["finance"]],
  ["test", "실증·시험·인프라", ["testing", "infrastructure", "certification"]], ["export", "수출·해외진출", ["export"]],
  ["biz", "판로·사업화·기술지원", ["commercial", "technical", "research"]], ["people", "인재·교육", ["people"]],
  ["grow", "창업보육·경영·IP", ["incubation", "management"]], ["etc", "기타", []],
];
const BENEFIT_LABELS = Object.fromEntries(BENEFITS.map(([key, label]) => [key, label]));
const FINDER_PAGE = 30;
// Two tabs. "신청 가능 공고" leaves out what the company cannot apply to;
// "특정 분야 공고" keeps only the notices that match every chosen condition.
const STORE = "koceanx-finder-4";
const TABS = ["company", "notice"];
const blank = () => ({industries: [], techs: [], regions: [], ages: [], benefits: []});
let finder = {tab: "company", company: blank(), notice: blank()};
try {
  const saved = JSON.parse(localStorage.getItem(STORE) || "{}");
  if (TABS.includes(saved.tab)) finder.tab = saved.tab;
  for (const tab of TABS) {
    for (const key of Object.keys(blank())) {
      if (Array.isArray(saved[tab]?.[key])) finder[tab][key] = saved[tab][key];
    }
  }
} catch { /* storage may be blocked */ }

function supportScope() {
  return data.records.filter((entry) => entry.category === "support" || entry.category === "rnd");
}

function benefitsOf(entry) {
  if (entry.category === "rnd") return ["rnd"];
  const types = entry.support?.types ?? [];
  const keys = BENEFITS.filter(([, , members]) => members.some((type) => types.includes(type))).map(([key]) => key);
  return keys.length ? keys : ["etc"];
}

const techsOf = (entry) => [...(entry.marine_tech ?? []), ...(entry.innovation ?? [])];
const isMaritimeNotice = (entry) => Boolean((entry.industries ?? []).length || entry.maritime_common);
// R&D tasks are fixed on their technology; other notices only when the target line names technology companies.
const techLimits = (entry) => entry.category === "rnd" ? techsOf(entry) : (entry.tech_only ?? []);
const techOk = (entry, picks) => !picks.techs.length || techsOf(entry).some((key) => picks.techs.includes(key));
const benefitOk = (entry, picks) => !picks.benefits.length || benefitsOf(entry).some((key) => picks.benefits.includes(key));

function industryNames(keys) {
  const names = FISHERIES.every((key) => keys.includes(key)) ?
    ["수산", ...keys.filter((key) => !FISHERIES.includes(key)).map((key) => LABELS[key])] : keys.map((key) => LABELS[key]);
  return names.join("·");
}

// 신청 가능 공고: what the company cannot apply to is left out.
function companyCheck(entry, picks) {
  const regions = regionsOf(entry);
  const ages = agesOf(entry);
  const age = picks.ages[0];
  if (picks.regions.length && regions.length && !regions.includes("전국") &&
    !regions.some((region) => picks.regions.includes(region))) return {out: "region"};
  if (age && ages.length && !ages.includes(age)) return {out: "age"};
  const limits = techLimits(entry);
  if (picks.techs.length && limits.length && !limits.some((key) => picks.techs.includes(key))) return {out: "tech"};
  const industries = entry.industries ?? [];
  if (picks.industries.length && industries.length && !industries.some((key) => picks.industries.includes(key))) {
    return {out: "industry"};
  }
  return {check: Boolean(entry.manufacturing && picks.industries.length &&
    !picks.industries.some((key) => MAKERS.has(key)))};
}

// 특정 분야 공고: every chosen item must match; choices within one item add up.
function noticeMatches(entry, picks) {
  const industries = entry.industries ?? [];
  if (picks.industries.length && !picks.industries.some((key) =>
    key === ALL_MARITIME ? isMaritimeNotice(entry) : industries.includes(key))) return false;
  if (!techOk(entry, picks)) return false;
  if (picks.regions.length && !regionsOf(entry).some((region) => picks.regions.includes(region))) return false;
  if (picks.ages.length && !agesOf(entry).some((age) => picks.ages.includes(age))) return false;
  return benefitOk(entry, picks);
}

function industryTag(entry) {
  const industries = entry.industries ?? [];
  if (industries.length) return ["mine", `${industryNames(industries)} 기업 대상`];
  if (entry.maritime_common) return ["common", "해양수산 기업 전체"];
  return ["", "업종 제한 없음"];
}

function companyTags(entry, picks, fit) {
  const tags = [industryTag(entry)];
  if (picks.industries.length && tags[0][0] !== "mine") tags[0][0] = tags[0][0] || "ok";
  if (picks.techs.length) {
    const mine = techLimits(entry).filter((key) => picks.techs.includes(key));
    tags.push(mine.length ? ["mine", `${mine.map((key) => LABELS[key]).join("·")} 기술 대상`] : ["ok", "기술 제한 없음"]);
  }
  if (fit?.check) tags.push(["", "제조기업 한정 가능성"]);
  const regions = regionsOf(entry);
  if (picks.regions.length) {
    const mine = regions.filter((region) => picks.regions.includes(region));
    tags.push(mine.length ? ["ok", `${mine.join("·")} 기업 대상`] :
      regions.includes("전국") ? ["ok", "전국 대상"] : ["", "지역: 공고문 확인"]);
  } else if (regions.length) {
    tags.push(["", regions.join("·")]);
  }
  const age = picks.ages[0];
  if (age) tags.push(agesOf(entry).includes(age) ? ["ok", `업력 ${AGE_LABELS[age]} 대상`] : ["ok", "업력 제한 없음"]);
  return tags;
}

function noticeTags(entry, picks) {
  const tags = [industryTag(entry)];
  const techs = techsOf(entry).filter((key) => !picks.techs.length || picks.techs.includes(key));
  if (techs.length) tags.push(["tech", `${techs.map((key) => LABELS[key]).join("·")} 관련`]);
  const regions = regionsOf(entry);
  if (regions.length) tags.push([picks.regions.length ? "mine" : "", regions.join("·")]);
  const ages = agesOf(entry);
  if (ages.length && ages.length < AGE_LIST.length) {
    tags.push([picks.ages.length ? "mine" : "", `업력 ${ages.map((age) => AGE_LABELS[age]).join("·")}`]);
  }
  return tags;
}

function noticeRow(list, entry, tags) {
  const item = addText(list, "li", "");
  const due = addText(item, "div", "", "due");
  if (entry.deadline) {
    const left = days(entry.deadline);
    const closed = isClosed(entry);
    if (!closed && left <= 7) due.classList.add("urgent");
    addText(due, "strong", closed ? "마감" : left === 0 ? "오늘 마감" : `D-${left}`);
    addText(due, "span", shortDate(entry.deadline) + (entry.deadline_time ? " " + entry.deadline_time : ""));
    if (!closed && entry.opens && entry.opens > today) addText(due, "span", `${shortDate(entry.opens)} 접수 시작`);
  } else {
    addText(due, "strong", entry.period_note || "공고문 확인");
    addText(due, "span", "마감일 없음");
  }
  const body = addText(item, "div", "", "title");
  addLink(body, entry.title, entry.url);
  const reasons = addText(body, "div", "", "reasons");
  addText(reasons, "span", sourceLabel(entry));
  const kinds = benefitsOf(entry).filter((key) => key !== "etc").map((key) => BENEFIT_LABELS[key]);
  if (kinds.length) addText(reasons, "span", kinds.join("·"), "tag kind");
  for (const [kind, text] of tags) addText(reasons, "span", text, kind ? `tag ${kind}` : "tag");
}

const byDeadline = (a, b) => (a.deadline || "9999").localeCompare(b.deadline || "9999") ||
  (a.deadline_time || "23:59").localeCompare(b.deadline_time || "23:59") || a.title.localeCompare(b.title, "ko");

function saveFinder() {
  try { localStorage.setItem(STORE, JSON.stringify(finder)); } catch { /* storage may be blocked */ }
}

function pressChips(container, chosen) {
  for (const chip of container.children) chip.setAttribute("aria-pressed", String(chosen.includes(chip.dataset.key)));
}

function summaryLine(tab, picks, count) {
  const summary = el("finder-summary");
  summary.replaceChildren();
  const strong = (text) => addText(summary, "strong", text);
  const techs = picks.techs.map((key) => LABELS[key]).join("·");
  const kinds = picks.benefits.map((key) => BENEFIT_LABELS[key]).join("·");
  if (tab === "company") {
    const company = [picks.regions.length && `${picks.regions.join("·")} 소재`,
      picks.industries.length && industryNames(picks.industries), techs && `${techs} 기술`,
      picks.ages[0] && `업력 ${AGE_LABELS[picks.ages[0]]}`].filter(Boolean);
    if (company.length) {
      strong(company.join(" · "));
      summary.append(" 기업 신청 가능 ");
    } else if (!kinds) {
      summary.append("현재 접수 가능한 모든 ");
    }
    if (kinds) { strong(kinds); summary.append(" "); }
  } else {
    const parts = [picks.regions.length && `${picks.regions.join("·")} 지역 대상`,
      picks.industries.length && picks.industries.map((key) => key === ALL_MARITIME ? "해양수산 분야" : LABELS[key]).join("·"),
      techs && `${techs} 관련`, picks.ages.length && `업력 ${picks.ages.map((age) => AGE_LABELS[age]).join("·")} 대상`, kinds]
      .filter(Boolean);
    if (parts.length) { strong(parts.join(" · ")); summary.append(" "); } else summary.append("현재 접수 가능한 모든 ");
  }
  summary.append("공고 ");
  addText(summary, "span", `${count.toLocaleString("ko-KR")}건`, "count");
}

function renderSupport() {
  const tab = finder.tab;
  const picks = finder[tab];
  for (const name of TABS) {
    el(`tab-${name}`).setAttribute("aria-selected", String(name === tab));
    el(`panel-${name}`).hidden = name !== tab;
  }
  const prefix = tab === "company" ? "c" : "n";
  pressChips(el(`${prefix}-industries`), picks.industries);
  pressChips(el(`${prefix}-marine-tech`), picks.techs);
  pressChips(el(`${prefix}-innovation`), picks.techs);
  pressChips(el(`${prefix}-regions`), picks.regions);
  pressChips(el(`${prefix}-ages`), picks.ages);
  pressChips(el(`${prefix}-benefits`), picks.benefits);

  const terms = searchTerms(el("query").value.trim());
  const shown = [];
  const closed = [];
  const counts = Object.fromEntries(BENEFITS.map(([key]) => [key, 0]));
  const anyKind = {...picks, benefits: []};
  for (const entry of supportScope()) {
    if (!matches(entry, terms)) continue;
    let fit = {};
    let keep;
    let keepAnyKind;
    if (tab === "company") {
      fit = companyCheck(entry, picks);
      keepAnyKind = !fit.out;
      keep = keepAnyKind && benefitOk(entry, picks);
    } else {
      keepAnyKind = noticeMatches(entry, anyKind);
      keep = noticeMatches(entry, picks);
    }
    const row = [entry, tab === "company" ? companyTags(entry, picks, fit) : noticeTags(entry, picks)];
    if (isClosed(entry)) {
      if (keep) closed.push(row);
      continue;
    }
    // Support chips count what the other choices leave, so each number says what a press would show.
    if (keepAnyKind) benefitsOf(entry).forEach((key) => { counts[key] += 1; });
    if (keep) shown.push(row);
  }
  for (const chip of el(`${prefix}-benefits`).children) chip.querySelector("small").textContent = counts[chip.dataset.key];

  summaryLine(tab, picks, shown.length);

  // Notices with a deadline come first; those open until the budget runs out or all year round
  // ("상시·예산 소진 시") are grouped below them (user decision 2026-11-22).
  shown.sort((a, b) => byDeadline(a[0], b[0]));
  const dated = shown.filter(([entry]) => entry.deadline);
  const open = shown.filter(([entry]) => !entry.deadline);
  const list = el("result-list");
  list.replaceChildren();
  dated.slice(0, limit).forEach(([entry, tags]) => noticeRow(list, entry, tags));
  if (!dated.length) {
    addText(list, "li", open.length ? "마감일이 정해진 공고 없음 · 아래 상시·예산 소진 시 공고 확인"
      : "해당 공고 없음 · 선택 항목 또는 검색어 변경 필요", "empty");
  }
  el("more").hidden = dated.length <= limit;
  el("more").textContent = `${(dated.length - limit).toLocaleString("ko-KR")}건 더 보기`;
  el("open-wrap").hidden = !open.length;
  el("open-summary").textContent = `상시·예산 소진 시 공고 ${open.length.toLocaleString("ko-KR")}건`;
  const openList = el("open-list");
  openList.replaceChildren();
  open.forEach(([entry, tags]) => noticeRow(openList, entry, tags));

  const ended = closed.sort((a, b) => byDeadline(b[0], a[0]));
  el("closed-summary").textContent = `같은 조건의 마감 공고 ${ended.length}건`;
  const closedList = el("closed-list");
  closedList.replaceChildren();
  ended.forEach(([entry, tags]) => noticeRow(closedList, entry, tags));
}

function chipGroup(container, items, tab, field, single) {
  for (const [key, label] of items) {
    const chip = addText(container, "button", label);
    chip.type = "button";
    chip.dataset.key = key;
    chip.addEventListener("click", () => {
      const chosen = finder[tab][field];
      if (chosen.includes(key)) finder[tab][field] = chosen.filter((value) => value !== key);
      else finder[tab][field] = single ? [key] : [...chosen, key];
      resetSupport();
    });
  }
}

function setupSupport() {
  for (const [tab, prefix] of [["company", "c"], ["notice", "n"]]) {
    const industries = tab === "notice" ? [[ALL_MARITIME, "해양수산 전체"], ...INDUSTRY_LIST] : INDUSTRY_LIST;
    chipGroup(el(`${prefix}-industries`), industries, tab, "industries");
    chipGroup(el(`${prefix}-marine-tech`), MARINE_TECH_LIST, tab, "techs");
    chipGroup(el(`${prefix}-innovation`), INNOVATION_LIST, tab, "techs");
    chipGroup(el(`${prefix}-regions`), REGIONS.map((region) => [region, region]), tab, "regions");
    chipGroup(el(`${prefix}-ages`), AGE_LIST, tab, "ages", tab === "company");
    chipGroup(el(`${prefix}-benefits`), BENEFITS.map(([key, label]) => [key, label]), tab, "benefits");
    for (const chip of el(`${prefix}-benefits`).children) addText(chip, "small", "", "chip-count");
    el(`tab-${tab}`).addEventListener("click", () => { finder.tab = tab; resetSupport(); });
  }
  el("finder-reset").addEventListener("click", () => {
    finder[finder.tab] = blank();
    resetSupport();
  });
  el("query").addEventListener("input", () => { limit = FINDER_PAGE; renderSupport(); });
  el("more").addEventListener("click", () => { limit += FINDER_PAGE; renderSupport(); });
}

function resetSupport() {
  limit = FINDER_PAGE;
  saveFinder();
  renderSupport();
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

/* ---------- 지원기관 안내 ---------- */

let agencyName = "";

// Agencies are grouped by where they sit (from their own name or supervising authority);
// this guide is about the agencies, not about who may apply to a notice.
const agencyRegionOf = (entry) => entry.agency_region || "전국";
const agencyLabel = (entry) => entry.agency || sourceLabel(entry);

// Every agency seen so far stays listed, also when it has no notice today.
function agencyDirectory(open) {
  const directory = new Map(Object.entries(data.agencies ?? {}).map(([name, info]) =>
    [name, {region: info.region || "전국", lastSeen: info.last_seen || "", notices: []}]));
  for (const entry of open) {
    const name = agencyLabel(entry);
    const info = directory.get(name) ?? {region: agencyRegionOf(entry), lastSeen: "", notices: []};
    info.notices.push(entry);
    directory.set(name, info);
  }
  return directory;
}

function renderAgencies() {
  const directory = agencyDirectory(supportScope().filter((entry) => !isClosed(entry)));
  const tiles = el("region-tiles");
  tiles.replaceChildren();
  for (const region of [...TILE_ORDER, "전국"]) {
    const count = [...directory.values()].filter((info) => info.region === region).length;
    const button = addText(tiles, "button", "", region === "전국" ? "national" : "");
    button.type = "button";
    button.append(region === "전국" ? "전국 단위 기관" : region);
    addText(button, "small", `기관 ${count}`);
    button.setAttribute("aria-pressed", String(region === agencyRegion));
    button.addEventListener("click", () => { agencyRegion = region; agencyName = ""; renderAgencies(); });
  }
  const agencies = [...directory].filter(([, info]) => info.region === agencyRegion);
  el("agency-region").textContent = agencyRegion === "전국" ? "전국 단위 기관" : `${agencyRegion} 소재 기관`;
  const rows = el("agency-rows");
  rows.replaceChildren();
  agencies.sort((a, b) => b[1].notices.length - a[1].notices.length || a[0].localeCompare(b[0], "ko"))
    .forEach(([name, info]) => {
      const row = addText(rows, "li", "", info.notices.length ? "agency" : "agency idle");
      const button = addText(row, "button", name);
      button.type = "button";
      button.setAttribute("aria-pressed", String(name === agencyName));
      button.addEventListener("click", () => {
        agencyName = name;
        renderAgencies();
        el("agency-detail").scrollIntoView({block: "start"});
      });
      addText(row, "span", `게시 중 공고 ${info.notices.length}건`);
    });
  if (!agencies.length) addText(rows, "li", "이 지역에서 확인된 기관이 아직 없습니다.", "empty");
  renderAgencyDetail(directory.get(agencyName));
}

function renderAgencyDetail(info) {
  const detail = el("agency-detail");
  detail.hidden = !info;
  if (!info) return;
  el("agency-name").textContent = agencyName;
  const place = info.region === "전국" ? "전국 단위" : info.region;
  el("agency-facts").textContent = info.notices.length ?
    `소재지 ${place} · 게시 중 공고 ${info.notices.length}건 · 제목을 누르면 원문 공고로 이동` :
    `소재지 ${place} · 지금 게시 중인 공고 없음` + (info.lastSeen ? ` · 마지막 공고 확인 ${info.lastSeen}` : "");
  const notices = el("agency-notices");
  notices.replaceChildren();
  [...info.notices].sort(byDeadline).forEach((entry) => noticeRow(notices, entry, []));
}

/* ---------- 화면 전환 ---------- */

function currentView() {
  const view = location.hash.replace("#", "");
  return ["support", "events", "agencies"].includes(view) ? view : "support";
}

function show() {
  const view = currentView();
  for (const name of ["support", "events", "agencies"]) el(`view-${name}`).hidden = name !== view;
  for (const link of document.querySelectorAll(".main-nav a")) {
    if (link.dataset.view === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (view === "support") renderSupport();
  if (view === "events") renderEvents();
  if (view === "agencies") renderAgencies();
}

function setup() {
  setupSupport();
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
