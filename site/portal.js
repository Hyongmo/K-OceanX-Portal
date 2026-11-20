"use strict";

const categories = {
  all: "전체", rnd: "R&D·기획", patent: "특허·기술", industry: "산업동향",
  international: "국제 행사", domestic: "국내 행사", support: "기업지원·인증",
};
const areaGroups = [
  ["공고·지원", "rnd", "support"],
  ["시장·기술정보", "patent", "industry"],
  ["행사·네트워킹", "domestic", "international"],
];
const planningStages = {
  demand: "수요 제안", opinion: "RFP 의견 제출", planning: "기획비·컨설팅 신청",
  joint: "공동기획 참여", preview: "공모 예고", application: "본공모 신청",
};
const planningActions = {
  demand: "공고의 조사 분야와 제안서 양식을 확인하세요.",
  opinion: "RFP 초안에서 기술 범위와 일정에 대한 의견을 준비하세요.",
  planning: "기획비 지원 항목과 주관기관 자격을 확인하세요.",
  joint: "필요한 대학·연구기관과 컨소시엄 조건을 확인하세요.",
};
const briefingNotes = {
  "nipa:17006": {
    title: "첨단 GPU 베타서비스 참여자를 모집합니다",
    lead: "과기정통부와 NIPA가 첨단 GPU 자원의 배분·운영을 시험합니다. AI 모델 개발에 컴퓨팅 자원이 필요한 팀은 이용 조건과 신청 자격을 확인하세요.",
  },
  "keit_planning:001026": {
    title: "제조 현장의 작업 노하우를 AI로 활용할 기술 수요를 받습니다",
    lead: "KEIT가 2027년 제조 AX 과제 기획에 반영할 아이디어를 받습니다. 작업자의 노하우를 데이터로 활용하려는 조선·기자재 기업은 조사 분야와 제안 양식을 살펴보세요.",
  },
  "kstartup:179815": {
    title: "KDB NextONE 부산, 7년 이내 창업법인 모집",
    lead: "혁신성장산업에 해당하는 창업 7년 이내 법인이 신청할 수 있습니다. 부산 해양, 울산 AI·산업 AX, 경남 조선해양은 공고에 명시된 지역별 우대 분야입니다.",
  },
  "kstartup:179832": {
    title: "기술 수요기업과 1:1로 만날 스타트업을 찾습니다",
    lead: "대구창조경제혁신센터가 기술소개자료를 수요기업에 전달하고, 매칭된 기업의 1:1 미팅을 연결합니다. 지원 전에 수요 분야와 참여기업 목록을 확인하세요.",
  },
  "kstartup:179824": {
    title: "송파ICT청년창업지원센터, 2027년 입주기업 모집",
    lead: "만 39세 이하 ICT·AI·빅데이터 분야 예비창업자와 창업 3년 이하 기업이 대상입니다. 사무공간과 멘토링을 제공하며 입주 후 사업장 등록 또는 이전 조건이 있습니다.",
  },
  "kotra:245160": {
    title: "일본 조선업 투자 확대, 기자재 기업이 살펴볼 변화",
    lead: "KOTRA가 일본 조선업의 투자 움직임을 전했습니다. 일본 진출을 검토하는 조선·해양 기자재 기업은 설비 투자와 공급망 변화를 살펴보세요.",
  },
};
const synonyms = [
  ["스마트항만", "스마트 항만", "항만자동화", "항만 자동화"],
  ["스마트양식", "스마트 양식", "지능형양식", "양식 자동화"],
  ["자율운항", "자율 운항", "무인선박", "무인 선박"],
  ["인공지능", "AI"],
  ["사업화", "상용화"],
  ["해상공급망", "해상 공급망", "해운 공급망"],
];
const el = (id) => document.getElementById(id);
const today = new Intl.DateTimeFormat("sv-SE", {timeZone: "Asia/Seoul"}).format(new Date());
const nowInSeoul = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
}).format(new Date());
const isClosed = (entry) => entry.deadline < today ||
  (entry.deadline === today && entry.deadline_time && entry.deadline_time <= nowInSeoul);
const briefingDate = new Intl.DateTimeFormat("ko-KR", {month: "long", day: "numeric", timeZone: "UTC"});
const formatBriefDate = (value) => briefingDate.format(new Date(value + "T00:00:00Z"));
const normalize = (value) => value.normalize("NFKC").toLowerCase().replace(/\s+/g, "");
const supportFields = ["stages", "types", "methods", "regions"];
const daysFromToday = (value) => (Date.parse(value) - Date.parse(today)) / 86400000;
const sourceKeys = (entry) => entry.source !== "gep" && entry.gep_notices?.length ?
  [entry.source, "gep"] : [entry.source];
