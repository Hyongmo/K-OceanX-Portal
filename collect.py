"""Collect source metadata and build the static K-OceanX portal."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import gzip
import hashlib
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
from target_rules import (AGE_BANDS, MARITIME, NOT_SUPPORT, age_bands, bands_under, judge, other_trades_only, sector_profile,
                          training_scope)

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


# Sites that serve no https at all; their pages are linked over http.
HTTP_ONLY_HOSTS = {"wof.kr", "www.kinpr.or.kr", "www.offshorekorea.org"}


def record(source, key, title, url, category, **fields):
    parsed = urlsplit(url)
    title = clean(title)
    secure = parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in HTTP_ONLY_HOSTS)
    if not key or not title or not secure or not parsed.hostname or parsed.username:
        raise ValueError("Invalid record identifier, title or URL")
    return {"id": f"{source}:{key}", "source": source, "title": title,
            "url": url, "category": category, **{k: v for k, v in fields.items() if v}}


def reader(samples):
    def get(name, url, headers=None, data=None):
        if samples:
            return (samples / f"{name}.body").read_bytes()
        # Event posters are tall pictures; other answers stay under 8 MB.
        limit = 30_000_000 if name == "eventus_poster" else 8_000_000
        if name in ("kimst_rnd", "kimst_notice", "jcia", "tp_planning", "biz_planning",
                    "bistep_planning", "nia_planning", "nipa_demand", "keit_planning"):
            # These publishers work with curl on the development host.
            raw = subprocess.check_output(["curl", "-fsSL", "--max-time", "20", "--max-filesize",
                                           "8000000", "--proto", "=https",
                                           "--user-agent", "K-OceanX pilot/0.1", url])
        else:
            request = Request(url, data=data, headers={"User-Agent": "K-OceanX pilot/0.1"})
            for key, value in (headers or {}).items():
                request.add_unredirected_header(key, value)
            with urlopen(request, timeout=20) as response:
                raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Response exceeds the size limit")
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
    rows, seen = [], set()
    # The open-call list shows ten items a page; read every page until no new item appears.
    for page_no in range(1, 21):
        added = 0
        for a in page(get, "iris", params(url, pageIndex=page_no)).select('a[onclick^="f_bsnsAncmListForm_view("]'):
            args = re.findall(r"'([^']*)'", a["onclick"])
            if len(args) < 7 or not args[0].isdigit():
                continue
            key = ":".join(args[i] for i in (0, 2, 3))
            if key in seen:
                continue
            seen.add(key)
            added += 1
            group = a.find_parent("li")
            sub = group.select_one(".etc_info span:last-child") if group else None
            title = a.get_text(" ", strip=True)
            if sub:
                sub_title = sub.get_text(" ", strip=True).removeprefix("사업공고명").strip()
                if sub_title and sub_title != title:
                    title += f" · {sub_title}"
            rows.append(record("iris", key, title, params(urljoin(url, "retrieveBsnsAncmView.do"), ancmId=args[0]),
                               "rnd", deadline=iso(args[6]), planning_stage=planning_type(title) or "application"))
        if not added:
            break
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
# Programs that name R&D but give something else: non-R&D tracks, marketing, shared equipment,
# technology transfer, consulting, or bundles with workplace and training support.
NOT_RND_TITLE = re.compile(r"비\s*R&D|마케팅|장비\s*(?:공동\s*)?활용|기술\s*(?:이전|거래)|컨설팅|애로|일터\s*개선|재직자\s*훈련")
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


REGION_NAMES = "|".join(sorted([*LONG_REGIONS, *SHORT_REGIONS], key=len, reverse=True))
# A region inside an organization's name ("울산창조경제혁신센터", "광주테크노파크") says who runs a
# program, not who may apply, so it is skipped.
ORGANIZATION_TAIL = r"[가-힣A-Za-z]*(?:센터|테크노파크|진흥원|공사|재단|대학교?|상공회의소|협회|연구원|산학융합원|TP)"


# Cities and counties (시·군) and the province or metropolitan city each belongs to, so a notice
# that names only "광명시" or "예산군" is read as 경기 or 충남. Names shared by two places
# (고성군: 강원·경남, 광주시: 경기 vs 광주광역시) and districts (구) are left out.
CITY_REGIONS = {
    "경기": "수원시 성남시 의정부시 안양시 부천시 광명시 평택시 동두천시 안산시 고양시 과천시 구리시 남양주시 오산시 "
            "시흥시 군포시 의왕시 하남시 용인시 파주시 이천시 안성시 김포시 화성시 양주시 포천시 여주시 연천군 가평군 양평군",
    "강원": "춘천시 원주시 강릉시 동해시 태백시 속초시 삼척시 홍천군 횡성군 영월군 평창군 정선군 철원군 화천군 양구군 "
            "인제군 양양군",
    "충북": "청주시 충주시 제천시 보은군 옥천군 영동군 증평군 진천군 괴산군 음성군 단양군",
    "충남": "천안시 공주시 보령시 아산시 서산시 논산시 계룡시 당진시 금산군 부여군 서천군 청양군 홍성군 예산군 태안군",
    "전북": "전주시 군산시 익산시 정읍시 남원시 김제시 완주군 진안군 무주군 장수군 임실군 순창군 고창군 부안군",
    "전남": "목포시 여수시 순천시 나주시 광양시 담양군 곡성군 구례군 고흥군 보성군 화순군 장흥군 강진군 해남군 영암군 "
            "무안군 함평군 영광군 장성군 완도군 진도군 신안군",
    "경북": "포항시 경주시 김천시 안동시 구미시 영주시 영천시 상주시 문경시 경산시 의성군 청송군 영양군 영덕군 청도군 "
            "고령군 성주군 칠곡군 예천군 봉화군 울진군 울릉군",
    "경남": "창원시 진주시 통영시 사천시 김해시 밀양시 거제시 양산시 의령군 함안군 창녕군 남해군 하동군 산청군 함양군 "
            "거창군 합천군",
    "제주": "제주시 서귀포시",
    "대구": "군위군 달성군",
    "부산": "기장군",
    "인천": "강화군 옹진군",
    "울산": "울주군",
}
CITY_TO_REGION = {city: region for region, cities in CITY_REGIONS.items() for city in cities.split()}
CITY_NAMES = "|".join(sorted(CITY_TO_REGION, key=len, reverse=True))


def city_regions(text):
    """Provinces of the cities and counties a text names, e.g. "연천군 중소기업" → 경기."""
    return sorted({CITY_TO_REGION[name] for name in re.findall(rf"(?<![가-힣])({CITY_NAMES})", text or "")})


def stated_regions(text):
    """Regions a target line limits applicants to, e.g. "부산 소재", "서울시에 본사", "부산ㆍ울산ㆍ경남 소재"."""
    found = set()
    places = f"{REGION_NAMES}|{CITY_NAMES}"
    # A clause that only prefers a region ("(대전 소재 기업 우대)", "부산 기업 가점"), or a line of
    # preferences ("** 우대조건: …, 충청북도 소재 중소기업"), limits no one.
    lines = [line for line in (text or "").splitlines() if not re.match(r"[\W\d]*(?:우대|가점)", line)]
    text = " ".join(part for part in re.split(r"[,.\n()（）]", "\n".join(lines)) if not re.search(r"우대|가점|우선", part))
    for group in re.findall(rf"((?:{places})(?:\s*[ㆍ·,/]\s*(?:{places}))*)[가-힣\s]{{0,10}}?(?:내\s*)?"
                            r"(?:소재|관내|거주|에\s*(?:본사|소재|사업장|주소|거주)|사업장|본사|지역\s*(?:소재|기업|중소|중기업|소기업))",
                            text or ""):
        for name in re.findall(places, group):
            found.add(CITY_TO_REGION.get(name) or LONG_REGIONS.get(name, name))
    # Tenants of a place's facility ("대전 팁스타운 입주기업"), and "지역 내" next to a named place
    # ("대전 팁스타운 입주기업 및 지역 내 창업기업"), limit applicants to that place too.
    tenants = re.findall(rf"({places})[가-힣A-Za-z0-9\s]{{0,15}}?입주\s*(?:기업|사|업체|예정)", text or "")
    for name in tenants:
        found.add(CITY_TO_REGION.get(name) or LONG_REGIONS.get(name, name))
    return sorted(found)


def content_regions(title, target="", content=""):
    """Regions a notice limits applicants to, read from its own content.

    The title's [지역] label counts first, then the stated target ("부산 소재", "여수시 관내";
    "전국" or "타지역" opens it), then the rest of the notice where a region comes with a cue
    such as 소재·관내·본사. When the notice has content but names no region, the result is []
    (no limit). Only a notice with no content at all is read from region names in its title."""
    prefix = re.match(r"\s*\[([^\]]+)\]", title or "")
    # Only a label of regions ("[부산]", "[전남광주]") counts, not an agency's name ("[제주창조경제혁신센터]").
    if prefix and re.fullmatch(rf"(?:{REGION_NAMES}|광주|[ㆍ·,/\s])+", prefix[1]):
        names = [name for name in SHORT_REGIONS if name in prefix[1]]
        if names:
            return names
    if re.search(r"타\s*(?:지역|시\s*[·ㆍ]?\s*도)|지역\s*(?:제한\s*(?:없|무관)|무관)", target or ""):
        return ["전국"]
    stated = set(stated_regions(target)) | set(city_regions(target))
    if stated:
        return sorted(stated)
    if re.search(r"(?<![가-힣])전국", target or ""):
        return ["전국"]
    stated = stated_regions(content)
    if stated:
        return stated
    if (target or "").strip() or (content or "").strip():
        return []
    named = {LONG_REGIONS.get(name, name) for name in re.findall(rf"({REGION_NAMES})(?!{ORGANIZATION_TAIL})", title or "")}
    named.update(city_regions(title))
    return sorted(named) if 0 < len(named) <= 3 else []


def region_hint(title, target="", tags=(), content=""):
    """Regions for a Bizinfo notice from its own content; nationwide when the content names none.
    Hashtags (which often follow the publisher's location) count only for a notice without content.
    The organizer's location never counts."""
    named = content_regions(title, target, content)
    if named or (target or "").strip() or (content or "").strip():
        return named or ["전국"]
    tagged = {name for tag in tags for name in SHORT_REGIONS if tag in (name, "전남광주") and name in tag}
    return sorted(tagged) if 0 < len(tagged) <= 2 else ["전국"]


PUBLISHED_DATA = "https://hyongmo.github.io/K-OceanX-Portal/data.json"
# Agencies whose own boards are collected directly carry no publisher field; their names.
SOURCE_AGENCIES = {
    "bistep_planning": "부산산업과학혁신원", "kimst_rnd": "해양수산과학기술진흥원", "kimst_notice": "해양수산과학기술진흥원",
    "nipa": "정보통신산업진흥원", "nia_planning": "한국지능정보사회진흥원", "keit_planning": "한국산업기술기획평가원",
    "jcia": "전남정보문화산업진흥원", "iris": "IRIS(범부처통합연구지원시스템)",
}
AGENCY_RENAMES = {"BISTEP": "부산산업과학혁신원", "KIMST 사업공고": "해양수산과학기술진흥원",
                  "KIMST 공지사항": "해양수산과학기술진흥원", "NIPA": "정보통신산업진흥원",
                  "NIA·AI허브": "한국지능정보사회진흥원", "KEIT 과제기획": "한국산업기술기획평가원",
                  "IRIS": "IRIS(범부처통합연구지원시스템)"}
# Main support agencies listed in the guide from the start, so they show even before any of their
# notices is collected. Name → location ("" = nationwide body).
SEED_AGENCIES = {
    **{f"{region}창조경제혁신센터": region for region in (
        "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
        "충북", "충남", "전북", "전남", "경북", "경남", "제주")},
    **{f"{region}테크노파크": region for region in (
        "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
        "충북", "충남", "전북", "전남", "경북", "경남", "제주")},
    "경기대진테크노파크": "경기", "포항테크노파크": "경북",
    "부산산업과학혁신원": "부산",
    "해양수산과학기술진흥원": "", "한국조선해양기자재연구원": "", "한국해양진흥공사": "",
}


def agency_name(name):
    """One name per agency: "(재) 대구창조경제혁신센터 대표이사" and "대구창조경제혁신센터" are the same."""
    name = re.sub(r"^\s*(?:\((?:재|사|주)\)|재단법인|사단법인)\s*", "", clean(name))
    name = re.sub(r"\s*센터장서?$", "센터", name)
    name = re.sub(r"\s*(?:대표이사|이사장|원장|본부장)$", "", name)
    return re.sub(r"센터센터$", "센터", name).strip()


def agency_registry(records, previous, today):
    """Agencies seen in this or any earlier collection, so an agency with no notice today stays listed.
    `previous` is the agency list of the data published last time."""
    registry = {}
    for name, info in (previous or {}).items():
        # Names first stored from a source label ("BISTEP", "KIMST 사업공고") move to the agency's name.
        name = AGENCY_RENAMES.get(name, name)
        if name and (name not in registry or info.get("last_seen", "") > registry[name].get("last_seen", "")):
            registry[name] = dict(info)
    for name, region in SEED_AGENCIES.items():
        registry.setdefault(name, {"region": region, "last_seen": ""})
    seen = {}
    for entry in records:
        if entry.get("agency"):
            seen.setdefault(entry["agency"], set()).add(entry.get("agency_region", ""))
    for name, regions in seen.items():
        # An agency collected again takes the location read this time, so a correction sticks.
        registry[name] = {"region": sorted(regions - {""})[0] if regions - {""} else "", "last_seen": today}
    for name, region in SEED_AGENCIES.items():
        registry[name]["region"] = region  # the reviewed location of a listed agency stands
    return dict(sorted(registry.items()))


def published_agencies():
    """The agency list of the currently published data, or {} when it cannot be read."""
    try:
        with urlopen(Request(PUBLISHED_DATA, headers={"User-Agent": "K-OceanX pilot/0.1"}), timeout=20) as response:
            published = json.loads(response.read(16_000_000))
    except Exception as error:  # the registry then starts from this collection
        print(f"Published agency list unavailable: {type(error).__name__}", file=sys.stderr)
        return {}
    if published.get("agencies"):
        return published["agencies"]
    # Data published before the registry existed: rebuild it from its notices.
    return {agency_name(row.get("publisher", "")): {"region": agency_region(row.get("publisher", "")),
                                                    "last_seen": str(published.get("updated_at", ""))[:10]}
            for row in published.get("records", ())
            if row.get("category") in ("support", "rnd") and row.get("publisher")}


def agency_region(*names):
    """Where an agency sits, read from its own name or its supervising authority (부산광역시, 여수시,
    대구창조경제혁신센터). Used only to group the agency guide, never to judge a notice."""
    for name in names:
        name = name or ""
        for long, short in LONG_REGIONS.items():
            if name.startswith(long):
                return short
        city = city_regions(name)
        if len(city) == 1:
            return city[0]
        found = [short for short in SHORT_REGIONS if re.search(f"(?<![가-힣]){short}", name)]
        if len(found) == 1:
            return found[0]
    return ""


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
    return sorted(stages)


# K-Startup lists the company age buckets a notice accepts, such as "예비창업자,1년미만,3년미만,7년미만".
def kstartup_ages(value):
    """Read K-Startup's company age boxes. "7년미만" means under seven years, so it covers
    every band from opening day up to seven years, not only three to seven."""
    text = re.sub(r"\s+", "", value or "")
    bands = set(bands_under(max(map(int, re.findall(r"(\d{1,2})년미만", text)), default=0)))
    if "예비" in text:
        bands.add("prestartup")
    if "10년이상" in text:
        bands.add("y10_plus")
    return [] if set(AGE_BANDS) <= bands else [band for band in AGE_BANDS if band in bands]


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
            target = clean(item.get("aply_trgt_ctnt"))
            keep, label = judge(title, organizer, clean(item.get("aply_trgt")), target)
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
            regions = kstartup_regions(clean(item.get("supt_regin")))
            # The target text decides first: a region it names ("대전 팁스타운 입주기업 및 지역 내 창업기업")
            # limits the notice even where the official field says 전국; "지역 제한 없음", or 전국
            # among the official regions when the target names none, opens it.
            named = [name for name in content_regions(title, target) if name != "전국"]
            if named:
                regions = named
            elif "전국" in regions or re.search(r"지역\s*(?:제한\s*(?:없|무관)|무관)|(?<![가-힣])전국|타\s*지역", target):
                regions = ["전국"]
            hints["regions"] = regions
            rows.append(record("kstartup", number, title, params(KSTARTUP_PAGE, schM="view", pbancSn=number),
                               "support", opens=opens, deadline=deadline, deadline_time=clock,
                               publisher=organizer, eligibility=shorten(target),
                               target_full=target,
                               content_full=f"{clean(item.get('pbanc_ctnt'))} {clean(item.get('support_ctnt'))}".strip(),
                               agency_region=agency_region(organizer),
                               ages=kstartup_ages(clean(item.get("biz_enyy"))),
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
        is_rnd = bool(planning_type(title) or RND_TITLE.search(title)) and not NOT_RND_TITLE.search(title)
        summary = clean(item.get("bsnsSumryCn"))
        hints = {"regions": region_hint(title, target, tags, summary)}
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
                           target_full=target or clean(item.get("trgetNm")), content_full=summary,
                           agency_region=agency_region(organizer),
                           planning_stage=(planning_type(title) or "application") if is_rnd else "",
                           place=hints["regions"][0] if len(hints["regions"]) == 1 and hints["regions"][0] != "전국" else "",
                           maritime=label == "해양 특화", support_hints=hints))
    tally("bizinfo", dropped, len(rows))
    return rows


# The event schedule keeps two groups: ocean, fisheries, shipping and port events, and AI and data
# events. The sea is read from the title and the event text; AI and data from the title only,
# since event texts mention data and AI in passing ("데이터 기반 마케팅").
# "해운대" (a Busan district, often in addresses) is not shipping; "TV조선", "헬스조선" and "조선이공대"
# are not shipbuilding. "선급" is ship classification (한국선급).
EVENT_MARITIME = re.compile(
    r"해양|해운(?!대)|항만|선박|선급|해수부|(?<!TV)(?<!헬스)조선(?!일보|대학|대|이공)|(?<!농)(?<!축)(?<!림)수산|"
    r"(?<!농)어업|(?<!농)어촌|어항|"
    r"스마트\s*양식|육상\s*양식|양식\s*(?:업|장|어|산업|기업|시설|기술)|해상\s*(?:풍력|물류|운송)|해사|크루즈|원양|"
    r"북극\s*항로|maritime|ocean|shipping|aquaculture|seafood|fisher", re.I)
EVENT_AI = re.compile(r"(?<![A-Za-z])(?:AI|AX)(?![A-Za-z])|인공지능|데이터|생성형|LLM|머신\s*러닝|딥\s*러닝", re.I)
# Paid courses, marketing and sales events, and job fairs are not events for companies to follow,
# whatever their topic (user decision 2026-11-22).
EVENT_COMMERCIAL = re.compile(
    r"마케팅|광고|쇼핑몰|스마트\s*스토어|상세\s*페이지|쇼츠|유튜브|인스타|틱톡|커머스|세일즈|"
    r"강의|클래스|수강|부트\s*캠프|자격증|교육생|국비\s*지원|채용|취업|승무원")


def event_in_scope(title, content=""):
    if EVENT_COMMERCIAL.search(title):
        return False
    return bool(EVENT_MARITIME.search(f"{title} {content}") or EVENT_AI.search(title))


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
        # One event can carry several types joined by "@", e.g. "교육@수출상담회".
        kinds = [part.strip() for part in clean(item.get("eventInfoTyNm")).split("@") if part.strip()]
        content = clean(item.get("nttCn"))
        if "교육" in kinds:
            # Training is a support program, listed with the others under 인재·교육 in the finder.
            keep, reason = training_scope(title)
            if not keep:
                dropped[reason] = dropped.get(reason, 0) + 1
                continue
            regions = [area] if area in REGIONS and area != "해외" else []
            rows.append(record("bizinfo_event", number, title, url, "support",
                               opens=opens, deadline=deadline or start, deadline_time=clock,
                               event_start=start, event_end=end, publisher=organizer,
                               topic=shorten(content, 140), content_full=content,
                               agency_region=agency_region(organizer), maritime=label == "해양 특화",
                               support_hints={"types": ["people"], "methods": ["service"], "regions": regions}))
            continue
        if not event_in_scope(title, content):
            dropped["해양수산·AI·데이터 밖 행사"] = dropped.get("해양수산·AI·데이터 밖 행사", 0) + 1
            continue
        rows.append(record("bizinfo_event", number, title, url,
                           "international" if re.search(r"해외|국외", area) else "domestic",
                           event_start=start, event_end=end, opens=opens, deadline=deadline, deadline_time=clock,
                           event_region=area, publisher=organizer, topic=shorten(content, 140),
                           event_types=kinds, maritime=label == "해양 특화"))
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
                           publisher="한국조선해양기자재연구원",
                           maritime=bool(MARITIME.search(f"{title} {fields.get('eligibility', '')}")), **fields))
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



