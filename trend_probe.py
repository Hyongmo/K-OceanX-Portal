"""Trial run for industry and technology trends: trade press RSS, Naver News and DDGS searches.

Nothing here is published. The run writes a report to the GitHub Actions run page
($GITHUB_STEP_SUMMARY) so the sources can be judged before any of them joins the portal:
whether each feed answers, how many days its items cover, and how many items fit the trend
concepts. Naver results are reported as counts only (Naver search API terms; tasks.md 13).
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from xml.etree import ElementTree

from target_rules import SEA

KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; KMI-portal-trend-trial)"

# Trade press feeds. "sea" says whether every item is about the sea already (True) or the
# feed also covers air and land logistics, so an item needs a sea word to count (False).
FEEDS = (
    ("한국해운신문", "국내", True, ("https://www.maritimepress.co.kr/rss/allArticle.xml",)),
    ("해양한국", "국내", True, ("https://www.monthlymaritimekorea.com/rss/allArticle.xml",)),
    ("쉬핑뉴스넷", "국내", True, ("https://www.shippingnewsnet.com/rss/allArticle.xml",)),
    ("현대해양", "국내", True, ("https://www.hdhy.co.kr/rss/allArticle.xml",)),
    ("해사신문", "국내", True, ("https://www.haesanews.com/rss/allArticle.xml",
                              "http://www.haesanews.com/rss/allArticle.xml")),
    ("항만신문", "국내", True, ("https://www.portnews.co.kr/rss/allArticle.xml",)),
    ("한국수산경제", "국내", True, ("https://www.fisheco.com/rss/allArticle.xml",
                                "http://www.fisheco.com/rss/allArticle.xml")),
    ("한국수산신문", "국내", True, ("https://www.susantimes.co.kr/rss/allArticle.xml",)),
    ("어업in수산", "국내", True, ("https://www.aqua.kr/rss/allArticle.xml",)),
    ("카고뉴스", "국내", False, ("https://www.cargonews.co.kr/rss/allArticle.xml",)),
    ("물류신문", "국내", False, ("https://www.klnews.co.kr/rss/allArticle.xml",)),
    ("Splash247", "해외", True, ("https://splash247.com/feed/",)),
    ("gCaptain", "해외", True, ("https://gcaptain.com/feed/",)),
    ("Hellenic Shipping News", "해외", True, ("https://www.hellenicshippingnews.com/feed/",)),
    ("Maritime Executive", "해외", True, ("https://maritime-executive.com/articles.rss",)),
    ("Seatrade Maritime", "해외", True, ("https://www.seatrade-maritime.com/rss.xml",)),
    ("Offshore Energy", "해외", False, ("https://www.offshore-energy.biz/feed/",)),
    ("Ship Technology", "해외", True, ("https://www.ship-technology.com/feed/",)),
)

# Trend concepts: Korean and English title words, and the searches that look for them.
CONCEPTS = (
    ("산업", "해운 시황", r"운임|시황|SCFI|KCCI|용선료|BDI|해운\s*경기|선복|할증료",
     r"\brates?\b|freight market|charter market|tanker market|spot market|SCFI|Drewry|Baltic|\bBDI\b|surcharge",
     ("해운 운임", "해운 시황")),
    ("산업", "조선 수주", r"수주|발주|신조선|수주\s*잔량|건조\s*계약",
     r"newbuild|orderbook|order for|ordered|shipyard|shipbuild", ("조선 수주", "선박 발주")),
    ("산업", "항만 물동량", r"물동량|처리량|TEU|환적",
     r"throughput|TEU|container volume|port volume", ("항만 물동량", "컨테이너 물동량")),
    ("산업", "수산물 시장", r"수산물\s*(?:수출|수입|가격|소비|시장|유통)|어획량|위판|수산\s*식품",
     r"seafood|fish price|fisheries export|salmon price", ("수산물 수출", "수산물 가격")),
    ("산업", "해양 에너지·플랜트", r"해상\s*풍력|해양\s*플랜트|부유식|FPSO|해양\s*에너지",
     r"offshore wind|floating wind|FPSO|offshore platform", ("해상풍력", "해양플랜트")),
    ("산업", "해양수산 정책·규제", r"(?:해양수산부|해수부).*(?:정책|전략|계획|규제|법|제도|추진|발표|대책)|IMO|탄소\s*규제|배출권|ETS|법안|규제",
     r"\bIMO\b|MEPC|net-zero framework|EU ETS|FuelEU|regulation", ("해양수산부 정책", "IMO 규제")),
    ("기술", "자율운항", r"자율\s*운항|(?-i:\bMASS\b)|무인\s*선박|원격\s*운항",
     r"autonomous|(?-i:\bMASS\b)|remotely operated vessel|uncrewed", ("자율운항선박", "자율운항")),
    ("기술", "친환경 선박·연료", r"암모니아|메탄올|LNG\s*추진|이중\s*연료|친환경\s*선박|탈탄소|무탄소|수소\s*선박|전기\s*추진",
     r"ammonia|methanol|LNG-fuel|dual-fuel|decarboni[sz]|zero-emission|biofuel|green fuel",
     ("친환경 선박", "암모니아 추진선")),
    ("기술", "스마트항만", r"스마트\s*항만|항만\s*자동화|자동화\s*(?:터미널|부두)|디지털\s*트윈",
     r"port automation|automated terminal|smart port|digital twin", ("스마트항만", "항만 자동화")),
    ("기술", "스마트양식", r"스마트\s*양식|육상\s*양식|양식\s*기술|순환\s*여과|스마트\s*어업",
     r"aquaculture|fish farm|\bRAS\b", ("스마트양식", "육상양식")),
    ("기술", "해양 AI·데이터", r"\bAI\b|인공지능|데이터|디지털|\bAX\b",
     r"\bAI\b|artificial intelligence|machine learning|digitali[sz]", ("해양 AI", "해양수산 데이터")),
    ("기술", "수중·해양 로봇", r"수중\s*(?:로봇|드론|건설|기술|글라이더)|해양\s*로봇|무인\s*잠수정|ROV|AUV|USV|무인\s*수상정",
     r"underwater (?:drone|robot|vehicle)|subsea robot|\bROV\b|\bAUV\b|\bUSV\b|uncrewed surface|unmanned surface", ("수중 로봇", "해양 로봇")),
    ("기술", "극지·쇄빙", r"북극|극지|쇄빙|남극", r"Arctic|icebreak|polar|Northern Sea Route", ("북극항로", "쇄빙선")),
    ("기술", "해양 바이오", r"해양\s*바이오|블루\s*바이오", r"marine bio|blue bio", ("해양바이오",)),
)
ENGLISH_SEARCHES = (
    ("조선 수주", "shipbuilding orders"), ("해운 시황", "container freight rates"),
    ("자율운항", "autonomous ship"), ("친환경 선박·연료", "ammonia methanol ship fuel"),
    ("스마트항만", "automated container terminal"), ("스마트양식", "aquaculture technology"),
)
REPORT_SEARCHES = ("자율운항선박 기술 동향 보고서", "친환경 선박 기술 동향 보고서", "스마트항만 기술 동향",
                   "스마트양식 기술 동향", "해양 디지털 기술 동향 브리프")
SEA_EN = re.compile(r"\b(?:ships?|shipping|shipbuild\w*|shipyards?|vessels?|ports?|maritime|seafood|fish\w*|"
                    r"aquaculture|offshore|marine|ocean|tankers?|containers?|bulkers?|naval|seafarers?|freight)\b", re.I)
# Items that are not trends: personnel news, obituaries, photo notes, notices.
NOISE = re.compile(r"인사\]|\[인사|전보\s*인사|정기\s*인사|임원\s*인사|인사\s*\(|과장에\s|국장에\s|부고|별세|모친상|부친상|빙부상|빙모상|결혼|화촉|\[포토\]|\[사진\]|동정\]|"
                   r"\[알림\]|게시판|오늘의 운세|obituary|in memoriam|podcast|webinar", re.I)
WINDOW_DAYS = 14


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()


def text(node, *names):
    for name in names:
        found = node.find(name)
        if found is not None and (found.text or found.get("href")):
            return (found.text or found.get("href") or "").strip()
    return ""


def when(value):
    value = (value or "").strip()
    for parse in (parsedate_to_datetime, lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
                  lambda v: datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S")):
        try:
            moment = parse(value)
            return moment if moment.tzinfo else moment.replace(tzinfo=KST)
        except (TypeError, ValueError, IndexError):
            continue
    return None


def read_feed(urls):
    """Items of the first address that answers: (title, link, date); and the address or error."""
    error = ""
    for url in urls:
        try:
            root = ElementTree.fromstring(fetch(url))
        except Exception as problem:  # noqa: BLE001 - every failure is reported per feed
            error = f"{type(problem).__name__}: {str(problem)[:80]}"
            continue
        atom = "{http://www.w3.org/2005/Atom}"
        nodes = root.findall(".//item") or root.findall(f".//{atom}entry")
        items = []
        for node in nodes:
            title = text(node, "title", f"{atom}title")
            link = text(node, "link", f"{atom}link")
            posted = when(text(node, "pubDate", f"{atom}updated", f"{atom}published",
                               "{http://purl.org/dc/elements/1.1/}date"))
            if title:
                items.append((re.sub(r"\s+", " ", title), link, posted))
        return items, url, ""
    return [], "", error


def concepts_of(title, english):
    return [name for _, name, ko, en, _ in CONCEPTS if re.search(en if english else ko, title, re.I)]


def is_sea(title, english):
    return bool((SEA_EN if english else SEA).search(title))


def judge(title, english, sea_feed):
    """(kept, concepts, reason) for one trend item."""
    if NOISE.search(title):
        return False, [], "인사·부고·알림"
    if not sea_feed and not is_sea(title, english):
        return False, [], "해양 무관"
    found = concepts_of(title, english)
    return bool(found), found, "" if found else "개념 없음"


def same_story(a, b):
    core = lambda t: re.sub(r"\[[^\]]*\]|[^0-9A-Za-z가-힣]", "", t).lower()
    return SequenceMatcher(None, core(a), core(b)).ratio() >= 0.6


def naver_counts():
    client_id, secret = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not secret:
        return None
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": secret}
    since = datetime.now(KST) - timedelta(days=WINDOW_DAYS)
    rows = []
    for group, name, *_ , queries in CONCEPTS:
        received = recent = kept = 0
        for query in queries:
            url = "https://openapi.naver.com/v1/search/news.json?" + urlencode(
                {"query": query, "display": 50, "sort": "date"})
            try:
                items = json.loads(fetch(url, headers))["items"]
            except Exception:  # noqa: BLE001
                continue
            for item in items:
                received += 1
                title = re.sub(r"<[^>]+>|&quot;|&amp;|&lt;|&gt;", "", item.get("title", ""))
                posted = when(item.get("pubDate"))
                if posted and posted >= since:
                    recent += 1
                    ok, found, _ = judge(title, False, False)
                    kept += ok and name in found
        rows.append((group, name, received, recent, kept))
    return rows


def ddgs_runs():
    try:
        from ddgs import DDGS
    except ImportError:
        return None, None, None
    search = DDGS(timeout=15)
    news, english, reports = [], [], []

    def ask(kind, query, **options):
        time.sleep(2)
        try:
            return getattr(search, kind)(query, **options), ""
        except Exception as problem:  # noqa: BLE001
            return [], f"{type(problem).__name__}: {str(problem)[:60]}"

    for group, name, *_, queries in CONCEPTS:
        results, error = ask("news", queries[0], region="kr-kr", timelimit="w", max_results=20)
        rows = [(r.get("title", ""), r.get("source", ""), (r.get("date") or "")[:10]) for r in results]
        news.append((group, name, queries[0], error, [(row, judge(row[0], False, False)) for row in rows]))
    for name, query in ENGLISH_SEARCHES:
        results, error = ask("news", query, region="us-en", timelimit="w", max_results=15)
        rows = [(r.get("title", ""), r.get("source", ""), (r.get("date") or "")[:10]) for r in results]
        english.append((name, query, error, [(row, judge(row[0], True, False)) for row in rows]))
    for query in REPORT_SEARCHES:
        results, error = ask("text", query, region="kr-kr", max_results=10)
        reports.append((query, error, [(r.get("title", ""), r.get("href", "")) for r in results]))
    return news, english, reports


def main():
    now = datetime.now(KST)
    since = now - timedelta(days=WINDOW_DAYS)
    out = [f"# 산업·기술 동향 자료원 시험 ({now:%Y-%m-%d %H:%M} KST)",
           "", "게시하지 않는 시험입니다. 판단: 인사·부고·알림 제외 → (물류지·검색은) 제목에 해양 낱말 → 제목에 동향 개념 낱말.", ""]

    # 1. Trade press RSS
    out += ["## 1. 전문지 RSS", "",
            "| 매체 | 구분 | 결과 | 기사 수 | 기간 | 최근 14일 | 개념 맞음 | 빠짐(인사 등/해양 무관/개념 없음) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    kept_all, samples, dropped_samples = [], {}, {}
    for name, place, sea_feed, urls in FEEDS:
        items, used, error = read_feed(urls)
        english = place == "해외"
        if not items:
            out.append(f"| {name} | {place} | 실패 {error or '기사 없음'} | 0 | | | | |")
            continue
        dates = [d for _, _, d in items if d]
        span = f"{min(dates):%y.%m.%d}~{max(dates):%y.%m.%d}" if dates else "날짜 없음"
        recent = [i for i in items if i[2] is None or i[2] >= since]
        reasons = {"인사·부고·알림": 0, "해양 무관": 0, "개념 없음": 0}
        for title, link, posted in recent:
            ok, found, reason = judge(title, english, sea_feed)
            if ok:
                kept_all.append((title, name, posted, found))
                for concept in found:
                    samples.setdefault(concept, []).append((title, name))
            else:
                reasons[reason] += 1
                dropped_samples.setdefault(name, []).append((reason, title))
        kept = len(recent) - sum(reasons.values())
        note = "" if used == urls[0] else " (http)"
        out.append(f"| {name} | {place} | 성공{note} | {len(items)} | {span} | {len(recent)} | {kept} | "
                   f"{reasons['인사·부고·알림']}/{reasons['해양 무관']}/{reasons['개념 없음']} |")

    clusters = []
    for title, *_ in kept_all:
        for cluster in clusters:
            if same_story(title, cluster[0]):
                cluster.append(title)
                break
        else:
            clusters.append([title])
    out += ["", f"개념에 맞은 기사 {len(kept_all)}건, 같은 소식을 묶으면 {len(clusters)}건.", "",
            "### 개념별 기사 (RSS, 개념마다 최대 6건)", ""]
    for group, name, *_ in CONCEPTS:
        rows = samples.get(name, [])
        out.append(f"**[{group}] {name}: {len(rows)}건**")
        out += [f"- {title} ({source})" for title, source in rows[:6]] or ["- 없음"]
        out.append("")
    out += ["### 빠진 기사 예 (매체마다 최대 5건, 놓친 것이 있는지 보기 위함)", ""]
    for name, rows in dropped_samples.items():
        out.append(f"**{name}**")
        out += [f"- ({reason}) {title}" for reason, title in rows[:5]]
        out.append("")

    # 2. Naver News: counts only
    out += ["## 2. 네이버 뉴스 (건수만 기록)", ""]
    naver = naver_counts()
    if naver is None:
        out.append("네이버 열쇠가 없어 건너뜀.")
    else:
        out += ["| 구분 | 개념 | 받은 기사 | 최근 14일 | 판단 통과 |", "| --- | --- | --- | --- | --- |"]
        out += [f"| {g} | {n} | {r} | {c} | {k} |" for g, n, r, c, k in naver]
    out.append("")

    # 3. DDGS
    news, english, reports = ddgs_runs()
    out += ["## 3. DDGS 뉴스 검색 (최근 1주, 한국어)", ""]
    if news is None:
        out.append("DDGS가 설치되지 않음.")
    else:
        for group, name, query, error, rows in news:
            passed = [row for row, (ok, found, _) in rows if ok and name in found]
            out.append(f"**[{group}] {name}** — 검색어 '{query}': 받은 {len(rows)}건, 판단 통과 {len(passed)}건"
                       + (f" (오류 {error})" if error else ""))
            out += [f"- 통과: {t} ({s}, {d})" for t, s, d in passed[:3]]
            failed = [row for row, (ok, found, _) in rows if not (ok and name in found)]
            out += [f"- 탈락: {t} ({s})" for t, s, _ in failed[:2]]
            out.append("")
        out += ["## 4. DDGS 뉴스 검색 (최근 1주, 영어)", ""]
        for name, query, error, rows in english:
            passed = [row for row, (ok, found, _) in rows if ok]
            out.append(f"**{name}** — '{query}': 받은 {len(rows)}건, 판단 통과 {len(passed)}건"
                       + (f" (오류 {error})" if error else ""))
            out += [f"- 통과: {t} ({s}, {d})" for t, s, d in passed[:3]]
            out.append("")
        out += ["## 5. DDGS 웹문서 검색 (기술동향 보고서 찾기, 날짜 없음)", ""]
        for query, error, rows in reports:
            out.append(f"**'{query}'**: {len(rows)}건" + (f" (오류 {error})" if error else ""))
            out += [f"- {t} — {h}" for t, h in rows[:5]]
            out.append("")

    report = "\n".join(out) + "\n"
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    else:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
