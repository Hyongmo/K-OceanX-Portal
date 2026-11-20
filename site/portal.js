"use strict";

const categories = {
  all: "전체", rnd: "R&D·기획", patent: "특허·기술", industry: "산업동향",
  international: "국제 행사", domestic: "국내 행사", support: "기업지원·인증",
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
  const subject = [record.title, record.place, record.topic, record.eligibility, data.sources[record.source],
    categories[record.category]].filter(Boolean).join(" ");
  const compact = normalize(subject);
  return terms.every((group) => group.some((word) => {
    if (word !== "ai") return compact.includes(word);
    return /(^|[^a-z0-9])ai(?=$|[^a-z0-9])/i.test(subject.normalize("NFKC"));
  }));
}

function appendRecord(parent, entry) {
  const item = document.createElement("li");
  const top = addText(item, "p", "", "meta");
  addText(top, "span", categories[entry.category], "category");
  addText(top, "span", data.sources[entry.source]);
  const url = new URL(entry.url);
  if (url.protocol !== "https:") return;
  const link = addText(item, "a", entry.title);
  link.href = url.href;
  const meta = addText(item, "p", "", "meta");
  if (entry.published) addText(meta, "span", `게시 ${entry.published}`);
  if (entry.event_start) addText(meta, "span", `개최 ${entry.event_start}${entry.event_end && entry.event_end !== entry.event_start ? " ~ " + entry.event_end : ""}`);
  if (entry.deadline) {
    const time = entry.deadline_time ? " " + entry.deadline_time + " KST" : "";
    addText(meta, "span", `${isClosed(entry) ? "마감" : "신청 마감"} ${entry.deadline}${time}`);
  }
  if (entry.place) addText(meta, "span", entry.place);
  if (!meta.childElementCount) meta.remove();
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
  const results = data.records.filter((entry) =>
    (selected === "all" || entry.category === selected) &&
    (!source || entry.source === source) && matches(entry, terms));
  results.sort((a, b) => {
    if (el("sort").value === "deadline") {
      const upcoming = (entry) => entry.deadline && !isClosed(entry) ? entry.deadline + (entry.deadline_time || "23:59") : "9999";
      const order = upcoming(a).localeCompare(upcoming(b));
      if (order) return order;
    }
    return (b.published || b.event_start || "").localeCompare(a.published || a.event_start || "") ||
      a.title.localeCompare(b.title, "ko");
  });
  el("results-title").textContent = selected === "all" ? "통합 결과" : categories[selected];
  el("summary").textContent = results.length ? `검색 결과 ${results.length.toLocaleString("ko-KR")}건` :
    selected === "patent" ? "특허 정보는 연계 준비 중입니다." : "조건에 맞는 정보가 없습니다.";
  const list = document.createDocumentFragment();
  results.slice(0, limit).forEach((entry) => appendRecord(list, entry));
  el("results").replaceChildren(list);
  el("more").hidden = results.length <= limit;
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
  reset();
});
el("source").addEventListener("change", reset);
el("sort").addEventListener("change", reset);
el("more").addEventListener("click", () => { limit += 20; render(); });

fetch("./data.json")
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
    ready = true;
    render();
  })
  .catch(() => {
    el("summary").textContent = "정보를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.";
  });