# ---------- Events from maritime institutions and press reports ----------

EVENT_WORD = re.compile(r"세미나|포럼|컨퍼런스|콘퍼런스|심포지엄|설명회|박람회|전시회|엑스포|EXPO|워크숍|토론회|공청회|"
                        r"전망\s*대회|학술\s*대회|상담회|페어|FAIR|위크|WEEK|라운드\s*테이블|밋업|컨벤션", re.I)
# Titles that report an event already held, or that are about something else than taking part.
EVENT_DONE = re.compile(r"결과|성료|성황|마쳐|마무리|폐막|개최했|열었|열렸|가졌|진행했|참석했|사진|영상|발표\s*자료|"
                        r"취소|연기|수상|시상|선정")
EVENT_LABEL = re.compile(r"(?:일\s*시|일\s*자|일\s*정|기\s*간|개최\s*일(?:자|시)?|행사\s*일(?:자|시)?|교육\s*일(?:자|시)?|날\s*짜)"
                         r"\s*[:：\-]?\s*")
EVENT_VERB = re.compile(r"개최|열린다|연다|열리는|열릴|여는|개막|진행(?:된다|한다|하는|되는|될)|마련한다|선보인다")
# Dates as notices and press reports write them: "2026. 12. 3.", "’26.12.3.", "12월 3일", "12.3.(목)",
# "12.3.~5.", "오는 3일" and, in a sentence about the event, a bare "22일" (not the "16일 밝혔다" of the report).
ANY_DAY = re.compile(
    r"(?P<y>20\d{2})\s*[.\-/년]\s*(?P<m>\d{1,2})\s*[.\-/월]\s*(?P<d>\d{1,2})(?!\d)"
    r"|[’'‘](?P<y2>\d{2})\s*\.\s*(?P<m5>\d{1,2})\s*\.\s*(?P<d5>\d{1,2})(?!\d)"
    r"|(?<![\d.])(?P<m2>\d{1,2})\s*월\s*(?P<d2>\d{1,2})\s*일"
    r"|(?<![\d.])(?P<m3>\d{1,2})\s*\.\s*(?P<d3>\d{1,2})\s*\.?(?=\s*[(~∼～])"
    r"|오는\s*(?P<d4>\d{1,2})\s*일"
    r"|(?<![\d.월\-~])(?P<d6>\d{1,2})\s*일(?!\s*(?:밝혔|발표|전했|알렸|말했|기준|간|이내|부로))")
