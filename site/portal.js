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
const regionsOf = (entry) => entry.support?.regions ?? (REGIONS.includes(entry.place) ? [entry.place] : []);
const agesOf = (entry) => entry.ages ?? [];
const isMaritime = (entry) => Boolean(entry.maritime) || MARITIME_SOURCES.has(entry.source) || MARITIME.test(entry.title);

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
const LABELS = Object.fromEntries([...INDUSTRY_LIST, ...MARINE_TECH_LIST, ...INNOVATION_LIST]);
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
// A new key so that earlier saved defaults (such as Busan) do not carry over.
const STORE = "koceanx-finder-2";
let finder = {industries: [], techs: [], regions: [], age: "", benefits: []};
try {
  const saved = JSON.parse(localStorage.getItem(STORE) || "{}");
  if (Array.isArray(saved.industries)) {
    for (const key of Object.keys(finder)) if (key in saved) finder[key] = saved[key];
    if (!Array.isArray(saved.regions)) finder.regions = saved.region ? [saved.region] : [];
    if (!AGE_LABELS[finder.age]) finder.age = "";
    if (!Array.isArray(finder.benefits)) finder.benefits = [];
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

function industryNames(keys) {
  const names = FISHERIES.every((key) => keys.includes(key)) ?
    ["수산", ...keys.filter((key) => !FISHERIES.includes(key)).map((key) => LABELS[key])] : keys.map((key) => LABELS[key]);
  return names.join("·");
}

// Where a notice stands for the chosen company: one of the groups, or left out.
function placeFor(entry) {
  const regions = regionsOf(entry);
  const ages = agesOf(entry);
  if (finder.regions.length && regions.length && !regions.includes("전국") &&
    !regions.some((region) => finder.regions.includes(region))) return {out: "region"};
  if (finder.age && ages.length && !ages.includes(finder.age)) return {out: "age"};
  const industries = entry.industries ?? [];
  if (industries.length) {
    if (!finder.industries.length) return {group: "industry", keys: industries};
    const keys = industries.filter((key) => finder.industries.includes(key));
    return keys.length ? {group: "industry", keys} : {out: "industry"};
  }
  const techs = techsOf(entry).filter((key) => finder.techs.includes(key));
  if (techs.length) return {group: "tech", keys: techs};
  if (entry.maritime_common || MARITIME_SOURCES.has(entry.source)) return {group: "common"};
  // R&D aimed at another field is left out only once the company has named its industries.
  if (entry.category === "rnd" && !entry.open_rnd && finder.industries.length) return {out: "rnd"};
  if (entry.manufacturing && finder.industries.length && !finder.industries.some((key) => MAKERS.has(key))) return {group: "check"};
  return {group: "open"};
}

function reasonTags(entry, place) {
  const tags = [];
  const regions = regionsOf(entry);
  if (place.group === "industry") tags.push(["mine", `${industryNames(place.keys)} 기업 대상`]);
  else if (place.group === "tech") tags.push(["tech", `${place.keys.map((key) => LABELS[key]).join("·")} 기술`]);
  else if (place.group === "common") tags.push(["common", "해양수산 기업 대상"]);
  else if (place.group === "check") tags.push(["", "제조기업 대상일 수 있음"]);
  else tags.push(["ok", "분야 제한 없음"]);
  if (finder.regions.length) {
    const mine = regions.filter((region) => finder.regions.includes(region));
    tags.push(mine.length ? ["ok", `${mine.join("·")} 기업 대상`] :
      regions.includes("전국") ? ["ok", "전국 대상"] : ["", "지역은 공고문 확인"]);
  }
  if (finder.age) tags.push(agesOf(entry).includes(finder.age) ? ["ok", `업력 ${AGE_LABELS[finder.age]} 대상`] : ["ok", "업력 제한 없음"]);
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

function renderSupport() {
  renderMine();
}

function renderMine() {
  pressChips(el("industries"), finder.industries);
  pressChips(el("marine-tech"), finder.techs);
  pressChips(el("innovation"), finder.techs);
  pressChips(el("regions"), finder.regions);
  pressChips(el("ages"), [finder.age]);
  pressChips(el("benefits"), finder.benefits);
  const terms = searchTerms(el("query").value.trim());
  const placed = [];
  const out = {region: 0, age: 0, industry: 0, rnd: 0};
  const closed = [];
  for (const entry of supportScope()) {
    if (!matches(entry, terms)) continue;
    const place = placeFor(entry);
    if (isClosed(entry)) {
      if (!place.out) closed.push([entry, place]);
      continue;
    }
    if (place.out) out[place.out] += 1;
    else placed.push([entry, place]);
  }
  // Each support chip shows how many notices the company could apply to of that kind.
  const counts = Object.fromEntries(BENEFITS.map(([key]) => [key, 0]));
  placed.forEach(([entry]) => benefitsOf(entry).forEach((key) => { counts[key] += 1; }));
  for (const chip of el("benefits").children) chip.querySelector("small").textContent = counts[chip.dataset.key];
  const wanted = ([entry]) => !finder.benefits.length || benefitsOf(entry).some((key) => finder.benefits.includes(key));
  const groups = {industry: [], tech: [], common: [], open: [], check: []};
  placed.filter(wanted).forEach((item) => groups[item[1].group].push(item));

  const total = Object.values(groups).reduce((sum, list) => sum + list.length, 0);
  const who = [finder.regions.length && `${finder.regions.join("·")} 소재`, finder.industries.length && industryNames(finder.industries),
    finder.age && `업력 ${AGE_LABELS[finder.age]}`].filter(Boolean).join(" · ") || "모든";
  const summary = el("finder-summary");
  summary.replaceChildren();
  addText(summary, "strong", who);
  summary.append(" 기업이 지금 신청할 수 있는 ");
  if (finder.benefits.length) addText(summary, "strong", finder.benefits.map((key) => BENEFIT_LABELS[key]).join("·"));
  summary.append(finder.benefits.length ? " 공고 " : "공고 ");
  addText(summary, "span", `${total.toLocaleString("ko-KR")}건`, "count");
  if (!finder.industries.length) summary.append(" · 종사업종을 고르면 더 좁혀집니다");
  const parts = [out.industry && `다른 업종 대상 ${out.industry}건`, out.rnd && `해양수산 외 분야 R&D ${out.rnd}건`,
    out.region && `다른 지역 ${out.region}건`, out.age && `업력 불일치 ${out.age}건`].filter(Boolean);
  el("finder-excluded").textContent = parts.length ? `걸러 낸 공고: ${parts.join(" · ")}` : "";

  el("mine-title").textContent = [`업종 대상 ${groups.industry.length}건`,
    finder.techs.length ? `선택 기술 ${groups.tech.length}건` : "", `해양수산 공통 ${groups.common.length}건`]
    .filter(Boolean).join(" · ");
  el("mine-note").textContent = finder.industries.length ?
    "우리 업종을 대상으로 한 공고, 선택 기술에 해당하는 공고, 해양수산 기업 전체 대상 공고 순으로 보여 드립니다." :
    "종사업종을 고르면 우리 업종 공고만 남고 다른 업종 대상 공고는 빠집니다.";
  const mine = el("mine-list");
  mine.replaceChildren();
  for (const [group, title] of [["industry", "우리 업종 대상"], ["tech", "선택 기술 관련"], ["common", "해양수산 기업 공통"]]) {
    const members = groups[group].sort((a, b) => byDeadline(a[0], b[0]));
    if (!members.length) continue;
    addText(mine, "li", `${title} · ${members.length}건`, "group-label");
    members.forEach(([entry, place]) => noticeRow(mine, entry, reasonTags(entry, place)));
  }
  if (!mine.children.length) addText(mine, "li", "지금은 우리 회사를 위한 공고가 없습니다.", "empty");

  const shown = groups.open.sort((a, b) => byDeadline(a[0], b[0]));
  el("open-title").textContent = `분야 제한 없이 신청할 수 있는 지원사업 · ${shown.length.toLocaleString("ko-KR")}건`;
  // R&D aimed at our industry or at ocean and fisheries companies sits in section 2.
  const aboveRnd = [...groups.industry, ...groups.tech, ...groups.common].filter(([entry]) => entry.category === "rnd").length;
  el("open-note").textContent = finder.benefits.includes("rnd") && aboveRnd ?
    ` 우리 업종·해양수산 관련 R&D ${aboveRnd}건은 위 2번에 있습니다.` : "";
  const openList = el("open-list");
  openList.replaceChildren();
  shown.slice(0, limit).forEach(([entry, place]) => noticeRow(openList, entry, reasonTags(entry, place)));
  if (!shown.length) addText(openList, "li", "조건에 맞는 공고가 없습니다. 조건이나 검색어를 바꿔 보세요.", "empty");
  el("more").hidden = shown.length <= limit;
  el("more").textContent = `${(shown.length - limit).toLocaleString("ko-KR")}건 더 보기`;

  const check = groups.check.sort((a, b) => byDeadline(a[0], b[0]));
  el("check-wrap").hidden = !check.length;
  el("check-summary").textContent = `자격 확인이 필요한 공고 ${check.length}건 · 제조기업만 신청할 수 있을 수 있음`;
  const checkList = el("check-list");
  checkList.replaceChildren();
  check.forEach(([entry, place]) => noticeRow(checkList, entry, reasonTags(entry, place)));

  // Closed notices that fit the same choices, latest deadline first, for reference.
  const ended = closed.filter(wanted).sort((a, b) => byDeadline(b[0], a[0]));
  el("closed-summary").textContent = `조건에 맞는 마감된 공고 ${ended.length}건 보기`;
  const closedList = el("closed-list");
  closedList.replaceChildren();
  ended.forEach(([entry, place]) => noticeRow(closedList, entry, reasonTags(entry, place)));
}

function chipGroup(container, items, owner, field) {
  for (const [key, label] of items) {
    const chip = addText(container, "button", label);
    chip.type = "button";
    chip.dataset.key = key;
    chip.addEventListener("click", () => {
      const target = owner();
      const list = target[field];
      target[field] = list.includes(key) ? list.filter((value) => value !== key) : [...list, key];
      resetSupport();
    });
  }
}

function setupSupport() {
  const mine = () => finder;
  chipGroup(el("industries"), INDUSTRY_LIST, mine, "industries");
  chipGroup(el("marine-tech"), MARINE_TECH_LIST, mine, "techs");
  chipGroup(el("innovation"), INNOVATION_LIST, mine, "techs");
  chipGroup(el("regions"), REGIONS.map((region) => [region, region]), mine, "regions");
  // A company has one age band; pressing the chosen band again clears it.
  for (const [key, label] of AGE_LIST) {
    const chip = addText(el("ages"), "button", label);
    chip.type = "button";
    chip.dataset.key = key;
    chip.addEventListener("click", () => { finder.age = finder.age === key ? "" : key; resetSupport(); });
  }
  chipGroup(el("benefits"), BENEFITS.map(([key, label]) => [key, label]), mine, "benefits");
  for (const chip of el("benefits").children) addText(chip, "small", "", "chip-count");
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