const noticeDeadlines = (entry) => [entry, ...(entry.gep_notices ?? [])].filter((notice) => notice.deadline);
const deadlineLabels = {"7": "7일 이내", "30": "30일 이내", later: "30일 이후", past: "마감"};
const deadlineField = (label) => ({
  label, labels: deadlineLabels,
  keys: (entry) => noticeDeadlines(entry).flatMap((notice) => {
    if (isClosed(notice)) return ["past"];
    const days = daysFromToday(notice.deadline);
    if (days <= 7) return ["7", "30"];
    return days <= 30 ? ["30"] : ["later"];
  }),
});
const textField = (label, name) => ({label, keys: (entry) => entry[name] ? [entry[name]] : []});
const tagField = (label, name) => ({label, keys: (entry) => entry[name] ?? []});
const eventFields = [
  {label: "개최 월", keys: (entry) => entry.event_start ? [entry.event_start.slice(0, 7)] : []},
  textField("개최 지역", "event_region"),
  tagField("행사 유형", "event_types"),
  tagField("참가 방식", "participation"),
  deadlineField("신청 마감"),
];
const categoryCounts = {};
const areaButtons = {};
const blank = () => ({ records: [], sources: {} });
let data = blank();
let selected = "home";
let localFacets = [];
let limit = 20;
let ready = false;

function addText(parent, tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  parent.append(node);
  return node;
}

function fillCategories() {
  const nav = el("categories");
  function addArea(parent, key, label) {
    const button = addText(parent, "button", label);
    areaButtons[key] = button;
    if (key !== "home") categoryCounts[key] = addText(button, "span", "", "category-count");
    button.type = "button";
    button.setAttribute("aria-pressed", String(key === selected));
    button.addEventListener("click", () => selectArea(key));
  }
  const overview = addText(nav, "div", "", "area-group");
  addArea(overview, "home", "홈");
  addArea(overview, "all", categories.all);
  for (const [label, ...keys] of areaGroups) {
    const group = addText(nav, "div", "", "area-group");
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", label);
    addText(group, "span", label, "area-group-label").setAttribute("aria-hidden", "true");
    keys.forEach((key) => addArea(group, key, categories[key]));
  }
}

function searchTerms(query) {
  const normalized = normalize(query);
  const known = synonyms.find((group) => group.some((word) => normalize(word) === normalized));
  return (known ? [normalized] : query.split(/\s+/).filter(Boolean).map(normalize)).map((term) => {
    const alternatives = synonyms.find((group) => group.some((word) => normalize(word) === term));
    return alternatives ? alternatives.map(normalize) : [term];
  });
}

function supportLabels(entry, field) {
  return (entry.support?.[field] ?? []).map((key) => data.support_facets?.[field]?.[key]).filter(Boolean);
}

function applicationStatus(entry) {
  if (/취소|잠정\s*중단/.test(entry.title)) return ["취소·중단"];
  if (/\[\s*(?:접수\s*마감|마감)\s*\]/.test(entry.title) || isClosed(entry)) return ["마감"];
  if (entry.planning_stage === "preview" || entry.opens > today) return ["접수 예정"];
  return entry.opens && entry.deadline ? ["접수 중"] : [];
}

function sectionFields(area) {
  if (area === "rnd") return [
    {...textField("참여 유형", "planning_stage"), labels: planningStages},
    {label: "접수 상태", keys: applicationStatus},
    deadlineField("제안·신청 마감"),
    {label: "공고 기관", keys: (entry) => {
      const agency = entry.publisher || {
        kimst_rnd: "KIMST", kimst_notice: "KIMST", bistep_planning: "BISTEP",
        nia_planning: "NIA", nipa_demand: "NIPA", keit_planning: "KEIT",
      }[entry.source];
      return agency ? [agency] : [];
    }},
  ];
  if (area === "support") return [["types", "사업 유형"], ["stages", "기업 단계"],
    ["regions", "사업 지역"], ["methods", "제공 형태"]].map(([key, label]) => ({
    label, labels: data.support_facets?.[key], keys: (entry) => entry.support?.[key] ?? [],
  }));
  if (area === "patent") return [
    textField("자료 유형", "technology_type"), tagField("기술 분야", "technology_fields"),
    textField("출원 국가", "filing_country"), textField("출원인", "applicant"),
  ];
  if (area === "industry") return [
    tagField("산업 분야", "industry_sectors"), tagField("주제", "industry_topics"),
    textField("대상 국가·지역", "place"),
  ];
  return ["domestic", "international"].includes(area) ? eventFields : [];
}