SPAN_DAYS = re.compile(r"\s*일?\s*(?:\([^)]{0,12}\))?\s*(?:부터\s*)?(이틀|사흘|나흘|닷새|\d{1,2}일)\s*간")
SPAN_COUNT = {"이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5}
RANGE_TAIL = re.compile(r"\.?\s*일?\s*(?:\([^)]{0,12}\))?\s*(?:\d{1,2}:\d{2}\s*)?(?:~|∼|～|-|–|부터)\s*")
DAY_ONLY = re.compile(r"(?<![\d.])(\d{1,2})\s*일(?!\s*간)|(?<![\d.])(\d{1,2})\s*\.?\s*(?=\()|(?<![\d.])(\d{1,2})\.(?!\d)")


# Sentences end at "…다." or a line break; a full stop alone may belong to a date ("11.3.~5.").
SENTENCE_END = re.compile(r"(?<=다)\.\s*|\n")


def _day(year, month, day):
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _read_day(match, reference):
    """The date a match names, read against the day the text was written."""
    if match["y"]:
        return _day(match["y"], match["m"], match["d"])
    if match["y2"]:
        return _day(2000 + int(match["y2"]), match["m5"], match["d5"])
    if match["d6"]:
        # A bare day is in the month of writing; one already past reports a past event.
        return _day(reference.year, reference.month, match["d6"])
    if match["d4"]:
        day = int(match["d4"])
        month, year = reference.month, reference.year
        if day < reference.day:
            month, year = (1, year + 1) if month == 12 else (month + 1, year)
        return _day(year, month, day)
    month, day = (match["m2"], match["d2"]) if match["m2"] else (match["m3"], match["d3"])
    found = _day(reference.year, month, day)
    # A month and day without a year that fall well before the text was written belong to next year.
    if found and found < reference - timedelta(days=60):
        found = _day(reference.year + 1, month, day)
    return found


def _span(text, match, reference):
    start = _read_day(match, reference)
    if not start:
        return None, None
    tail = RANGE_TAIL.match(text, match.end())
    end = None
    length = SPAN_DAYS.match(text, match.end())
    if length:
        count = SPAN_COUNT.get(length[1]) or int(length[1][:-1])
        end = start + timedelta(days=count - 1)
    elif tail:
        following = ANY_DAY.match(text, tail.end())
        if following:
            end = _read_day(following, start)
        else:
            day = DAY_ONLY.match(text, tail.end())
            if day:
                end = _day(start.year, start.month, day[1] or day[2] or day[3])
    if end and not (start <= end <= start + timedelta(days=60)):
        end = None
    return start, end


def event_when(text, reference):
    """(start, end) of the event a notice or report describes, as ISO dates; ("", "") when unclear.

    A labelled line ("일시: 2026. 12. 3.(목)") decides first; otherwise the first sentence that says
    the event is held ("오는 3일 부산에서 개최한다") does. Dates elsewhere in the text are not used."""
    text = text or ""
    for label in EVENT_LABEL.finditer(text):
        match = ANY_DAY.match(text, label.end()) or ANY_DAY.search(text[:label.end() + 25], label.end())
        if match:
            start, end = _span(text, match, reference)
            if start:
                return start.isoformat(), end.isoformat() if end else ""
    for sentence in re.split(SENTENCE_END, text):
        if not EVENT_VERB.search(sentence):
            continue
        match = ANY_DAY.search(sentence)
        if match:
            start, end = _span(sentence, match, reference)
            if start:
                return start.isoformat(), end.isoformat() if end else ""
    return "", ""


def upcoming(start, end, today, days=300):
    """True for an event that has not ended and starts within the coming days (ten months for dates
    read from text; schedules that state their dates may look further)."""
    return bool(start) and (end or start) >= today and start <= (
        date.fromisoformat(today) + timedelta(days=days)).isoformat()


def kmi_events(get):
    # The KMI seminar board lists each seminar with the day it is held.
    url = "https://www.kmi.re.kr/web/board/list.do?rbsIdx=165"
    today = kst_today()
    links = require(page(get, "kmi_events", url).select('a[href*="rbsIdx=165"][href*="idx="]'))
    rows = []
    for link in links:
        title, held = link.select_one(".tit"), link.select_one(".data")
        start = iso(held.get_text(strip=True)) if held else ""
        if not title or not upcoming(start, "", today, days=400):
            continue
        rows.append(record("kmi_event", parse_qs(urlsplit(link["href"]).query)["idx"][0],
                           title.get_text(" ", strip=True), urljoin(url, link["href"]), "domestic",
                           event_start=start, publisher="한국해양수산개발원", maritime=True))
    return rows


def bexco_events(get):
    # BEXCO, Busan's exhibition centre, lists coming events with their dates; only ocean,
    # fisheries and AI or data events are kept.
    base = "https://www.bexco.co.kr/kor/CMS/EventScheduleMgr/list.do"
    today = kst_today()
    rows, listed = [], 0
    for number in range(1, 9):
        links = page(get, "bexco", params(base, mCode="MN214", page=number)).select(
            'a[href*="EventScheduleMgr/view.do"]')
        if not links:
            break
        for link in links:
            subject, when = link.select_one(".subject"), link.select_one(".date")
            if not subject or not when:
                continue
            listed += 1
            title = subject.get_text(" ", strip=True)
            dates = re.findall(DATE, when.get_text(" ", strip=True))
            start, end = (iso(dates[0]), iso(dates[-1])) if dates else ("", "")
            kind = link.select_one(".eventIcon")
            kind = kind.get_text(strip=True) if kind else ""
            # Rented meeting rooms (courses, dinners) are not public events unless named as one.
            if kind == "공연" or (kind != "전시" and not EVENT_WORD.search(title)):
                continue
            if not upcoming(start, end, today, days=400) or not event_in_scope(title):
                continue
            place = link.select_one(".place")
            number_id = parse_qs(urlsplit(link["href"]).query).get("event_seq", [""])[0]
            rows.append(record("bexco", number_id, title, urljoin(base, link["href"]), "domestic",
                               event_start=start, event_end=end if end != start else "", event_region="부산",
                               place=place.get_text(" ", strip=True) if place else "BEXCO",
                               publisher="BEXCO", event_types=[kind] if kind else []))
    if not listed:
        raise ValueError("BEXCO schedule has no recognizable events")
    return rows


# Event pages of maritime institutions, associations, societies and venues, from the survey of
# 2026-11-22. Three kinds:
#  - board: a notice list; each notice whose title names an event is opened and its "일시" line
#    (or the sentence that says it is held) gives the dates.
#  - page: the page of one recurring event (a forum, an exhibition), read for its next dates.
#  - the schedules of COEX, KINTEX and the 해양생물자원관 list each event with its dates (own readers).
# A site that does not answer leaves only its own events out.
BOARDS = (
    dict(key="kriso", agency="선박해양플랜트연구소", url="https://www.kriso.re.kr/menu.es?mid=a10401000000",
         link=r"board\.es\?mid=a10401000000&bid=0010&act=view&list_no=(\d+)",
         detail="https://www.kriso.re.kr/board.es?mid=a10401000000&bid=0010&act=view&list_no={}"),
    dict(key="kopri", agency="극지연구소", url="https://www.kopri.re.kr/kopri/html/comm/0401.html",
         link=r"\?mode=V&no=([0-9a-f]{32})", detail="https://www.kopri.re.kr/kopri/html/comm/0401.html?mode=V&no={}"),
    dict(key="busan_mof", agency="부산지방해양수산청", url="https://busan.mof.go.kr/ko/board.do?menuIdx=4480",
         link=r"board\.do\?menuIdx=4480&bbsIdx=(\d+)", detail="https://busan.mof.go.kr/ko/board.do?menuIdx=4480&bbsIdx={}"),
    dict(key="busan_mof_notice", agency="부산지방해양수산청", url="https://busan.mof.go.kr/ko/board.do?menuIdx=4468",
         link=r"board\.do\?menuIdx=4468&bbsIdx=(\d+)", detail="https://busan.mof.go.kr/ko/board.do?menuIdx=4468&bbsIdx={}"),
    dict(key="fira", agency="한국수산자원공단", url="https://www.fira.or.kr/newfira/web/news/news01_01.jsp",
         link=r"mode=view&article_no=(\d+)",
         detail="https://www.fira.or.kr/newfira/web/news/news01_01.jsp?mode=view&article_no={}"),
    dict(key="kr", agency="한국선급", url="https://www.krs.co.kr/kor/BBS/BF_Main.aspx?MRID=913&URID=909",
         link=r"frmView\('([A-Za-z0-9+/=]+)'", every_title=True, overseas=True,
         detail="https://www.krs.co.kr/kor/BBS/BF_View.aspx?PMODE=E&MRID=913&URID=909&BF_ROWID={}"),
    dict(key="kims", agency="한국해양전략연구소", url="https://kims.or.kr/notice/",
         link=r"kims\.or\.kr/news/notice/([\w%-]+)/", detail="https://kims.or.kr/news/notice/{}/"),
    dict(key="ocean_foundation", agency="한국해양재단", url="https://ocean.or.kr/brd/board/2219/L/menu/586",
         link=r"bbIdx=(\d+)", detail="https://ocean.or.kr/brd/board/2219/L/menu/586?brdType=R&bbIdx={}"),
    dict(key="seapower", agency="대한민국해양연맹", url="https://www.seapower.or.kr/notice/category/2242",
         link=r"seapower\.or\.kr/notice/(\d+)", detail="https://seapower.or.kr/notice/{}"),
    dict(key="kinpr", agency="한국항해항만학회", url="http://www.kinpr.or.kr/bbs/board.php?bo_table=noticee",
         link=r"bo_table=noticee&(?:amp;)?wr_id=(\d+)", detail="http://www.kinpr.or.kr/bbs/board.php?bo_table=noticee&wr_id={}"),
    dict(key="snak", agency="대한조선학회", url="https://www.snak.or.kr/05_board/board01.html",
         link=r"Item=board2&(?:amp;)?mode=view&(?:amp;)?s_t=1&(?:amp;)?No=(\d+)",
         detail="https://www.snak.or.kr/05_board/board01.html?Item=board2&mode=view&s_t=1&No={}"),
    dict(key="ksoe", agency="한국해양공학회", url="https://www.ksoe.or.kr/bbs/board.php?bo_table=conference",
         link=r"bo_table=conference&(?:amp;)?wr_id=(\d+)", every_title=True,
         detail="https://www.ksoe.or.kr/bbs/board.php?bo_table=conference&wr_id={}"),
    dict(key="kosfas", agency="한국수산과학회", url="https://www.kosfas.or.kr/05/01.php",
         link=r"05/01\.php\?[^\"']*?(?:idx|no|uid)=(\d+)", detail="https://www.kosfas.or.kr/05/01.php?mode=view&idx={}"),
    dict(key="btp", agency="부산테크노파크", url="https://www.btp.or.kr/kor/CMS/Board/Board.do?mCode=MN018",
         link=r"mgr_seq=35&(?:amp;)?board_seq=(\d+)",
         detail="https://www.btp.or.kr/kor/CMS/Board/Board.do?mCode=MN018&mode=view&mgr_seq=35&board_seq={}"),
)
EVENT_PAGES = (
    dict(key="wof", agency="세계해양포럼(한국해양산업협회)", url="http://wof.kr/", name="세계해양포럼", dated_heading=True),
    dict(key="oceaninnoweek", agency="해양수산과학기술진흥원", url="https://oceaninnoweek.com/about",
         name="해양수산과학기술주간(OCEAN INNO WEEK)"),
    dict(key="offshorekorea", agency="국제해양플랜트전 사무국", url="http://www.offshorekorea.org/kor/main/main.html",
         name="국제해양플랜트전(OFFSHORE KOREA)"),
    dict(key="upipsc", agency="울산항만공사", url="https://www.upipsc.com", name="울산항 안전 콘퍼런스"),
    dict(key="ocean_policy_forum", agency="한국해양재단", url="https://ocean.or.kr/cms/content/view/566", name="해양정책포럼"),
)
POSTED = re.compile(r"20\d{2}[./-]\d{1,2}[./-]\d{1,2}")
# A labelled place line ("■ 장소 : 부산 벡스코", "지역\n태국 방콕"), read only at the start of a line.
REGION_WORD = re.compile(r"(?m)^[\s■□○●◦·*\-–]*(?:지역|장소|개최\s*장소|개최지|행사장)\s*[:：]?\s*\n?([^\n]{2,40})")
DOMESTIC_PLACE = re.compile(r"국내|온라인|벡스코|BEXCO|코엑스|COEX|킨텍스|KINTEX|BPEX|엑스코|EXCO|송도|국회|대한민국|한국", re.I)


def notice_text(document):
    for removed in document(["script", "style"]):
        removed.decompose()
    body = next((document.select_one(selector) for selector in (
        "#dic_area", "#newsct_article", "#article-view-content-div", "#real_contents", "#bo_v_con", "article",
        ".board_view", ".bbs_view", ".view_cont", ".view", "#contents", "#content") if document.select_one(selector)),
        document.body or document)
    return body.get_text("\n", strip=True)


def event_row(source, key, title, url, agency, start, end, text="", published="", overseas=False):
    """An event record. Where a list holds events abroad too (overseas=True), one whose place line
    names no Korean place goes to the overseas list."""
    place = REGION_WORD.search(text or "")
    place = clean(place[1]) if place else ""
    abroad = overseas and bool(place) and not (re.search(REGION_NAMES + r"|" + CITY_NAMES, place) or
                                               DOMESTIC_PLACE.search(place))
    return record(source, key, title, url, "international" if abroad else "domestic", event_start=start,
                  event_end=end if end != start else "", publisher=agency, published=published,
                  event_region=shorten(place, 30) if abroad else event_place(f"{place}에서") or "",
                  content_full=(text or "")[:4000])


def board_events(get, board, today):
    listing = page(get, board["key"], board["url"])
    rows, seen = [], set()
    for anchor in listing.select("a"):
        match = re.search(board["link"], f'{anchor.get("href", "")} {anchor.get("onclick", "")}')
        title = " ".join(anchor.get_text(" ", strip=True).split())
        if not match or match[1] in seen or len(title) < 4:
            continue
        # Exhibition and conference lists name events by their own names ("SMM 2026"); other boards
        # are read only where the title says an event is held.
        if not board.get("every_title") and (not EVENT_WORD.search(title) or EVENT_DONE.search(title)):
            continue
        seen.add(match[1])
        row = anchor.find_parent(["tr", "li"]) or anchor
        posted = POSTED.search(row.get_text(" ", strip=True))
        posted = date.fromisoformat("-".join(f"{int(part):02}" for part in re.split(r"[./-]", posted[0]))) \
            if posted else date.fromisoformat(today)
        if (date.fromisoformat(today) - posted).days > 120:
            continue
        address = board["detail"].format(match[1])
        try:
            text = notice_text(page(get, board["key"], address))
        except PLANNING_HTTP:
            continue
        start, end = event_when(text, posted)
        if not upcoming(start, end, today) or not event_in_scope(title, text):
            continue
        title = re.split(r"\s*[•·]\s*(?:행사명|일자|장소)\s*:", title)[0]
        rows.append(event_row("institution_event", f'{board["key"]}-{match[1][:40]}', title, address,
                              board["agency"], start, end, text, posted.isoformat(),
                              overseas=board.get("overseas", False)))
    return rows


def page_event(get, event, today):
    """The next edition of a recurring event, from its own page: its name and the first dates on it."""
    document = page(get, event["key"], event["url"])
    heading = document.title.get_text(" ", strip=True) if document.title else ""
    text = notice_text(document)
    reference = date.fromisoformat(today)
    start, end = event_when(text, reference)
    edition_year = re.search(r"20\d{2}", heading)
    if not start and event.get("dated_heading") and edition_year:
        # Some event sites show the dates of the edition named in their heading with no label.
        for match in ANY_DAY.finditer(text):
            if match["y"] == edition_year[0]:
                first, last = _span(text, match, reference)
                if first:
                    start, end = first.isoformat(), last.isoformat() if last else ""
                    break
    if not upcoming(start, end, today, days=400):
        return []
    edition = next((part.strip() for part in re.split(r"\s*[|·\-–]\s*", heading)
                    if event["name"][:4] in part and start[:4] in part), "")
    title = clean(edition) if edition else f'{start[:4]} {event["name"]}'
    return [event_row("institution_event", f'{event["key"]}-{start[:4]}', title, event["url"], event["agency"],
                      start, end, text)]


def listing_pages(get, source, url, name, count):
    """The first pages of a list; a page after the first that does not answer ends the list."""
    for number in range(1, count + 1):
        try:
            yield page(get, source, params(url, **{name: number}))
        except PLANNING_HTTP:
            if number == 1:
                raise
            return


def coex_events(get, today):
    # COEX lists every coming event with its dates; only ocean, fisheries and AI or data events stay.
    base = "https://www.coex.co.kr/event/full-schedules/"
    rows = []
    for document in listing_pages(get, "coex", base, "var_page", 8):
        cards = document.select('a[href*="/exhibitions/"]')
        if not cards:
            break
        for card in cards:
            text = " ".join(card.get_text(" ", strip=True).split())
            dates = re.findall(r"20\d{2}\.\d{2}\.\d{2}", text)
            if not dates:
                continue
            title = re.sub(r"^(?:Exhibition|Convention|Pop-up/Event|Event|Performance)\s+", "", text.split(dates[0])[0]).strip()
            start, end = iso(dates[0].replace(".", "-")), iso(dates[-1].replace(".", "-"))
            if not title or not upcoming(start, end, today, days=400) or not event_in_scope(title):
                continue
            rows.append(event_row("institution_event", f"coex-{re.sub(r'[^0-9a-z]', '', card['href'].lower())[-40:]}",
                                  title, urljoin(base, card["href"]), "COEX", start, end, "장소: 서울 COEX"))
    return list({row["id"]: row for row in rows}.values())


def kintex_events(get, today):
    # KINTEX lists its coming exhibitions, conferences and other events with their dates.
    url = "https://www.kintex.com/web/ko/event/list.do"
    rows = []
    cards = [card for document in listing_pages(get, "kintex", url, "pageIndex", 6)
             for card in document.select("a.btn-square-item")]
    for card in cards:
        when = card.select_one(".item-date")
        name = card.select_one(".item-subject")
        number = re.search(r"fnView\([^,]*,\s*(\d+)", card.get("href", ""))
        dates = re.findall(r"20\d{2}\.\d{2}\.\d{2}", when.get_text(" ", strip=True)) if when else []
        if not name or not dates or not number:
            continue
        title = " ".join(name.get_text(" ", strip=True).split())
        start, end = iso(dates[0].replace(".", "-")), iso(dates[-1].replace(".", "-"))
        if not upcoming(start, end, today, days=400) or not event_in_scope(title):
            continue
        rows.append(event_row("institution_event", f"kintex-{number[1]}", title, url, "KINTEX", start, end,
                              "장소: 경기 고양 KINTEX"))
    return list({row["id"]: row for row in rows}.values())


def mabik_events(get, today):
    # The 해양생물자원관 lists its events with dates and audiences; family and children's programmes
    # are not company events and stay out.
    url = "https://www.mabik.re.kr/prog/clturEvnt/kor/sub01_08/list.do"
    rows = []
    for item in page(get, "mabik", url).select("li"):
        text = " ".join(item.get_text(" ", strip=True).split())
        held = re.search(r"행사일시\s*(20\d{2}-\d{2}-\d{2})\s*~\s*(20\d{2}-\d{2}-\d{2})", text)
        if not held or re.search(r"대상\s*\S*(?:초등|가족|어린이|유아|청소년|전\s*연령)", text):
            continue
        link = item.find("a", href=True)
        title = re.sub(r"^.*?(?:오프라인|온라인)\s*행사\s*", "", text.split("행사일시")[0]).strip()
        if not link or not upcoming(held[1], held[2], today) or not event_in_scope(title, text):
            continue
        rows.append(event_row("institution_event", f"mabik-{re.sub(r'\W', '', title)[:30]}-{held[1]}", title,
                              urljoin(url, link["href"]), "국립해양생물자원관", held[1], held[2], text))
    return rows


def institution_events(get):
    today = kst_today()
    rows, failed = [], []
    readers = [(board["key"], lambda board=board: board_events(get, board, today)) for board in BOARDS]
    readers += [(event["key"], lambda event=event: page_event(get, event, today)) for event in EVENT_PAGES]
    readers += [("coex", lambda: coex_events(get, today)), ("kintex", lambda: kintex_events(get, today)),
                ("mabik", lambda: mabik_events(get, today))]
    counts = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [(key, pool.submit(read)) for key, read in readers]
        for key, job in jobs:
            try:
                found = job.result()
            except Exception:  # noqa: BLE001 - one site's failure leaves only its own events out
                failed.append(key)
                continue
            counts[key] = len(found)
            rows.extend(found)
    print("institution events: " + ", ".join(f"{key} {count}" for key, count in counts.items() if count) +
          (f"; unreachable {', '.join(failed)}" if failed else ""), flush=True)
    if len(failed) == len(readers):
        raise ValueError("No institution event page could be read")
    return list({row["id"]: row for row in rows}.values())


# Institutions whose events reach the press: the maritime institutions and associations in the
# survey of 2026-11-22 (ministry and its agencies, public bodies, research institutes, shipping,
# port, shipbuilding and fisheries associations, societies, universities, regional support centres,
# exhibition organisers), less those that rarely hold events for companies. Their own boards are often
# closed to collection from abroad, so press reports naming them are searched instead.
NEWS_INSTITUTIONS = (
    "해양수산부", "국립수산물품질관리원", "국립해양조사원", "국립해양측위정보원", "해양수산인재개발원", "부산지방해양수산청", "인천지방해양수산청", "여수지방해양수산청", "마산지방해양수산청",
    "동해지방해양수산청", "군산지방해양수산청", "목포지방해양수산청", "포항지방해양수산청", "평택지방해양수산청", "울산지방해양수산청", "대산지방해양수산청", "중앙해양안전심판원",
    "국립수산과학원", "해양환경공단", "한국해양교통안전공단", "국립해양박물관", "국립해양과학관", "해양수산과학기술진흥원", "한국해양과학기술원", "국립해양생물자원관", "한국해양조사협회",
    "한국수산자원공단", "한국어촌어항공단", "한국해양진흥공사", "한국해양수산연수원", "부산항만공사", "인천항만공사", "여수광양항만공사", "울산항만공사", "한국항로표지기술원",
    "한국해양수산개발원", "선박해양플랜트연구소", "극지연구소", "한국조선해양기자재연구원", "한국선급", "한국해사문제연구소", "한국해양전략연구소", "한국해사위험물검사원", "한국해양재단",
    "해양과학기술 산학연 협력센터", "한국해운협회", "대한민국해양연맹", "한국항만물류협회", "목포해양대학교", "한국도선사협회", "한국선박관리산업협회", "한국선주상호보험조합",
    "한국예선업협동조합", "한국해기사협회", "한국해양대학교", "한국해운조합", "한국해운세제학회", "한국해운중개업협회", "부산항만산업협회", "한국검수검정협회", "한국국제물류협회",
    "한국국제해운대리점협회", "한국선원복지고용센터", "한국항만협회", "한국항해항만학회", "한국해법학회", "한국해사법학회", "한국해사재단", "한국해사포럼", "한국해양교육연구회",
    "한국해양구조협회", "한국해양수산기업협회", "한국해운대리점협회", "한국해운물류학회", "해양환경안전학회", "수협중앙회", "부산공동어시장", "한국수산업경영인중앙연합회", "한국수산회",
    "한국원양산업협회", "한국수산무역협회", "한국수산종자산업협회", "한국농수산식품유통공사", "한국수산기자재협회", "한국수산과학총연합회", "한국수산물유통가공협회", "전국근해어업인연합회",
    "한국김산업연합회", "한국수산경영학회", "한국수산과학회", "한국수산해양기술학회", "한국어류학회", "한국어병학회", "한국패류학회", "부경대학교", "군산대학교", "제주대학교",
    "한국농수산대학교", "한국조선해양플랜트협회", "한국조선해양기자재공업협동조합", "중소조선연구원", "한국해양산업협회", "한국해양과학기술협의회", "대한조선학회", "한국해안·해양공학회",
    "한국해양공학회", "한국해양학회", "한국해양환경·에너지학회", "한국항만경제학회", "경상국립대학교 해양과학대학", "전남대학교 수산해양대학", "한국수상레저안전협회", "한국해양레저산업협회",
    "한국풍력산업협회", "부산테크노파크", "제주테크노파크", "환동해산업연구원", "강릉과학산업진흥원", "전남 해양수산 창업투자지원센터", "충남테크노파크", "전북바이오융합산업진흥원",
    "경남테크노파크", "경남항노화연구원", "BEXCO", "부산항국제전시컨벤션센터", "COEX", "KINTEX", "코마린", "국제해양플랜트전", "부산국제수산엑스포", "경기국제보트쇼",
    "해양수산과학기술주간", "세계해양포럼", "해양산업통합클러스터", "부산수산자원연구소", "인천수산자원연구소", "경기도해양수산자원연구소", "강원특별자치도 수산자원연구원", "충남수산자원연구소",
    "전북수산기술연구소", "전남해양수산과학원", "경북어업기술원", "경북수산자원연구원", "경남수산안전기술원", "울산수산자원연구소", "제주해양수산연구원", "코리아씨푸드쇼", "부산국제보트쇼",
    "인천국제해양포럼",
    # Regional economic and industry agencies that hold company forums with ocean sessions.
    "부산경제진흥원", "부산정보산업진흥원", "부산상공회의소", "부산산업과학혁신원", "울산경제일자리진흥원",
    "울산정보산업진흥원", "울산테크노파크", "경남투자경제진흥원", "전남정보문화산업진흥원", "전남테크노파크",
    "포항테크노파크", "인천테크노파크",
)
EVENT_TOPICS = (
    "해양수산 전망대회", "해양수산 세미나 개최", "해양수산 포럼 개최", "해운 세미나 개최", "해운 포럼 개최",
    "항만 세미나 개최", "항만 포럼 개최", "조선해양 포럼 개최", "조선해양 세미나 개최", "수산 포럼 개최",
    "수산 세미나 개최", "해양 심포지엄 개최", "해양 컨퍼런스 개최", "해양산업 박람회", "해양 AI 세미나",
    "해양 데이터 포럼", "스마트항만 세미나", "자율운항선박 포럼", "스마트양식 세미나", "조선 AI 세미나",
)
QUOTED = re.compile(r"[‘'“\"「『<〈《]([^’'”\"」』>〉》]{4,60})[’'”\"」』>〉》]")


def event_name(title):
    """The event's own name when a headline quotes it ("…, '2027 해양수산 전망대회' 개최")."""
    for name in QUOTED.findall(title):
        if EVENT_WORD.search(name):
            return name.strip()
    return title


def event_place(sentence):
    """The region of the venue named right before "에서" ("부산 벡스코에서"); "" when none is named."""
    for venue in re.finditer(r"에서", sentence):
        window = sentence[max(0, venue.start() - 25):venue.start()]
        found = [(m.start(), CITY_TO_REGION[m[0]]) for m in re.finditer(CITY_NAMES, window)]
        # A region name inside a word is not that region ("해운대구" is not 대구).
        found += [(m.start(), LONG_REGIONS.get(m[1], m[1]))
                  for m in re.finditer(rf"(?<![가-힣])({REGION_NAMES})", window)]
        if found:
            return max(found)[1]
    return ""


def naver_events(get):
    headers = naver_headers()
    if not headers:
        print("Naver keys missing; press reports skipped", file=sys.stderr)
        return []
    today = kst_today()
    candidates = {}
    queries = (*[f"{name} 개최" for name in NEWS_INSTITUTIONS], *EVENT_TOPICS)
    answered = 0
    for query in queries:
        url = params("https://openapi.naver.com/v1/search/news.json", query=query, display=30, sort="date")
        try:
            items = json.loads(get("naver", url, headers))["items"]
        except (OSError, ValueError, KeyError):
            continue
        answered += 1
        for item in items:
            title, summary = clean(item.get("title")), clean(item.get("description"))
            if not EVENT_WORD.search(title) or EVENT_DONE.search(title):
                continue
            posted = parsedate_to_datetime(item["pubDate"]).date()
            if (date.fromisoformat(today) - posted).days > 45 or not event_in_scope(title, summary):
                continue
            # The Naver copy is preferred: it is always https and keeps one layout.
            link = next((value for value in (item.get("link"), item.get("originallink"))
                         if str(value or "").startswith("https://")), "")
            if link:
                candidates.setdefault(link, (title, summary, posted))
    if not answered:
        raise ValueError("Naver News answered none of the event searches")
    rows = {}
    for link, (title, summary, posted) in list(candidates.items())[:200]:
        text = f"{title}\n{summary}"
        try:
            text += "\n" + notice_text(page(get, "naver_article", link))
        except PLANNING_HTTP:
            pass
        start, end = event_when(text, posted)
        if not upcoming(start, end, today):
            continue
        name = event_name(title)
        # One event reported by several papers is listed once.
        key = re.sub(r"\W|20\d{2}년?|제\s*\d+\s*회", "", name)[:40] + start
        if key in rows:
            continue
        sentence = next((part for part in re.split(SENTENCE_END, text)
                         if EVENT_VERB.search(part) and ANY_DAY.search(part)), "")
        rows[key] = record("naver_event", hashlib.sha1(key.encode()).hexdigest()[:12], name, link, "domestic",
                           event_start=start, event_end=end, published=posted.isoformat(),
                           event_region=event_place(sentence), topic=shorten(summary, 140),
                           content_full=text[:4000])
    print(f"press reports: {len(candidates)} candidates, {len(rows)} events", flush=True)
    return list(rows.values())


# ---------- Events from Event-us, the booking site many regional bodies use ----------
# Regional agencies often announce an event only on its Event-us booking page, with the programme
# as a poster picture (제2회 부산 기업 혁신 포럼, 2026-11-23: "조선해양 산업의 AX 전략" only in the poster).
# From Event-us only ocean and fisheries events are taken; its AI-only events are mostly paid courses
# and marketing (user decision 2026-11-22). Paid events are left out.
EVENTUS_API = "https://api.event-us.kr/api/v1/engine/search"
EVENTUS_TERMS = ("해양", "해운", "항만", "조선", "선박", "수산", "어업", "양식", "해사", "선급", "오션", "마리타임")
# Regions on the coast, where a forum may hide its ocean programme in the poster.
EVENTUS_COAST = ("부산/울산/경남", "전라/광주", "제주")
EVENTUS_TYPES = {"강연/세미나", "학술회의", "정부회의", "기업회의", "컨벤션", "박람회/페어", "데모데이",
                 "모임/커뮤니티", "워크샵/클리닉"}
POSTER_WORD = re.compile(r"포럼|세미나|컨퍼런스|콘퍼런스|심포지엄|설명회|워크숍|박람회|엑스포|EXPO|데모데이|"
                         r"밋업|토론회|학술|비전|전략", re.I)


def eventus_search(get, query, filters):
    rows, number = [], 1
    while number <= 10:
        body = json.dumps({"query": query, "page": {"current": number, "size": 100},
                           "filters": {"all": filters}}).encode()
        found = json.loads(get("eventus", EVENTUS_API, {"Content-Type": "application/json"}, body))
        rows += [{key: (value.get("raw") if isinstance(value, dict) else value) for key, value in row.items()}
                 for row in found["results"]]
        if number >= found["meta"]["page"]["total_pages"]:
            break
        number += 1
    return rows


def poster_text(get, event):
    """Text read from the pictures of an Event-us page (the programme is often a poster).
    Empty when the reading tool (tesseract with Korean) is not installed."""
    if not shutil.which("tesseract"):
        return ""
    html = get("eventus_page", event["url"]).decode("utf-8", "replace")
    pictures = sorted(set(re.findall(
        r'https://eventusstorage\.blob\.core\.windows\.net/evs/[^"\'\s)\\]+?\.(?:png|jpe?g|webp)', html, re.I)))
    pictures = [url for url in pictures if f'/{event["subdomain"]}/' in url and
                not re.search(r"logo|/Cover/|PlatForm", url, re.I)][:4]
    text = []
    for url in pictures:
        picture = get("eventus_poster", url)
        result = subprocess.run(["tesseract", "stdin", "stdout", "-l", "kor+eng", "--psm", "3"],
                                input=picture, capture_output=True, timeout=90)
        text.append(result.stdout.decode("utf-8", "replace"))
    # The reader takes "AI" for "Al".
    return re.sub(r"(?<![A-Za-z])Al(?![A-Za-z])", "AI", "\n".join(text))


def address_region(address):
    """The region an address starts with ("부산 해운대구 …" → 부산)."""
    found = re.match(rf"\s*({REGION_NAMES})(?![가-힣])", address or "")
    return LONG_REGIONS.get(found[1], found[1]) if found else ""


def eventus_events(get):
    today = kst_today()
    now = f"{today}T00:00:00Z"
    later = (date.fromisoformat(today) + timedelta(days=300)).isoformat() + "T23:59:59Z"
    base = [{"start_date": {"from": f"{(date.fromisoformat(today) - timedelta(days=30)).isoformat()}T00:00:00Z",
                            "to": later}}, {"close_date": {"from": now}}]
    found, failed = {}, 0
    searches = [(term, base) for term in EVENTUS_TERMS] + [("", base + [{"area": list(EVENTUS_COAST)}])]
    for query, filters in searches:
        try:
            for row in eventus_search(get, query, filters):
                found[row["id"]] = row
        except (OSError, ValueError, KeyError):
            failed += 1
    if failed == len(searches):
        raise ValueError("Event-us answered none of the searches")
    events, posters = [], []
    for row in found.values():
        title = clean(row.get("title"))
        start, end = str(row.get("start_date") or "")[:19], str(row.get("close_date") or "")[:19]
        if not title or row.get("state") != "Start" or row.get("disclosure_status") != "open" or \
                row.get("is_ignore") == "true" or row.get("event_type") not in EVENTUS_TYPES:
            continue
        if (row.get("min_money") or 0) > 0 or row.get("payway") == "true" or EVENT_COMMERCIAL.search(title):
            continue
        start, end = (datetime.fromisoformat(value + "+00:00").astimezone(timezone(timedelta(hours=9))).date().isoformat()
                      if value else "" for value in (start, end))
        if not upcoming(start, end, today):
            continue
        event = {**row, "title": title, "start": start, "end": end,
                 "url": f'https://event-us.kr/{row["subdomain"]}/event/{row["id"]}',
                 "text": clean(row.get("description") or "")}
        if EVENT_MARITIME.search(f'{title} {event["text"]}'):
            events.append(event)
        elif row.get("area") in EVENTUS_COAST and POSTER_WORD.search(title):
            posters.append(event)

    def read(event):
        try:
            return event, poster_text(get, event)
        except (OSError, ValueError, subprocess.SubprocessError):
            return event, ""
    with ThreadPoolExecutor(max_workers=4) as pool:
        for event, text in pool.map(read, posters):
            if EVENT_MARITIME.search(text):
                events.append({**event, "text": f'{event["text"]}\n{text}'.strip()})
    rows = []
    for event in events:
        address = clean(event.get("full_address") or event.get("address") or event.get("area_detail") or "")
        rows.append(record("eventus", event["id"], event["title"], event["url"], "domestic",
                           event_start=event["start"], event_end=event["end"] if event["end"] != event["start"] else "",
                           publisher=clean(event.get("app_title") or ""), place=clean(event.get("place") or ""),
                           event_region=address_region(address),
                           event_types=[event["event_type"]], content_full=event["text"][:4000]))
    print(f"Event-us: {len(found)} listed, {len(posters)} posters read, {len(rows)} events", flush=True)
    return rows


def drop_event_duplicates(records):
    """One event listed by several sources is kept once, from the source that states its dates."""
    rank = {"kmi_event": 0, "bexco": 1, "institution_event": 2, "eventus": 3, "naver_event": 9}
    kept = set()
    for key, entry in sorted(((key, entry) for key, entry in records.items()
                              if entry["category"] in ("domestic", "international") and entry.get("event_start")),
                             key=lambda pair: rank.get(pair[1]["source"], 5)):
        name = re.sub(r"\[[^\]]*\]|\W|20\d{2}년?|제\s*\d+\s*회", "", event_name(entry["title"]))[:20]
        if (name, entry["event_start"]) in kept:
            del records[key]
        else:
            kept.add((name, entry["event_start"]))


def optional(collect):
    def run(get):
        try:
            return collect(get)
        except Exception as error:  # noqa: BLE001 - reported and skipped, see build()
            print(f"{collect.__name__} skipped: {type(error).__name__}", file=sys.stderr, flush=True)
            return []
    return run

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
        # Event sources are added to the schedule when they answer; one that does not answer
        # leaves its events out of this run instead of stopping the whole collection.
        sources["kmi_event"] = ("KMI 세미나", optional(kmi_events))
        sources["bexco"] = ("BEXCO 행사일정", optional(bexco_events))
        sources["institution_event"] = ("해양수산 기관 공지", optional(institution_events))
        sources["naver_event"] = ("언론 보도(일정은 원문 확인)", optional(naver_events))
        sources["eventus"] = ("이벤터스 행사 신청", optional(eventus_events))
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
    # Every source, not only the hubs, leaves out notices that are not company support
    # (operator recruitment, service contracts, judges and the like).
    # Notices whose target names only trades outside ocean and fisheries (철강, 석유화학, 콘텐츠 …)
    # are left out too, read from the full target line.
    for key in [key for key, entry in records.items()
                if entry["category"] in ("support", "rnd") and (
                    NOT_SUPPORT.search(entry["title"]) or
                    other_trades_only(entry.get("target_full") or entry.get("eligibility", "")))]:
        del records[key]
    for entry in records.values():
        classify_information(entry)
    # Events from every source keep to the two groups of the schedule (see event_in_scope).
    for key in [key for key, entry in records.items()
                if entry["category"] in ("domestic", "international") and
                not event_in_scope(entry["title"], entry.get("content_full", "") or entry.get("topic", ""))]:
        del records[key]
    drop_event_duplicates(records)
    for entry in records.values():
        classify_support(entry)
        if entry["category"] in ("support", "rnd"):
            entry["agency"] = agency_name(entry.get("publisher") or SOURCE_AGENCIES.get(entry["source"]) or
                                          sources.get(entry["source"], ("",))[0])
            if "agency_region" not in entry:
                region = agency_region(entry.get("publisher", ""))
                if region:
                    entry["agency_region"] = region
        # Full target and notice text are read for judging and not published.
        target = entry.pop("target_full", "") or entry.get("eligibility", "")
        content = entry.pop("content_full", "")
        if entry["category"] in ("support", "rnd"):
            entry.update(sector_profile(entry["title"], target, content))
            # Sources other than the hubs carry no region field; their own target text may name one.
            named = content_regions(entry["title"], target, content)
            if not named and (target or content).strip():
                named = ["전국"]
            if named and not entry.get("support", {}).get("regions"):
                entry.setdefault("support", {})["regions"] = named
            if "ages" not in entry:
                # The title is read only when the notice carries no content of its own.
                text = f"{target} {content}" if (target or content).strip() else entry["title"]
                bands = age_bands(text)
                if bands:
                    entry["ages"] = bands
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
               "agencies": agency_registry(records.values(), {} if samples else published_agencies(),
                                           updated_at.astimezone(timezone(timedelta(hours=9))).date().isoformat()),
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
        # Shows which press-reported events the next collection would list, without publishing.
        for row in sorted(naver_events(get), key=lambda row: row["event_start"]):
            print(f'{row["event_start"]} {row.get("event_region", "")} {row["title"]}', flush=True)
    else:
        build(args.samples)
