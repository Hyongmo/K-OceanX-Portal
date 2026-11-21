"""Collect source metadata and build the static K-OceanX portal."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import gzip
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unicodedata
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from support_taxonomy import METHODS, REGIONS, STAGES, TYPES, classify_support
from target_rules import judge, sector_profile

ROOT = Path(__file__).resolve().parent
DATE = r"\d{4}[-/]\d{2}[-/]\d{2}"
MARINE = re.compile(r"해양|해운|항만|선박|조선소|조선업|조선해양|조선 산업|수산|양식장|스마트\s*양식|해상|북극항로|항만물류|maritime|nor.shipping|ocean|aquaculture", re.I)
AI = re.compile(r"\bAI\b|인공지능|데이터|디지털|로봇|자율|스마트", re.I)
NEWS_TERMS = ("스마트항만", "스마트양식", "자율운항선박", "해양 인공지능", "해상 공급망")
WEB_TERMS = (
    "스마트양식 실증 공고",
    "해양수산 AI 데이터 R&D 공고",
    "해양 로봇 전시회 참가 모집",
    "KIMST 해양수산 AI 지원사업 공고",
    "KOTRA 선박 전시회 한국관 참가기업 모집",
    "스마트양식 지원 공고 site:bizinfo.go.kr",
)


JCIA = "https://www.jcia.or.kr"
JCIA_QUERY = "AI어장 현장실증 지원 모집 site:jcia.or.kr"
JCIA_POST = re.compile(r"/cf/Board/([0-9]{1,8})/detailView\.do")
JCIA_REVIEWED = ("9830", "9759")
NOR_SHIPPING = "https://nor-shipping.com/"
PLANNING_TOPIC = re.compile(r"해양|해운|항만|선박|조선|수산|양식|물류|제조\s*AX|피지컬\s*AI|인공지능|\bAI\b|학습용\s*데이터", re.I)
PLANNING_HTTP = (OSError, ValueError, subprocess.SubprocessError)


def iso(value):
    if not value:
        return ""
    value = str(value).strip().replace("/", "-")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def clean(value):
    return " ".join(BeautifulSoup(str(value or ""), "html.parser").stripped_strings)


def record(source, key, title, url, category, **fields):
    parsed = urlsplit(url)
    title = clean(title)
    if not key or not title or parsed.scheme != "https" or not parsed.hostname or parsed.username:
        raise ValueError("Invalid record identifier, title or URL")
    return {"id": f"{source}:{key}", "source": source, "title": title,
            "url": url, "category": category, **{k: v for k, v in fields.items() if v}}


def reader(samples):
    def get(name, url, headers=None):
        if samples:
            return (samples / f"{name}.body").read_bytes()
        if name in ("kimst_rnd", "kimst_notice", "jcia", "tp_planning", "biz_planning",
                    "bistep_planning", "nia_planning", "nipa_demand", "keit_planning"):
            # These publishers work with curl on the development host.
            raw = subprocess.check_output(["curl", "-fsSL", "--max-time", "20", "--max-filesize",
                                           "8000000", "--proto", "=https",
                                           "--user-agent", "K-OceanX pilot/0.1", url])
        else:
            request = Request(url, headers={"User-Agent": "K-OceanX pilot/0.1"})
            for key, value in (headers or {}).items():
                request.add_unredirected_header(key, value)
            with urlopen(request, timeout=20) as response:
                raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise ValueError("Response exceeds 8 MB")
        return gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
    return get


def page(get, source, url):
    return BeautifulSoup(get(source, url), "html.parser")


def params(url, **values):
    return f"{url}?{urlencode(values)}"


def require(rows):
    if not rows:
        raise ValueError("No recognizable source records")
    return rows


def planning_type(title):
    for kind, pattern in (
        ("preview", r"예비공고|공모예고"),
        ("opinion", r"사전\s*공시|인터넷\s*공시|의견\s*수렴|공청회"),
        ("demand", r"수요\s*조사|수요\s*제안|품목\s*수요"),
        ("joint", r"공동\s*(?:R&D\s*)?(?:과제\s*)?기획|과제\s*연구회|워킹\s*그룹"),
        ("planning", r"기획\s*[·ㆍ‧]?\s*(?:지원|유치|연구)|연구\s*기획\s*사업"),
    ):
        if re.search(pattern, title):
            return kind
    return ""


def planning_period(text):
    parts = re.split(r"[~～∼]", text, maxsplit=1)
    date_pattern = r"(?:(20\d{2})\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})(?!\d)"
    start = re.search(date_pattern, parts[0])
    end = re.search(date_pattern, parts[1]) if len(parts) == 2 else None
    if not start or not end or not start[1]:
        return {}
    year, month, day = map(int, start.groups())
    first = iso(f"{year}-{month:02}-{day:02}")
    last_month, last_day = int(end[2]), int(end[3])
    last_year = int(end[1]) if end[1] else year + (last_month < month)
    last = iso(f"{last_year}-{last_month:02}-{last_day:02}")
    if not first or not last or first > last:
        return {}
    clock = re.search(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b", parts[1])
    return {"opens": first, "deadline": last, "deadline_time": clock[0] if clock else ""}


def planning_fields(title, period):
    kind = planning_type(title)
    return {"planning_stage": kind, **(planning_period(period) if kind != "preview" else {})}


def regional_planning(get):
    url = "https://technopark.or.kr/www/linkBoard/list.do?mid=1012&type=P"
    candidates = []
    try:
        doc = page(get, "tp_planning", url)
        candidates = require(doc.select('td .view a[onclick^="updateRdcnt"]'))
    except PLANNING_HTTP as error:
        print(f"TP notice index unavailable: {type(error).__name__}", file=sys.stderr)
    rows = []
    # shortcut: approved direct parsers and reviewed government reposts while regional formats vary.
    for link in candidates:
        title = link.get_text(" ", strip=True)
        href = urlsplit(link["href"])
        identifier = parse_qs(href.query).get("nttId", [""])[0]
        if not planning_type(title) or href.scheme != "https" or href.netloc != "dgtp.or.kr" or not identifier.isdigit():
            continue
        official = params("https://dgtp.or.kr/bbs/BoardControllView.do",
                          bbsId="BBSMSTR_000000000003", nttId=identifier)
        try:
            detail = page(get, "tp_planning", official)
        except PLANNING_HTTP as error:
            print(f"Daegu TP candidate unavailable: {type(error).__name__}", file=sys.stderr)
            continue
        fields = {h.get_text(" ", strip=True): h.find_next_sibling("td").get_text(" ", strip=True)
                  for h in detail.select("th") if h.find_next_sibling("td")}
        if fields.get("제목") == title and PLANNING_TOPIC.search(title):
            rows.append(record("tp_planning", "dgtp-" + identifier, title, official, "rnd",
                               place="대구", publisher="대구테크노파크", published=iso(fields.get("작성일")),
                               **planning_fields(title, fields.get("접수기간", ""))))

    registry = dict.fromkeys(("000000000126006", "000000000123085", "000000000120103", "000000000120819"))
    try:
        listing = page(get, "biz_planning", "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do")
        for a in listing.select('a[href*="selectSIIA200Detail.do"][href*="pblancId="]'):
            if not planning_type(a.get_text(" ", strip=True)) or "테크노파크" not in a.find_parent("tr").get_text(" ", strip=True):
                continue
            key = re.search(r"[?&]pblancId=PBLN_(\d+)", a["href"])
            if key:
                registry[key[1]] = None
    except PLANNING_HTTP as error:
        print(f"Bizinfo listing unavailable: {type(error).__name__}", file=sys.stderr)
    for key in registry:
        official = params("https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do", pblancId=f"PBLN_{key}")
        try:
            detail = page(get, "biz_planning", official)
        except PLANNING_HTTP as error:
            print(f"Regional notice unavailable: {type(error).__name__}", file=sys.stderr)
            continue
        heading = detail.select_one("h2")
        fields = {label.get_text(" ", strip=True): label.find_next_sibling("div", class_="txt")
                  for label in detail.select(".s_title")}
        if not heading or not all(fields.get(name) for name in ("사업수행기관", "신청기간", "사업개요")):
            continue
        title = heading.get_text(" ", strip=True)
        publisher = fields["사업수행기관"].get_text(" ", strip=True)
        overview = fields["사업개요"].get_text("\n", strip=True)
        if not planning_type(title) or "테크노파크" not in publisher:
            continue
        source_link = detail.select_one("a#barogagi[href]")
        if source_link:
            source_url = urlsplit(source_link["href"])
            source_key = parse_qs(source_url.query).get("nttId", [""])[0]
            if source_url.hostname == "dgtp.or.kr" and any(row["id"] == f"tp_planning:dgtp-{source_key}" for row in rows):
                continue
        eligibility = re.search(r"☞\s*([^\n]{1,240})", overview)
        rows.append(record("tp_planning", key, title, official, "rnd", publisher=publisher,
                           place=publisher.replace("테크노파크", ""), eligibility=eligibility[1] if eligibility else "",
                           **planning_fields(title, fields["신청기간"].get_text(" ", strip=True))))
    return require(rows)


def pohang_support(get):
    key = "000000000121126"
    url = params("https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do", pblancId=f"PBLN_{key}")
    try:
        detail = page(get, "biz_planning", url)
    except PLANNING_HTTP as error:
        print(f"Pohang TP support notice unavailable: {type(error).__name__}", file=sys.stderr)
        return []
    heading = detail.select_one("h2.title")
    fields = {label.get_text(" ", strip=True): label.find_next_sibling("div", class_="txt")
              for label in detail.select(".s_title")}
    if not heading or not all(fields.get(name) for name in ("사업수행기관", "신청기간", "사업개요")):
        return []
    publisher = fields["사업수행기관"].get_text(" ", strip=True)
    title = heading.get_text(" ", strip=True)
    overview = fields["사업개요"].get_text("\n", strip=True)
    rnd = re.search(r"R&D\s*지원\s*:\s*([^\n]+)", overview)
    commercial = re.search(r"사업화\s*지원\s*:\s*([^\n]+)", overview)
    period = planning_period(fields["신청기간"].get_text(" ", strip=True))
    if publisher != "포항테크노파크" or not ("해양기업" in title and rnd and commercial and period):
        return []
    eligibility = ""
    if "경상북도 내" in overview and "협약 후 3개월 이내" in overview:
        eligibility = "경북에 본사·지사·공장·연구소가 있거나 협약 후 3개월 이내 경북으로 이전 가능한 기업."
    return [record("regional_support", key, title, url, "support", publisher=publisher,
                   place="경북", eligibility=eligibility,
                   support_track_note="두 지원 중 하나를 선택합니다." if re.search(r"택\s*1", overview) else "",
                   support_tracks=[
                       {"name": "R&D 지원", "types": ["research"], "description": rnd[1]},
                       {"name": "사업화 지원", "types": ["technical", "testing", "commercial", "management"],
                        "description": commercial[1]},
                   ], **period)]


def bistep_planning(get):
    try:
        return require(bistep_direct(get))
    except PLANNING_HTTP as error:
        print(f"BISTEP direct board unavailable: {type(error).__name__}", file=sys.stderr)

    rows = []
    url = "https://btis.bistep.re.kr/web/board/view.do?brdIdx=52&mId=51"
    try:
        doc = page(get, "bistep_planning", url)
        body = doc.select_one(".viewTypeA")
        if body and body.h2:
            title = body.h2.get_text(" ", strip=True)
            text = body.get_text(" ", strip=True)
            period = re.search(r"공고 및 접수기간\s*:\s*(.*?)\s*(?:💻|마\. 접수방법)", text)
            audience = re.search(r"부산 소재 산·학·연 등 연구개발주체", text)
            if period and planning_type(title) == "demand" and "⑥해양" in text:
                rows.append(record("bistep_planning", "6142", title, url, "rnd", place="부산",
                                   eligibility=audience[0] if audience else "",
                                   **planning_fields(title, period[1])))
    except PLANNING_HTTP as error:
        print(f"BTIS notice unavailable: {type(error).__name__}", file=sys.stderr)

    url = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000121211"
    try:
        doc = page(get, "biz_planning", url)
        heading = doc.select_one("h2.title")
        fields = {label.get_text(" ", strip=True): label.find_next_sibling("div", class_="txt")
                  for label in doc.select(".s_title")}
        if heading and all(fields.get(name) for name in ("사업수행기관", "사업개요", "신청기간")):
            title = heading.get_text(" ", strip=True)
            overview = fields["사업개요"].get_text(" ", strip=True)
            audience = re.search(r"주관기관은\s*[^☞]{1,160}", overview)
            if "부산과학기술고등교육진흥원" in fields["사업수행기관"].get_text() and planning_type(title):
                rows.append(record("bistep_planning", "5631", title, url, "rnd", place="부산",
                                   eligibility=audience[0].strip() if audience else "",
                                   **planning_fields(title, fields["신청기간"].get_text(" ", strip=True))))
    except PLANNING_HTTP as error:
        print(f"BISTEP Bizinfo notice unavailable: {type(error).__name__}", file=sys.stderr)
    return require(rows)


def bistep_direct(get):
    url = "https://www.bistep.re.kr/kor/CMS/Board/Board.do"
    doc = page(get, "bistep_planning", params(url, mCode="MN022"))
    links = require(doc.select('.subject a[href*="board_seq="]'))
    rows = []
    for a in [link for link in links if re.search(r"기획|수요", link.get_text(" ", strip=True))][:6]:
        key = parse_qs(urlsplit(a["href"]).query).get("board_seq", [""])[0]
        if not key.isdecimal():
            continue
        detail_url = params(url, mCode="MN022", mode="view", mgr_seq=33, board_seq=key)
        try:
            detail = page(get, "bistep_planning", detail_url)
        except PLANNING_HTTP as error:
            print(f"BISTEP detail unavailable: {type(error).__name__}", file=sys.stderr)
            continue
        body = detail.select_one("#boardContents")
        heading = detail.select_one(".bdViewTit .stit")
        if not body or not heading:
            continue
        title = heading.get_text(" ", strip=True)
        if not planning_type(title) or not PLANNING_TOPIC.search(" ".join((title, body.get_text(" ", strip=True)))):
            continue
        paragraphs = [p.get_text(" ", strip=True) for p in body.select("p")]
        eligibility = next((paragraphs[i + 1].lstrip("-ㅇ ") for i, p in enumerate(paragraphs[:-1])
                            if re.fullmatch(r"(?:[가-하]\.\s*)?(?:제안\s*자격|신청\s*자격|지원\s*대상)", p)), "")
        if not eligibility:
            audience = re.search(r"부산\s+(?:역내외|소재)[^,.]{2,45}?(?=을 대상으로|를 대상으로)",
                                 body.get_text(" ", strip=True))
            eligibility = audience[0] if audience else ""
        period = detail.select_one(".bdViewWinfo .txt")
        published = detail.select_one(".viewTitWinfo .date")
        rows.append(record("bistep_planning", key, title, detail_url, "rnd", place="부산",
                           published=iso(published.get_text(strip=True).replace(".", "-")) if published else "",
                           eligibility=eligibility,
                           **planning_fields(title, period.get_text(" ", strip=True) if period else "")))
    return rows


def nia_planning(get):
    base = "https://aihub.or.kr/aihubnews/notice/"
    query = {"currMenu": 132, "topMenu": 103}
    doc = page(get, "nia_planning", params(base + "list.do", **query))
    links = require(doc.select("td.subject a.btnView[data-key]"))
    rows = []
    for a in links:
        title, key = a.get_text(" ", strip=True), a["data-key"]
        if not key.isdecimal() or not re.search(r"데이터.*구축.*수요\s*조사", title):
            continue
        detail_url = params(base + "view.do", **query, nttSn=key)
        detail = page(get, "nia_planning", detail_url)
        body = detail.select_one(".newsView")
        if not body:
            continue
        text = body.get_text("\n", strip=True)
        audience = re.search(r"조사대상\s*:\s*([^\n]+)", text)
        period = re.search(r"조사기간\s*:\s*([^\n]+)", text)
        if title not in text or not period:
            continue
        rows.append(record("nia_planning", key, title, detail_url, "rnd",
                           eligibility=audience[1] if audience else "",
                           topic="현장에 필요한 AI 학습용 데이터 수요 제안",
                           **planning_fields(title, period[1])))
    return rows


def keit_planning(get):
    listing = "https://itech.keit.re.kr/bsnsancm/retrieveSbjtPlnnAncmList.do"
    # Keep the verified cross-sector baseline when ITECH temporarily redirects.
    candidates = {"001026": ""}
    try:
        doc = page(get, "keit_planning", listing)
        links = require(doc.select('a[href="#detail"][onclick^="f_detailPage"]'))
    except PLANNING_HTTP as error:
        print(f"KEIT index unavailable: {type(error).__name__}", file=sys.stderr)
        links = []
    for a in links:
        title = a.get_text(" ", strip=True)
        key = re.search(r"'(\d+)'", a["onclick"])
        if key and PLANNING_TOPIC.search(title):
            candidates[key[1]] = title
    rows = []
    for key, expected_title in list(candidates.items())[:5]:
        if expected_title and not planning_type(expected_title):
            continue
        url = params("https://srome.keit.re.kr/srome/biz/perform/opnnPrpsl/retrieveRndPlnnDtlView.do",
                     prgmId="XPG201010000", sbjtPlnnAncmId=key)
        try:
            detail = page(get, "keit_planning", url)
        except PLANNING_HTTP as error:
            print(f"KEIT detail unavailable: {type(error).__name__}", file=sys.stderr)
            continue
        heading = detail.select_one(".board-head h3")
        if not heading:
            continue
        title = heading.get_text(" ", strip=True)
        if (expected_title and title != expected_title) or not PLANNING_TOPIC.search(title):
            continue
        fields = {label.get_text(strip=True): label.find_next_sibling(class_="val").get_text(" ", strip=True)
                  for label in detail.select(".board-head .label") if label.find_next_sibling(class_="val")}
        rows.append(record("keit_planning", key, title, url, "rnd", published=iso(fields.get("공고일")),
                           **planning_fields(title, fields.get("접수기간", ""))))
    return require(rows)


def nipa_demand(get):
    url = "https://nxt.nipa.kr/indexBms.do"
    try:
        doc = page(get, "nipa_demand", url)
        require([tab for tab in doc.select(".vn_title p") if tab.get_text(strip=True) == "수요조사공고"])
    except PLANNING_HTTP as error:
        print(f"NIPA NXT demand index unavailable: {type(error).__name__}", file=sys.stderr)
        return []
    cards = doc.select('.vn_box[data-type="dmand"]')
    # shortcut: audit candidates here; publish details once NXT exposes a verified direct notice link.
    titles = {title.get_text(" ", strip=True) for card in cards
              if (title := card.select_one("p:nth-of-type(2)")) and planning_type(title.get_text(" ", strip=True))}
    print(f"NIPA NXT public demand candidates: {len(titles)}", flush=True)
    return []


def kimst_planning(get):
    base = "https://www.kimst.re.kr/u/news/notice_01/board.do"
    rows = []
    for key in ("153421765145001", "153421765145982"):
        url = params(base, bno=key, type="view")
        detail = page(get, "kimst_notice", url)
        body = detail.select_one(".bbs-article-detail")
        heading = detail.select_one(".bbs-article-title")
        if not body or not heading:
            continue
        title = heading.get_text(" ", strip=True)
        lines = [p.get_text(" ", strip=True) for p in body.select("p")]
        period = next((line for line in lines if re.match(r"ㅇ\s*(?:조사\s*)?기\s*간\s*:", line)), "")
        if planning_type(title) and planning_period(period):
            date_cell = detail.find("th", string=re.compile(r"작성일"))
            published = date_cell.find_next_sibling("td") if date_cell else None
            rows.append(record("kimst_notice", key, title, url, "rnd",
                               published=iso(published.get_text(strip=True)) if published else "",
                               **planning_fields(title, period)))
    return rows


def announcements(get, source, url, selector, key, category):
    rows = []
    for anchor in page(get, source, url).select(selector):
        cells = anchor.find_parent("tr").find_all("td", recursive=False)
        href = anchor["href"]
        title = anchor.get_text(" ", strip=True)
        schedule = {}
        if source == "kimst_notice":
            if re.search(r"채용|임원|인사발령|연구윤리|입찰|위탁정산", title):
                continue
            kind = ("rnd" if re.search(r"RFP|수요조사|연구개발사업|연구기획", title)
                    else "domestic" if re.search(r"전시|박람회|기술대전|설명회|상담회", title)
                    else "support")
            published, deadline = iso(cells[2].get_text(strip=True)), ""
        else:
            kind = category
            published = iso(cells[-2 if source == "kimst_rnd" else -1].get_text(strip=True))
            period = cells[-1].get_text(" ", strip=True) if source == "kimst_rnd" else (
                anchor.find_parent("td").get_text(" ", strip=True).partition("신청기간")[2])
            dates = re.findall(DATE, period)
            deadline = iso(dates[-1]) if len(dates) >= 2 else ""
            if source == "nipa":
                parsed = planning_period(period)
                if parsed.get("deadline") == deadline:
                    schedule = {"opens": parsed["opens"], "deadline_time": parsed["deadline_time"]}
        identifier = parse_qs(urlsplit(href).query)[key][0] if key else href.rsplit("/", 1)[-1]
        stage = planning_type(title) or ("application" if source == "kimst_rnd" else "")
        rows.append(record(source, identifier, title, urljoin(url, href), kind,
                           published=published, deadline=deadline, planning_stage=stage if kind == "rnd" else "",
                           **schedule))
    return require(rows)


def iris(get):
    url = "https://www.iris.go.kr/contents/retrieveBsnsAncmListView.do"
    rows = []
    for a in page(get, "iris", url).select('a[onclick^="f_bsnsAncmListForm_view("]'):
        args = re.findall(r"'([^']*)'", a["onclick"])
        if len(args) < 7 or not args[0].isdigit():
            continue
        group = a.find_parent("li")
        sub = group.select_one(".etc_info span:last-child")
        title = a.get_text(" ", strip=True)
        if sub:
            sub_title = sub.get_text(" ", strip=True).removeprefix("사업공고명").strip()
            if sub_title and sub_title != title:
                title += f" · {sub_title}"
        rows.append(record("iris", ":".join(args[i] for i in (0, 2, 3)), title,
                           params(urljoin(url, "retrieveBsnsAncmView.do"), ancmId=args[0]),
                           "rnd", deadline=iso(args[6]), planning_stage=planning_type(title) or "application"))
    # Government R&D is open to every industry unless the notice names another one.
    return [row for row in require(rows) if judge(row["title"])[0]]


def kmi(get):
    url = "https://www.kmi.re.kr/web/main/web/trebook/list.do?rbsIdx=273"
    rows = []
    for a in page(get, "kmi", url).select('tr a[href^="view.do"][href*="idx="]'):
        title = a.get_text(" ", strip=True)
        href = a["href"]
        if not title:
            continue
        dates = re.findall(DATE, a.find_parent("tr").get_text(" ", strip=True))
        rows.append(record("kmi", parse_qs(urlsplit(href).query)["idx"][0], title,
                           urljoin(url, href), "industry", published=iso(dates[0]) if dates else ""))
    return require(rows)


def kotra(get):
    base = "https://dream.kotra.or.kr"
    url = params(base + "/ajaxf/frNews/getKotraBoardList.do", MENU_ID=70, pageNo=1,
                 recordCountPerPage=50, bbsSn="242,244,322,245,246,444,464,518,505,484,519")
    entries = json.loads(get("kotra_ajax", url))["data"]["list"]
    rows = []
    for item in require(entries):
        title = item["NTT_SJ"]
        if MARINE.search(title) or AI.search(title):
            link = params(base + "/kotranews/cms/news/actionKotraBoardDetail.do", MENU_ID=70,
                          CONTENTS_NO=1, pNttSn=item["NTT_SN"], bbsSn=item["BBS_SN"])
            rows.append(record("kotra", item["NTT_SN"], title, link, "industry",
                               published=iso(item["OTHBC_DT_NM"]), place=clean(item.get("NAT"))))
    return rows


def gep(get):
    base = "https://www.gep.or.kr/gept/ovrss/"
    entries = json.loads(get("gep_ajax", base + "main/selectListMainExbiKrn.do"))["result"]
    rows = []
    for item in require(entries):
        title = item["krnOvrssExbiNm"]
        if MARINE.search(title) or AI.search(title):
            key = item["ovrssExbiCd"]
            rows.append(record("gep", key, title,
                               params(base + "exbi/exbiInfo/exbiDetailMain.do", ovrssExbiCd=key),
                               "international", event_start=iso(item.get("opmtPdStrDe")),
                               event_end=iso(item.get("opmtPdEndDe")), deadline=iso(item.get("rcritPdEndDe"))))
    return rows


def kstartup(get):
    url = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
    rows = []
    for a in page(get, "kstartup_list", url).select('#bizPbancList a[href^="javascript:go_view("]'):
        key = re.search(r"go_view\((\d+)\)", a["href"])[1]
        box = a.find_parent("li")
        title = a.select_one(".tit").get_text(" ", strip=True)
        fields = {}
        for label, field in (("등록일자", "published"), ("시작일자", "opens"), ("마감일자", "deadline")):
            match = re.search(rf"{label}\s+({DATE})", box.get_text(" ", strip=True))
            if match:
                fields[field] = iso(match[1])
        rows.append(record("kstartup", key, title, params(url, schM="view", pbancSn=key), "support", **fields))
    return require(rows)


KSTARTUP_PAGE = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
KSTARTUP_API = "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"
BIZINFO_API = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
BIZINFO_EVENT_API = "https://www.bizinfo.go.kr/uss/rss/bizinfoEventApi.do"
API_KEYS = ("KSTARTUP_API_KEY", "BIZINFO_API_KEY", "BIZINFO_EVENT_API_KEY")
SHORT_REGIONS = [name for name in REGIONS if name not in ("전국", "해외")]
LONG_REGIONS = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
    "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원",
    "강원도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북",
    "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주",
}
DATE_TIME = re.compile(r"(20\d{2})[.\-/\s]*(\d{1,2})[.\-/\s]*(\d{1,2})(?:\D{0,4}?((?:[01]\d|2[0-3]):[0-5]\d))?")
RND_TITLE = re.compile(r"R&D|연구개발|기술개발\s*사업|신규\s*(?:지원\s*)?(?:대상\s*)?과제|과제\s*공모")
# Official program fields mapped onto the portal's support facets.
KSTARTUP_FIELDS = {
    "사업화": {"types": ["commercial"]},
    "시설ㆍ공간ㆍ보육": {"types": ["infrastructure", "incubation"], "methods": ["access"]},
    "멘토링ㆍ컨설팅ㆍ교육": {"methods": ["service"]},
    "창업교육": {"methods": ["service"]},
    "행사ㆍ네트워크": {"methods": ["matching"]},
    "인력": {"types": ["people"]},
    "정책자금": {"types": ["finance"], "methods": ["loan"]},
    "융자ㆍ보증": {"types": ["finance"], "methods": ["loan"]},
    "판로ㆍ해외진출": {"types": ["export"]},
    "글로벌": {"types": ["export"]},
    "기술개발(R&D)": {"types": ["research"]},
}
BIZINFO_FIELDS = {
    "금융": "finance", "기술": "technical", "인력": "people", "수출": "export",
    "내수": "commercial", "창업": "incubation", "경영": "management",
}


def kst_today():
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def period_note(text):
    """Return the stated application period when it names no date, such as "예산 소진 시까지"."""
    text = clean(text)
    if not text or DATE_TIME.search(text) or re.search(r"\d{8}", text):
        return ""
    return shorten(re.sub(r"(소진|완료|마감)시", r"\1 시", text), 30)


def stated_target(summary):
    """Return the target line of a Bizinfo summary written as "개요 ☞ 대상 ☞ 지원내용"."""
    parts = str(summary or "").split("☞")
    return clean(parts[1]) if len(parts) > 2 else ""


def date_range(text):
    """Return (first date, last date, last time) from an official period string."""
    found = []
    for year, month, day, clock in DATE_TIME.findall(str(text or "")):
        value = iso(f"{year}-{int(month):02}-{int(day):02}")
        if value:
            found.append((value, clock))
    if not found:
        return "", "", ""
    if len(found) == 1:
        return "", found[0][0], found[0][1]
    return found[0][0], found[-1][0], found[-1][1]


def shorten(value, limit=160):
    text = clean(value)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def keyed(url, key_param, key, **values):
    # Public Data Portal keys may be stored already URL-encoded.
    encoded = key if "%" in key else quote(key, safe="")
    return f"{url}?{key_param}={encoded}&{urlencode(values)}"


def region_hint(title, authority="", tags=(), organizer=""):
    prefix = re.match(r"\s*\[([^\]]+)\]", title or "")
    if prefix:
        names = [name for name in SHORT_REGIONS if name in prefix[1]]
        if names:
            return names
    # A provincial authority or a regional agency named after its province, e.g. 울산테크노파크.
    for name in (authority or "", organizer or ""):
        for long, short in LONG_REGIONS.items():
            if name.startswith(long):
                return [short]
        if name.startswith(tuple(SHORT_REGIONS)) and not name.startswith(("경제", "대한")):
            return [next(short for short in SHORT_REGIONS if name.startswith(short))]
    tagged = {name for tag in tags for name in SHORT_REGIONS if tag in (name, "전남광주") and name in tag}
    return sorted(tagged) if 0 < len(tagged) <= 2 else ["전국"]


def kstartup_regions(value):
    names = set()
    for part in re.split(r"[,·ㆍ/\s]+", value or ""):
        part = LONG_REGIONS.get(part, part)
        if part in REGIONS:
            names.add(part)
    return sorted(names) or ["전국"]


def kstartup_stages(value):
    stages = set()
    if "예비" in (value or ""):
        stages.add("prestartup")
    if re.search(r"(?<!\d)[123]년\s*미만", value or ""):
        stages.add("early")
    if re.search(r"(?:5|7|10)년\s*(?:미만|이상)", value or ""):
        stages.add("scaleup")
    return sorted(stages)


def tally(source, counts, kept):
    dropped = ", ".join(f"{label} {count}" for label, count in sorted(counts.items()))
    print(f"{source}: 포함 {kept}" + (f" / 제외 {dropped}" if dropped else ""), flush=True)


def kstartup_api(get, key):
    today = kst_today()
    rows, dropped, page_no = [], {}, 1
    while page_no <= 30:
        data = json.loads(get("kstartup_api", keyed(KSTARTUP_API, "serviceKey", key, page=page_no, perPage=100,
                                                     returnType="json", **{"cond[rcrt_prgs_yn::EQ]": "Y"})))
        items = data.get("data") or []
        for item in items:
            number = str(item.get("pbanc_sn") or "").strip()
            title = clean(item.get("biz_pbanc_nm"))
            if not number.isdigit() or not title:
                continue
            opens = date_range(item.get("pbanc_rcpt_bgng_dt"))[1]
            _, deadline, clock = date_range(item.get("pbanc_rcpt_end_dt"))
            if deadline and deadline < today:
                dropped["마감"] = dropped.get("마감", 0) + 1
                continue
            organizer = clean(item.get("pbanc_ntrp_nm"))
            keep, label = judge(title, organizer, clean(item.get("aply_trgt")))
            if not keep:
                dropped[label] = dropped.get(label, 0) + 1
                continue
            hints = {}
            for name in re.split(r"[,]\s*", clean(item.get("supt_biz_clsfc"))):
                for field, values in KSTARTUP_FIELDS.get(name, {}).items():
                    hints.setdefault(field, []).extend(values)
            stages = kstartup_stages(clean(item.get("biz_enyy")))
            if stages:
                hints["stages"] = stages
            hints["regions"] = kstartup_regions(clean(item.get("supt_regin")))
            rows.append(record("kstartup", number, title, params(KSTARTUP_PAGE, schM="view", pbancSn=number),
                               "support", opens=opens, deadline=deadline, deadline_time=clock,
                               publisher=organizer, eligibility=shorten(item.get("aply_trgt_ctnt")),
                               maritime=label == "해양 특화", support_hints=hints))
        total = int(data.get("totalCount") or 0)
        if not items or page_no * 100 >= total:
            break
        page_no += 1
    tally("kstartup", dropped, len(rows))
    return require(rows)


def bizinfo_api(get, key):
    today = kst_today()
    data = json.loads(get("bizinfo_api", keyed(BIZINFO_API, "crtfcKey", key, dataType="json", searchCnt=0)))
    rows, dropped = [], {}
    for item in require(data.get("jsonArray") or []):
        number = str(item.get("pblancId") or "")
        title = clean(item.get("pblancNm"))
        if not re.fullmatch(r"PBLN_\d+", number) or not title:
            continue
        organizer = clean(item.get("excInsttNm"))
        if organizer in ("", "기초자치단체", "직접수행", "-"):
            organizer = clean(item.get("jrsdInsttNm"))  # placeholder values name no agency
        target = stated_target(item.get("bsnsSumryCn"))
        keep, label = judge(title, organizer, clean(item.get("trgetNm")), target)
        if not keep:
            dropped[label] = dropped.get(label, 0) + 1
            continue
        opens, deadline, clock = date_range(item.get("reqstBeginEndDe"))
        if deadline and deadline < today:
            dropped["마감"] = dropped.get("마감", 0) + 1
            continue
        tags = [tag.strip() for tag in re.split(r"[,#]", item.get("hashtags") or "") if tag.strip()]
        is_rnd = bool(planning_type(title) or RND_TITLE.search(title))
        hints = {"regions": region_hint(title, clean(item.get("jrsdInsttNm")), tags, organizer)}
        field = BIZINFO_FIELDS.get(clean(item.get("pldirSportRealmLclasCodeNm")))
        if field:
            hints["types"] = [field]
        rows.append(record("bizinfo", number, title,
                           params("https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do", pblancId=number),
                           "rnd" if is_rnd else "support", published=iso(str(item.get("creatPnttm") or "")[:10]),
                           opens=opens, deadline=deadline, deadline_time=clock, publisher=organizer,
                           period_note="" if deadline else period_note(item.get("reqstBeginEndDe")),
                           topic=shorten(item.get("bsnsSumryCn"), 140),
                           eligibility=shorten(target or item.get("trgetNm"), 120),
                           planning_stage=(planning_type(title) or "application") if is_rnd else "",
                           place=hints["regions"][0] if len(hints["regions"]) == 1 and hints["regions"][0] != "전국" else "",
                           maritime=label == "해양 특화", support_hints=hints))
    tally("bizinfo", dropped, len(rows))
    return rows


def bizinfo_events(get, key):
    today = kst_today()
    data = json.loads(get("bizinfo_event_api", keyed(BIZINFO_EVENT_API, "crtfcKey", key, dataType="json", searchCnt=0)))
    rows, dropped = [], {}
    for item in require(data.get("jsonArray") or []):
        number = str(item.get("eventInfoId") or "")
        title = clean(item.get("nttNm"))
        if not re.fullmatch(r"EVEN_\d+", number) or not title:
            continue
        start, end, _ = date_range(item.get("eventBeginEndDe"))
        start = start or end
        if (end or start) and (end or start) < today:
            dropped["종료"] = dropped.get("종료", 0) + 1
            continue
        organizer = clean(item.get("originEngnNm"))
        keep, label = judge(title, organizer)
        if not keep:
            dropped[label] = dropped.get(label, 0) + 1
            continue
        url = next((value for value in (item.get("bizinfoUrl"), item.get("orginlUrlAdres"))
                    if str(value or "").startswith("https://")), "")
        if not url:
            dropped["원문 주소 없음"] = dropped.get("원문 주소 없음", 0) + 1
            continue
        opens, deadline, clock = date_range(item.get("rceptPd"))
        area = clean(item.get("areaNm"))
        kind = clean(item.get("eventInfoTyNm"))
        rows.append(record("bizinfo_event", number, title, url,
                           "international" if re.search(r"해외|국외", area) else "domestic",
                           event_start=start, event_end=end, opens=opens, deadline=deadline, deadline_time=clock,
                           event_region=area, publisher=organizer, topic=shorten(item.get("nttCn"), 140),
                           event_types=[kind] if kind else [], maritime=label == "해양 특화"))
    tally("bizinfo_event", dropped, len(rows))
    return rows


def komeri(get):
    base = "https://www.komeri.re.kr/bbs/board.php"
    boxes = require(page(get, "komeri", params(base, bo_table="business")).select(".bbsBox"))
    today = date.fromisoformat(kst_today())
    rows = []
    for box in boxes:
        link = box.select_one('.title a[href*="wr_id="]')
        posted = box.select_one(".date")
        if not link or not posted:
            continue
        number = parse_qs(urlsplit(link["href"]).query).get("wr_id", [""])[0]
        published = iso(posted.get_text(strip=True))
        title = link.get_text(" ", strip=True)
        # Only recent notices can still be open; older ones are skipped without a detail request.
        if not number.isdigit() or not published or (today - date.fromisoformat(published)).days > 90:
            continue
        if not judge(title)[0]:
            continue
        url = params(base, bo_table="business", wr_id=number)
        body = page(get, "komeri", url).select_one("#bo_v_con")
        text = body.get_text("\n", strip=True) if body else ""
        fields = {}
        period = re.search(r"(?:모집|접수|신청)\s*기간\s*:\s*([^\n]+)", text)
        if period:
            fields.update(planning_period(period[1]))
        target = re.search(r"지원\s*대상\s*:\s*([^\n□※]{1,160})", text)
        if target:
            fields["eligibility"] = target[1].strip()
        if fields.get("deadline") and fields["deadline"] < today.isoformat():
            continue
        rows.append(record("komeri", number, title, url, "support", published=published,
                           publisher="한국조선해양기자재연구원", maritime=True, **fields))
    return rows


def drop_hub_duplicates(records):
    """Keep the K-Startup copy when Bizinfo republishes the same notice."""
    key = lambda title: re.sub(r"[^가-힣A-Za-z0-9]", "", title)[:40]
    startup = {key(row["title"]) for row in records.values() if row["source"] == "kstartup"}
    for record_id in [i for i, row in records.items() if row["source"] == "bizinfo" and key(row["title"]) in startup]:
        del records[record_id]


def bisfe(get):
    url = "https://www.bisfe.com/sub01/sub02.php"
    cells = {}
    for th in page(get, "bisfe", url).select("tr > th"):
        td = th.find_next_sibling("td")
        if td:
            cells[re.sub(r"\s", "", th.get_text())] = td.get_text(" ", strip=True)
    title = cells["전시회명"]
    match = re.search(r"(\d{4})년\s*(\d+)월\s*(\d+)일[^~]*~\s*(\d+)월\s*(\d+)일", cells["기간"])
    if not match:
        raise ValueError("Event schedule format changed")
    year, month, day, end_month, end_day = map(int, match.groups())
    return [record("bisfe", year, title, url, "domestic", event_start=date(year, month, day).isoformat(),
                   event_end=date(year + (end_month < month), end_month, end_day).isoformat(), place=cells["장소"])]


def nor_shipping_origin(links):
    # shortcut: one reviewed organizer; add a parser before admitting another event site.
    official = re.compile(r"^https?://((?:www\.)?nor-shipping\.com)(?:/|$)")
    return next((f"https://{match[1]}/" for url in links
                 if isinstance(url, str) and (match := official.match(url))), None)


def discover_nor_shipping(get):
    try:
        items = DDGS(timeout=10).text("maritime exhibition site:nor-shipping.com",
                                      max_results=8, backend="duckduckgo", region="uk-en")
    except DDGSException as error:
        print(f"DDGS DuckDuckGo returned no usable response ({type(error).__name__})", flush=True)
    else:
        url = nor_shipping_origin(item.get("href") for item in items)
        print(f"DDGS DuckDuckGo: {len(items)} results, Nor-Shipping official host matched: {bool(url)}", flush=True)
        if url:
            return url

    query = params("https://api.mwmbl.org/api/v2/search/", q="Nor-Shipping maritime exhibition")
    try:
        items = json.loads(get("mwmbl", query))["results"]
        if not isinstance(items, list):
            raise ValueError("Unexpected Mwmbl response")
        url = nor_shipping_origin(item.get("url") for item in items if isinstance(item, dict))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Mwmbl returned no usable response ({type(error).__name__})", flush=True)
        return None
    print(f"Mwmbl: {len(items)} results, Nor-Shipping official host matched: {bool(url)}", flush=True)
    return url


def nor_shipping(get):
    url = discover_nor_shipping(get)
    if not url:
        print("Nor-Shipping: collecting from the reviewed organizer URL", flush=True)
        url = NOR_SHIPPING
    document = page(get, "nor_shipping", url)
    title = document.select_one('meta[property="og:title"]')
    title_match = re.fullmatch(r"Nor-Shipping (\d{4})", title.get("content", "")) if title else None
    if not title_match:
        raise ValueError("Nor-Shipping event title format changed")
    schedule = re.compile(
        rf"(\d{{1,2}})\s*[–-]\s*(\d{{1,2}})\s+([A-Z]+)\s+{title_match[1]}\s*\|\s*"
        r"EXHIBITION\s+(\d{1,2})\s*[–-]\s*(\d{1,2})\s+\3\s*\|\s*(.+)", re.I)
    match = next((match for heading in document.select("h2")
                  if (match := schedule.fullmatch(heading.get_text(" ", strip=True)))), None)
    if not match:
        raise ValueError("Nor-Shipping event schedule format changed")
    start_day, end_day, month, exhibition_start, exhibition_end, place = match.groups()
    year = title_match[1]
    start, end, show_start, show_end = [
        datetime.strptime(f"{value} {month.title()} {year}", "%d %B %Y").date().isoformat()
        for value in (start_day, end_day, exhibition_start, exhibition_end)
    ]
    if not start <= show_start <= show_end <= end:
        raise ValueError("Nor-Shipping event dates are inconsistent")
    links = {urljoin(NOR_SHIPPING, anchor["href"]) for anchor in document.select("a[href]")}
    participation = {field: link for field, path in (
        ("visit_url", "the-exhibition/"), ("exhibit_url", "becomeanexhibitor/"))
        if (link := urljoin(NOR_SHIPPING, path)) in links}
    return [record("nor_shipping", year, title["content"], NOR_SHIPPING, "international",
                   event_start=start, event_end=end, exhibition_start=show_start, exhibition_end=show_end,
                   place=place, **participation)]


def exhibition_key(title, start, end):
    if not start or not end or start > end:
        return None
    title = unicodedata.normalize("NFKC", title).casefold()
    title = re.sub(rf"(?<!\d){start[:4]}(?!\d)", "", title)
    name = "".join(character for character in title if character.isalnum())
    return (name, start, end) if name else None


def merge_exhibitions(records):
    organizers = {}
    gep_notices = []
    for row in records.values():
        if row["category"] != "international":
            continue
        if row["source"] == "gep":
            gep_notices.append(row)
            continue
        key = exhibition_key(row["title"], row.get("exhibition_start") or row.get("event_start"),
                             row.get("exhibition_end") or row.get("event_end"))
        if key:
            organizers.setdefault(key, []).append(row)

    for notice in gep_notices:
        title = unicodedata.normalize("NFKC", notice["title"]).strip()
        # shortcut: use exact dates and a shared name; add explicit aliases for verified translations.
        alias = re.search(r"\[([^\[\]]+)\]$|\(([^()]+)\)$", title)
        titles = [title, alias[1] or alias[2]] if alias else [title]
        matches = {}
        for name in titles:
            key = exhibition_key(name, notice.get("event_start"), notice.get("event_end"))
            matches.update((row["id"], row) for row in organizers.get(key, ()))
        if len(matches) == 1:
            official, = matches.values()
            official.setdefault("gep_notices", []).append({
                field: notice[field] for field in ("title", "url", "deadline", "deadline_time") if field in notice
            })
            del records[notice["id"]]


def naver_headers():
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id and not client_secret:
        return {}
    if not client_id or not client_secret:
        raise ValueError("Set both Naver Actions Secrets")
    return {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}


def check_naver(get):
    headers = naver_headers()
    if not headers:
        raise SystemExit("Missing Naver Actions Secrets")
    searches = (
        ("news", NEWS_TERMS, {"display": 20, "sort": "date"}),
        ("webkr", WEB_TERMS, {"display": 10, "start": 1}),
    )
    for endpoint, terms, options in searches:
        total = 0
        for term in terms:
            url = params(f"https://openapi.naver.com/v1/search/{endpoint}.json", query=term, **options)
            items = json.loads(get("naver", url, headers))["items"]
            if not isinstance(items, list) or any(
                not isinstance(item, dict) or not item.get("title") or not item.get("link")
                for item in items
            ):
                raise ValueError(f"Naver {endpoint} returned an unexpected response")
            total += len(items)
            print(f"{endpoint} {term}: {len(items)} results")
        if total == 0:
            raise SystemExit(f"Naver {endpoint} returned zero results")
        print(f"Naver {endpoint} API verified: {total} results across {len(terms)} queries")


def discover_jcia(get, headers):
    url = params("https://openapi.naver.com/v1/search/webkr.json",
                 query=JCIA_QUERY, display=10, start=1)
    items = json.loads(get("naver", url, headers))["items"]
    ids = []
    for item in items:
        link = urlsplit(item["link"])
        match = JCIA_POST.fullmatch(link.path)
        if (link.scheme == "https" and link.netloc in ("www.jcia.or.kr", "jcia.or.kr")
                and match and match[1] not in ids):
            ids.append(match[1])
    print(f"JCIA discovery: {len(ids)} official detail candidates", flush=True)
    return ids


def jcia_post(get, key):
    url = f"{JCIA}/cf/Board/{key}/detailView.do"
    document = page(get, "jcia", url)
    heading = next((h.get_text(" ", strip=True) for h in document.select("h2")
                    if re.search(r"AI\s*어장\s*현장실증", h.get_text(" ", strip=True))), "")
    fields = {th.get_text(" ", strip=True): th.find_next_sibling("td")
              for th in document.select("th") if th.find_next_sibling("td")}
    deadline = iso(fields["종료일"].get_text(" ", strip=True)) if "종료일" in fields else ""
    published = iso(fields["등록일"].get_text(" ", strip=True)) if "등록일" in fields else ""
    if not heading or not deadline or not published:
        return None

    attachments = []
    for link in document.select("a[onclick]"):
        title = link.get_text(" ", strip=True)
        key_match = re.fullmatch(r"cf_download\('(?P<key>FS_[0-9]{10})'\);?", link["onclick"].strip())
        if key_match and re.search(r"공고.*\.pdf", title, re.I):
            attachments.append(key_match["key"])
    if len(attachments) != 1:
        return None

    pdf_url = params(f"{JCIA}/async/MultiFile/download.do", FS_KEYNO=attachments[0])
    pdf = PdfReader(BytesIO(get("jcia", pdf_url)))
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in pdf.pages[:10])
    eligibility = re.search(r"(?:지원|신청)\s*대상\s*:\s*([^※❍•]{1,180})(?=\s*[※❍•])", text)
    timing = re.search(
        r"접수\s*기간\s*:[^❍•]{0,65}?(\d{2,4})\.\s*(\d{1,2})\.\s*(\d{1,2})"
        r"\.?\s*(?:\([가-힣]\))?\s*((?:[01]\d|2[0-3]):[0-5]\d)", text)
    if not eligibility or not timing:
        return None
    year, month, day, clock = timing.groups()
    year = f"20{year}" if len(year) == 2 else year
    pdf_day = iso(f"{year}-{int(month):02}-{int(day):02}")
    if pdf_day != deadline:
        return None
    return record("jcia", key, heading, url, "support", published=published,
                  deadline=deadline, deadline_time=clock, eligibility=eligibility[1].strip(),
                  eligibility_url=pdf_url)


def jcia_notices(get, discovery_only=False):
    headers = naver_headers()
    discovered = []
    if headers:
        try:
            discovered = discover_jcia(get, headers)
        except (OSError, ValueError, KeyError, TypeError):
            if discovery_only:
                raise
            print("JCIA discovery unavailable; using reviewed official posts", file=sys.stderr)
    keys = discovered[:3] if discovery_only else list(dict.fromkeys([*JCIA_REVIEWED, *discovered[:3]]))
    rows = []
    for key in keys:
        try:
            row = jcia_post(get, key)
        except (OSError, ValueError, subprocess.SubprocessError, PdfReadError):
            if key in JCIA_REVIEWED:
                raise
            continue
        if row:
            rows.append(row)
    if discovery_only:
        print(f"JCIA discovery verified from original notices: {len(rows)}", flush=True)
    return require(rows)


SOURCES = {
    "kimst_rnd": ("KIMST 사업공고", lambda get: announcements(get, "kimst_rnd",
        "https://www.kimst.re.kr/u/rnd/inform_01/pjtAnuc.do", 'tr a[href*="anucno="]', "anucno", "rnd")),
    "kimst_notice": ("KIMST 공지사항", lambda get: announcements(get, "kimst_notice",
        "https://www.kimst.re.kr/u/news/notice_01/board.do", 'tr a[href*="bno="]', "bno", "rnd")),
    "nipa": ("NIPA", lambda get: announcements(get, "nipa", "https://www.nipa.kr/home/2-2",
        'tr a[href^="/home/2-2/"]', None, "support")),
    "iris": ("IRIS", iris),
    "kmi": ("KMI 동향분석", kmi),
    "kotra": ("KOTRA 해외시장뉴스", kotra),
    "gep": ("KOTRA 글로벌 전시 플랫폼", gep),
    "kstartup": ("K-Startup", kstartup),
    "bisfe": ("부산국제수산엑스포", bisfe),
}


# shortcut: verified notice IDs supply dates and venues until detail parsers cover these formats.
REVIEWED_EVENTS = {
    "nipa:16953": dict(category="international", event_region="베트남", place="하노이",
                       event_start="2026-10-29"),
    "nipa:16931": dict(category="international", event_region="인도", place="벵갈루루 국제전시센터",
                       event_start="2026-11-17", event_end="2026-11-19"),
    "kstartup:179822": dict(category="domestic", event_region="서울", place="스페이스쉐어 서울역 3센터",
                            event_start="2026-12-01", deadline_time="18:00",
                            participation=["IR 피칭", "상담·매칭"]),
    "kstartup:179823": dict(category="domestic", event_region="전북", place="김제시 죽산면",
                            event_start="2026-11-26", deadline_time="23:59"),
}


def classify_information(entry):
    title = entry["title"]
    source = entry["source"]
    if source == "kimst_notice" and re.match(r"KIMST\s*지원\s*연구\s*,", title):
        entry.update(category="patent", technology_type="연구성과")
        if re.search(r"오염|방사능", title):
            entry["technology_fields"] = ["해양환경"]
    entry.update(REVIEWED_EVENTS.get(entry["id"], {}))

    if entry["category"] == "industry":
        entry["industry_sectors"] = [
            label for label, pattern in (
                ("해운·항만", r"해운|항만|운하"), ("조선·기자재", r"조선|기자재"),
                ("수산·양식", r"수산|양식|어업|어장"), ("해양", r"해양"),
                ("AI·디지털", AI), ("금융", r"금융|루블|모바일머니"),
            ) if re.search(pattern, title)
        ]
        entry["industry_topics"] = [
            label for label, pattern in (
                ("시장·수출", r"소비|수출|수요|시장|판로"), ("정책·제도", r"정책|제도|규제|의무|선거|관리\s*공백"),
                ("투자·협력", r"투자|협력"), ("공급망·운송", r"공급망|운하|통항"),
            ) if re.search(pattern, title)
        ]
    if entry["category"] in ("domestic", "international"):
        types = [label for label, pattern in (
            ("전시", r"전시|박람회|기술대전|EXPO|Nor-Shipping"),
            ("콘퍼런스·포럼", r"콘퍼런스|컨퍼런스|포럼|세미나"),
            ("IR·투자 설명회", r"투자\s*설명회|INVESTOR\s*DAY"),
        ) if re.search(pattern, title, re.I)]
        if types:
            entry["event_types"] = types
        if source == "nor_shipping":
            entry["event_region"] = "노르웨이"
        elif source == "bisfe":
            entry["event_region"] = "부산"
        participation = []
        if entry.get("visit_url"):
            participation.append("참관")
        if entry.get("exhibit_url") or ("전시" in types and re.search(r"참가\s*기업\s*모집", title)):
            participation.append("전시 참가")
        if re.search(r"매칭\s*부스|상담\s*부스", title):
            participation.append("상담·매칭")
        if participation and not entry.get("participation"):
            entry["participation"] = participation


def build(samples):
    get = reader(samples)
    sources = dict(SOURCES)
    if not samples:
        notice_label, collect_notices = sources["kimst_notice"]
        sources["kimst_notice"] = (notice_label, lambda get: collect_notices(get) + kimst_planning(get))
        sources["jcia"] = ("전남정보문화산업진흥원", jcia_notices)
        sources["nor_shipping"] = ("Nor-Shipping", nor_shipping)
        sources["tp_planning"] = ("지역 테크노파크", regional_planning)
        sources["regional_support"] = ("지역 테크노파크 기업지원", pohang_support)
        sources["bistep_planning"] = ("BISTEP", bistep_planning)
        sources["nia_planning"] = ("NIA·AI허브", nia_planning)
        sources["nipa_demand"] = ("NIPA·NXT 수요조사", nipa_demand)
        sources["keit_planning"] = ("KEIT 과제기획", keit_planning)
        sources["komeri"] = ("한국조선해양기자재연구원", komeri)
        keys = {name: os.getenv(name, "").strip() for name in API_KEYS}
        missing = [name for name in ("KSTARTUP_API_KEY", "BIZINFO_API_KEY") if not keys[name]]
        if missing and os.getenv("GITHUB_ACTIONS") == "true":
            raise SystemExit("Missing Actions Secrets: " + ", ".join(missing))
        if keys["KSTARTUP_API_KEY"]:
            sources["kstartup"] = ("K-Startup", lambda get: kstartup_api(get, keys["KSTARTUP_API_KEY"]))
        if keys["BIZINFO_API_KEY"]:
            event_key = keys["BIZINFO_EVENT_API_KEY"] or keys["BIZINFO_API_KEY"]
            sources["bizinfo"] = ("기업마당", lambda get: bizinfo_api(get, keys["BIZINFO_API_KEY"]))
            sources["bizinfo_event"] = ("기업마당 행사정보", lambda get: bizinfo_events(get, event_key))

    records, failed = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {key: pool.submit(collect, get) for key, (_, collect) in sources.items()}
        for key, job in jobs.items():
            try:
                rows = job.result()
                records.update((row["id"], row) for row in rows)
                print(f"{key}: {len({row['id'] for row in rows})}")
            except Exception as error:
                failed.append(key)
                print(f"{key}: {type(error).__name__} {getattr(error, 'code', '')}", file=sys.stderr)
    if failed:
        raise SystemExit("Collection failed: " + ", ".join(failed))

    drop_hub_duplicates(records)
    for entry in records.values():
        classify_information(entry)
        classify_support(entry)
        if entry["category"] in ("support", "rnd"):
            entry.update(sector_profile(entry["title"], entry.get("eligibility", ""), entry.get("publisher", ""),
                                        entry["source"]))
    merge_exhibitions(records)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for name in ("portal.css", "portal.js"):
        shutil.copyfile(ROOT / "site" / name, dist / name)
    shutil.copytree(ROOT / "site/logos", dist / "logos", dirs_exist_ok=True)
    updated_at = datetime.now(timezone.utc)
    payload = {"updated_at": updated_at.isoformat(), "sample": bool(samples),
               "sources": {key: label for key, (label, _) in sources.items() if key != "nipa_demand" or
                           any(row["source"] == key for row in records.values())},
               "support_facets": {"types": TYPES, "stages": STAGES, "methods": METHODS,
                                  "regions": {name: name for name in REGIONS}},
               "records": list(records.values())}
    temporary = dist / "data.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(dist / "data.json")
    index = (ROOT / "site/index.html").read_text(encoding="utf-8")
    index = index.replace('src="./portal.js"', f'src="./portal.js?v={updated_at:%Y%m%d%H%M%S%f}"')
    (dist / "index.html").write_text(index, encoding="utf-8")
    print(f"{len(records)} records written to dist/data.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, help="Replay saved HTTP responses from the source checks")
    parser.add_argument("--check-naver", action="store_true", help="Check live Naver News and Web response counts")
    args = parser.parse_args()
    if args.check_naver:
        get = reader(None)
        check_naver(get)
        jcia_notices(get, discovery_only=True)
    else:
        build(args.samples)