function selectArea(area) {
  if (area === selected) return;
  selected = area;
  el("sort").value = "latest";
  for (const [key, button] of Object.entries(areaButtons)) button.setAttribute("aria-pressed", String(area === key));
  fillSectionFilters();
  reset();
}

function fillSectionFilters() {
  const controls = el("section-filter-controls");
  controls.replaceChildren();
  localFacets = [];
  const scope = data.records.filter((entry) => entry.category === selected);
  for (const field of sectionFields(selected)) {
    const keys = (entry) => {
      const values = field.keys(entry);
      return values.length ? values : ["unknown"];
    };
    const present = countKeys(scope, keys);
    // Keep an unpopulated dimension off the screen until at least one value is known.
    if (!field.labels && ![...present.keys()].some((key) => key !== "unknown")) continue;
    if (!scope.length) continue;
    const label = addText(controls, "label", field.label);
    const control = addText(label, "select", "");
    addText(control, "option", "전체").value = "";
    const choices = field.labels ? Object.keys(field.labels) : [...present.keys()].sort((a, b) => a.localeCompare(b, "ko"));
    for (const key of choices.filter((key) => key !== "unknown")) {
      addText(control, "option", field.labels?.[key] ?? key).value = key;
    }
    if (present.has("unknown")) {
      addText(control, "option", selected === "support" ? "미분류" : "미확인").value = "unknown";
    }
    control.addEventListener("change", reset);
    localFacets.push({control, keys});
  }
  el("section-filters").hidden = !localFacets.length;
  el("section-filter-title").textContent = selected === "support" ? "기업지원사업 찾기" : `${categories[selected] ?? ""} 필터`;
}

function matchesFacets(entry, facets, except) {
  return facets.every(({control, keys}) => control === except || !control.value || keys(entry).includes(control.value));
}

