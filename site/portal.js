"use strict";

const categories = {
  all: "전체", rnd: "R&D·기획", patent: "특허·기술", industry: "산업동향",
  international: "국제 행사", domestic: "국내 행사", support: "기업지원·인증",
};
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
const blank = () => ({ records: [], sources: {} });
let data = blank();
let selected = "all";
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
  Object.entries(categories).forEach(([key, label]) => {
    const button = addText(el("categories"), "button", label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(key === selected));
    button.addEventListener("click", () => {
      selected = key;
      el("categories").querySelectorAll("button").forEach((other) => {
        other.setAttribute("aria-pressed", String(other === button));
      });
      reset();
    });
  });
}

function searchTerms(query) {
  const normalized = normalize(query);
  const known = synonyms.find((group) => group.some((word) => normalize(word) === normalized));
  return (known ? [normalized] : query.split(/\s+/).filter(Boolean).map(normalize)).map((term) => {
    const alternatives = synonyms.find((group) => group.some((word) => normalize(word) === term));
    return alternatives ? alternatives.map(normalize) : [term];
  });
}

function matches(record, terms) {
  const gepTitles = (record.gep_notices ?? []).map((notice) => notice.title);
  const subject = [record.title, record.place, record.topic, record.eligibility, record.publisher,
    planningStages[record.planning_stage], data.sources[record.source],
    ...gepTitles, gepTitles.length ? data.sources.gep : "", categories[record.category]]
    .filter(Boolean).join(" ");
  const compact = normalize(subject);
  return terms.every((group) => group.some((word) => {
    if (word !== "ai") return compact.includes(word);
    return /(^|[^a-z0-9])ai(?=$|[^a-z0-9])/i.test(subject.normalize("NFKC"));
  }));
}

function selectBriefing(entries) {
  const daysFromToday = (value) => (Date.parse(value) - Date.parse(today)) / 86400000;
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
      deadline: [entry, ...(entry.gep_notices ?? [])]
        .filter((item) => item.deadline && !isClosed(item) && daysFromToday(item.deadline) <= 7)
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
  if (entry.place) addText(meta, "span", entry.place);
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
  if (entry.planning_stage && entry.eligibility) {
    const eligibility = addText(item, "p", "", "eligibility");
    addText(eligibility, "strong", "참여 대상 ");
    addText(eligibility, "span", entry.eligibility);
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
  const source = el("source").value;
  const stage = selected === "rnd" ? el("planning-stage").value : "";
  const defaultView = !terms.length && !source && !stage && el("sort").value === "latest";
  el("planning-stage-filter").hidden = selected !== "rnd";
  const results = data.records.filter((entry) =>
    (selected === "all" || entry.category === selected) &&
    (!source || entry.source === source || (source === "gep" && entry.gep_notices?.length)) &&
    (!stage || entry.planning_stage === stage) &&
    matches(entry, terms));
  const upcoming = (entry) => [entry, ...(entry.gep_notices ?? [])]
    .filter((notice) => notice.deadline && !isClosed(notice))
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
  el("results-title").textContent = selected === "all" ? "통합 결과" : categories[selected];
  el("summary").textContent = results.length ? `검색 결과 ${results.length.toLocaleString("ko-KR")}건` :
    selected === "patent" ? "특허 정보는 연계 준비 중입니다." : "조건에 맞는 정보가 없습니다.";
  const briefingIds = renderBriefing(selected === "all" && defaultView ? results : []);
  const picks = selected === "rnd" && defaultView ?
    results.filter((entry) => planningActions[entry.planning_stage] &&
      entry.opens && entry.opens <= today && entry.deadline && !isClosed(entry))
      .sort((a, b) => upcoming(a).localeCompare(upcoming(b))).slice(0, 3) : [];
  const featured = document.createDocumentFragment();
  picks.forEach((entry) => appendRecord(featured, entry, true));
  el("rnd-picks").replaceChildren(featured);
  el("rnd-featured").hidden = !picks.length;
  const remaining = results.filter((entry) => !picks.includes(entry) && !briefingIds.has(entry.id));
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
for (const [key, label] of Object.entries(planningStages)) {
  addText(el("planning-stage"), "option", label).value = key;
}
el("planning-stage").addEventListener("change", reset);
el("query").addEventListener("input", () => {
  const query = el("query").value.trim() || "해양수산 AI";
  for (const link of document.querySelectorAll(".naver-search a")) {
    const search = new URL(link.href);
    search.searchParams.set("query", query);
    link.href = search.href;
  }
  reset();
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
    render();
  })
  .catch(() => {
    el("summary").textContent = "정보를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.";
  });