function countKeys(entries, keysFor) {
  const counts = new Map();
  for (const entry of entries) {
    for (const key of new Set(keysFor(entry))) {
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return counts;
}

const countLabel = (count) => `${count.toLocaleString("ko-KR")}건`;

function updateFacetCounts(control, keys, entries) {
  const counts = countKeys(entries, keys);
  for (const option of control.options) {
    const label = option.dataset.label ??= option.textContent;
    const count = option.value ? counts.get(option.value) ?? 0 : entries.length;
    option.textContent = `${label} (${countLabel(count)})`;
  }
}

function appendSupportTags(parent, entry, brief = false) {
  if (entry.category !== "support") return;
  const fields = brief ? ["stages", "types"] : supportFields;
  const labels = fields.flatMap((field) => supportLabels(entry, field));
  if (!labels.length) return;
  const tags = addText(parent, "p", "", "meta support-tags");
  (brief ? labels.slice(0, 3) : labels).forEach((label) => addText(tags, "span", label));
}

function matches(record, terms) {
  const gepTitles = (record.gep_notices ?? []).map((notice) => notice.title);
  const subject = [record.title, record.place, record.topic, record.eligibility, record.publisher,
    planningStages[record.planning_stage], data.sources[record.source],
    record.event_region, record.technology_type, record.filing_country, record.applicant,
    ...(record.industry_sectors ?? []), ...(record.industry_topics ?? []),
    ...(record.event_types ?? []), ...(record.participation ?? []), ...(record.technology_fields ?? []),
    ...supportFields.flatMap((field) => supportLabels(record, field)),
    ...gepTitles, gepTitles.length ? data.sources.gep : "", categories[record.category]]
    .filter(Boolean).join(" ");
  const compact = normalize(subject);
  return terms.every((group) => group.some((word) => {
    if (word !== "ai") return compact.includes(word);
    return /(^|[^a-z0-9])ai(?=$|[^a-z0-9])/i.test(subject.normalize("NFKC"));
  }));
}

function selectBriefing(entries) {
  const relevance = (entry) => {
    if (briefingNotes[entry.id]) return 3;
    const subject = [entry.title, entry.topic].filter(Boolean).join(" ");
    if (/해양|해운|해상|항만|선박|조선|수산|양식|maritime|ocean/i.test(subject)) return 2;
    return /(?<![a-z0-9])AI(?![a-z0-9])|인공지능|학습용\s*데이터|GPU|제조\s*AX/i.test(subject) ? 1 : 0;
  };
  const candidates = entries.filter((entry) =>
    relevance(entry) && !/\[\s*(?:접수\s*마감|마감|취소)\s*\]|잠정\s*중단|공고\s*취소/.test(entry.title)
  );
  const deadlineOrder = (a, b) => (a.deadline + (a.deadline_time || "23:59"))
    .localeCompare(b.deadline + (b.deadline_time || "23:59"));
  const deadlines = candidates
    .filter((entry) => entry.planning_stage !== "preview" && (!entry.opens || entry.opens <= today))
    .map((entry) => ({
      entry,
      deadline: noticeDeadlines(entry)
        .filter((item) => !isClosed(item) && daysFromToday(item.deadline) <= 7)
        .sort(deadlineOrder)[0],
    }))
    .filter(({deadline}) => deadline)
    .sort((a, b) => relevance(b.entry) - relevance(a.entry) || deadlineOrder(a.deadline, b.deadline))
    .slice(0, 3).sort((a, b) => deadlineOrder(a.deadline, b.deadline));
  const featured = new Set(deadlines.map(({entry}) => entry.id));
  const latest = candidates.filter((entry) => !featured.has(entry.id) &&
    entry.published && daysFromToday(entry.published) >= -6 && daysFromToday(entry.published) <= 0 &&
    (!entry.deadline || !isClosed(entry)))
    .sort((a, b) => b.published.localeCompare(a.published) || relevance(b) - relevance(a))
    .slice(0, 3);
  return {deadlines, latest};
}

function appendBrief(parent, entry, deadline) {
  const source = deadline && deadline !== entry ? data.sources.gep : entry.publisher || data.sources[entry.source];
  const url = new URL(deadline?.url || entry.url);
  if (url.protocol !== "https:") return;
  const note = briefingNotes[entry.id];
  const story = document.createElement("li");
  const article = document.createElement("article");
  story.append(article);
  const meta = addText(article, "p", "", "meta");
  addText(meta, "span", source);
  if (deadline) {
    const date = deadline.deadline === today ? "오늘" : formatBriefDate(deadline.deadline);
    const time = deadline.deadline_time ? ` ${deadline.deadline_time} KST` : "";
    addText(meta, "span", `${date}${time} 마감`, "briefing-when");
  } else {
    addText(meta, "span", formatBriefDate(entry.published));
    if (entry.deadline) addText(meta, "span", `${formatBriefDate(entry.deadline)} 마감`);
  }
  addText(addText(article, "h4", ""), "a", note?.title || entry.title).href = url.href;
  appendSupportTags(article, entry, true);
  const lead = note?.lead || entry.topic || entry.eligibility || planningActions[entry.planning_stage];
  if (lead) addText(article, "p", lead, "briefing-lead");
  const linkLabel = entry.category === "industry" ? "출처에서 기사 읽기" :
    deadline && !deadline.deadline_time ? "참여 조건·마감 시각 확인" : "공식 원문 보기";
  addText(article, "a", linkLabel, "briefing-link").href = url.href;
  parent.append(story);
}

function renderBriefing(entries) {
  const {deadlines, latest} = selectBriefing(entries);
  const deadlineList = document.createDocumentFragment();
  deadlines.forEach(({entry, deadline}) => appendBrief(deadlineList, entry, deadline));
  el("briefing-deadline-list").replaceChildren(deadlineList);
  const latestList = document.createDocumentFragment();
  latest.forEach((entry) => appendBrief(latestList, entry));
  el("briefing-latest-list").replaceChildren(latestList);
  el("briefing-deadlines").hidden = deadlines.length === 0;
  el("briefing-latest").hidden = latest.length === 0;
  el("briefing").hidden = deadlines.length + latest.length === 0;
  return new Set([...deadlines.map(({entry}) => entry.id), ...latest.map((entry) => entry.id)]);
}

function appendRecord(parent, entry, featured = false) {
  const item = document.createElement("li");
  const top = addText(item, "p", "", "meta");
  addText(top, "span", categories[entry.category], "category");
  addText(top, "span", entry.publisher || data.sources[entry.source]);
  if (entry.planning_stage) addText(top, "span", planningStages[entry.planning_stage]);
  if (entry.technology_type) addText(top, "span", entry.technology_type);
  const url = new URL(entry.url);
  if (url.protocol !== "https:") return;
  const link = addText(item, "a", entry.title);
  link.href = url.href;
  const meta = addText(item, "p", "", "meta");
  if (entry.published) addText(meta, "span", `게시 ${entry.published}`);
  if (entry.event_start) addText(meta, "span", `개최 ${entry.event_start}${entry.event_end && entry.event_end !== entry.event_start ? " ~ " + entry.event_end : ""}`);
  if (entry.exhibition_start && entry.exhibition_end) addText(meta, "span", `전시장 운영 ${entry.exhibition_start} ~ ${entry.exhibition_end}`);
  if (entry.deadline) {
    const time = entry.deadline_time ? " " + entry.deadline_time + " KST" : "";
    const label = isClosed(entry) ? "마감" : entry.planning_stage === "demand" ? "제안 마감" :
      entry.planning_stage === "opinion" ? "의견 마감" : "신청 마감";
    addText(meta, "span", `${label} ${entry.deadline}${time}`);
  }
  if (entry.event_region) addText(meta, "span", entry.event_region);
  if (entry.place && entry.place !== entry.event_region) addText(meta, "span", entry.place);
  for (const [field, label] of [["visit_url", "참관 안내"], ["exhibit_url", "전시 참가 안내"]]) {
    if (entry[field]?.startsWith("https://nor-shipping.com/")) {
      addText(meta, "a", label).href = entry[field];
    }
  }
  for (const notice of entry.gep_notices ?? []) {
    if (!notice.url.startsWith("https://www.gep.or.kr/gept/")) continue;
    const reference = addText(item, "p", "", "meta");
    const label = entry.gep_notices.length === 1 ? "KOTRA 전시 안내" : notice.title;
    addText(reference, "a", label).href = notice.url;
    if (notice.deadline) {
      const time = notice.deadline_time ? " " + notice.deadline_time + " KST" : "";
      addText(reference, "span", `KOTRA 신청 마감 ${notice.deadline}${time}`);
    }
  }
  if (!meta.childElementCount) meta.remove();
  appendSupportTags(item, entry);
  if (entry.eligibility && !entry.eligibility_url) {
    const eligibility = addText(item, "p", "", "eligibility");
    addText(eligibility, "strong", entry.planning_stage ? "참여 대상 " : "신청 대상 ");
    addText(eligibility, "span", entry.eligibility);
  }
  if (entry.support_tracks?.length) {
    const tracks = addText(item, "div", "", "support-tracks");
    if (entry.support_track_note) addText(tracks, "p", entry.support_track_note, "meta");
    entry.support_tracks.forEach((track) => {
      const row = addText(tracks, "p", "");
      addText(row, "strong", track.name + " ");
      addText(row, "span", track.description);
    });
  }
  if (featured) addText(item, "p", planningActions[entry.planning_stage], "eligibility");
  if (entry.eligibility && entry.eligibility_url?.startsWith("https://www.jcia.or.kr/")) {
    const eligibility = addText(item, "p", "", "eligibility");
    addText(eligibility, "strong", "신청 대상 ");
    addText(eligibility, "span", entry.eligibility);
    addText(eligibility, "a", "공식 공고문에서 조건 확인").href = entry.eligibility_url;
  }
  parent.append(item);
}

function render() {
  if (!ready) return;
  const terms = searchTerms(el("query").value.trim());
  const source = el("source");
  const hasLocalFilters = localFacets.some(({control}) => control.value);
  const defaultView = !terms.length && !source.value && !hasLocalFilters && el("sort").value === "latest";
  const home = selected === "home";
  const searched = data.records.filter((entry) => matches(entry, terms));
  const shared = source.value ? searched.filter((entry) => sourceKeys(entry).includes(source.value)) : searched;
  const totals = countKeys(shared, (entry) => [entry.category]);
  for (const [key, count] of Object.entries(categoryCounts)) {
    count.textContent = " " + countLabel(key === "all" ? shared.length : totals.get(key) ?? 0);
  }
  updateFacetCounts(source, sourceKeys, searched);
  const scope = selected === "all" ? shared : shared.filter((entry) => entry.category === selected);
  for (const {control, keys} of localFacets) {
    updateFacetCounts(control, keys, scope.filter((entry) => matchesFacets(entry, localFacets, control)));
  }
  const help = el("section-filter-help");
  help.hidden = selected !== "support" && !hasLocalFilters;
  help.textContent = [
    selected === "support" ? "한 공고에 여러 사업 유형이나 제공 형태가 포함될 수 있습니다." : "",
    hasLocalFilters ? "상단 건수는 검색어와 정보원 기준입니다." : "",
  ].filter(Boolean).join(" ");
  const results = scope.filter((entry) => matchesFacets(entry, localFacets));
  const upcoming = (entry) => noticeDeadlines(entry)
    .filter((notice) => !isClosed(notice))
    .map((notice) => notice.deadline + (notice.deadline_time || "23:59"))
    .sort()[0] ?? "9999";
  results.sort((a, b) => {
    if (el("sort").value === "deadline") {
      const order = upcoming(a).localeCompare(upcoming(b));
      if (order) return order;
    }
    return (b.published || b.event_start || "").localeCompare(a.published || a.event_start || "") ||
      a.title.localeCompare(b.title, "ko");
  });
  const briefingIds = renderBriefing(home ? shared : []);
  el("results-title").textContent = home ? "홈" : selected === "all" ? "통합 결과" : categories[selected];
  el("results-heading").hidden = home && briefingIds.size > 0;
  el("sort-filter").hidden = home || ["industry", "patent"].includes(selected);
  el("summary").textContent = home ? "표시할 브리핑이 없습니다." :
    results.length ? `검색 결과 ${countLabel(results.length)}` : "조건에 맞는 정보가 없습니다.";
  const picks = selected === "rnd" && defaultView ?
    results.filter((entry) => planningActions[entry.planning_stage] &&
      entry.opens && entry.opens <= today && entry.deadline && !isClosed(entry))
      .sort((a, b) => upcoming(a).localeCompare(upcoming(b))).slice(0, 3) : [];
  const featured = document.createDocumentFragment();
  picks.forEach((entry) => appendRecord(featured, entry, true));
  el("rnd-picks").replaceChildren(featured);
  el("rnd-featured").hidden = !picks.length;
  const related = selected === "rnd" && !hasLocalFilters ? shared.filter((entry) => entry.category === "support" &&
    entry.support_tracks?.some((track) => track.types.includes("research")) && entry.url.startsWith("https://")) : [];
  el("rnd-related").hidden = !related.length;
  el("rnd-related-links").replaceChildren();
  for (const entry of related) {
    const item = addText(el("rnd-related-links"), "li", "");
    addText(item, "a", entry.title).href = entry.url;
  }
  const remaining = results.filter((entry) => !picks.includes(entry));
  const list = document.createDocumentFragment();
  remaining.slice(0, limit).forEach((entry) => appendRecord(list, entry));
  el("results").replaceChildren(list);
  el("more").hidden = remaining.length <= limit;
}

function reset() {
  limit = 20;
  render();
}

fillCategories();
el("query").addEventListener("input", () => {
  const query = el("query").value.trim() || "해양수산 AI";
  for (const link of document.querySelectorAll(".naver-search a")) {
    const search = new URL(link.href);
    search.searchParams.set("query", query);
    link.href = search.href;
  }
  if (selected === "home" && el("query").value.trim()) selectArea("all");
  else reset();
});
el("source").addEventListener("change", reset);
el("sort").addEventListener("change", reset);
el("more").addEventListener("click", () => { limit += 20; render(); });

const dataUrl = new URL("./data.json", document.currentScript.src);
dataUrl.search = new URL(document.currentScript.src).search;
fetch(dataUrl, {cache: "no-cache"})
  .then((response) => {
    if (!response.ok) throw new Error("Data unavailable");
    return response.json();
  })
  .then((payload) => {
    data = payload;
    Object.entries(data.sources).forEach(([key, label]) => {
      addText(el("source"), "option", label).value = key;
    });
    const timestamp = new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short",
    }).format(new Date(data.updated_at));
    el("updated").textContent = data.sample ? "저장된 응답으로 만든 시험 데이터" : `마지막 갱신 ${timestamp}`;
    const dataDate = new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul", month: "long", day: "numeric",
    }).format(new Date(data.updated_at));
    el("briefing-date").textContent = `${dataDate} 수집 기준`;
    ready = true;
    fillSectionFilters();
    render();
  })
  .catch(() => {
    el("summary").textContent = "정보를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.";
  });
