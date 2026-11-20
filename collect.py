"""Collect source metadata and build the static K-OceanX portal."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
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
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from ddgs import DDGS
from ddgs.exceptions import DDGSException
from pypdf import PdfReader
from pypdf.errors import PdfReadError

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
        if name in ("kimst_rnd", "kimst_notice", "jcia"):
            # These publishers work with curl on the development host.
            raw = subprocess.check_output(["curl", "-fsSL", "--max-time", "20", "--max-filesize",
                                           "8000000", "--proto", "=https", url])
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


def announcements(get, source, url, selector, key, category):
    rows = []
    for anchor in page(get, source, url).select(selector):
        cells = anchor.find_parent("tr").find_all("td", recursive=False)
        href = anchor["href"]
        title = anchor.get_text(" ", strip=True)
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
        identifier = parse_qs(urlsplit(href).query)[key][0] if key else href.rsplit("/", 1)[-1]
        rows.append(record(source, identifier, title, urljoin(url, href), kind,
                           published=published, deadline=deadline))
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
                           "rnd", deadline=iso(args[6])))
    return [row for row in require(rows) if MARINE.search(row["title"]) or AI.search(row["title"])]


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
        for label, field in (("등록일자", "published"), ("마감일자", "deadline")):
            match = re.search(rf"{label}\s+({DATE})", box.get_text(" ", strip=True))
            if match:
                fields[field] = iso(match[1])
        rows.append(record("kstartup", key, title, params(url, schM="view", pbancSn=key), "support", **fields))
    return require(rows)


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


def build(samples):
    get = reader(samples)
    sources = dict(SOURCES)
    if not samples:
        sources["jcia"] = ("전남정보문화산업진흥원", jcia_notices)
        sources["nor_shipping"] = ("Nor-Shipping", nor_shipping)

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

    merge_exhibitions(records)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for name in ("portal.css", "portal.js"):
        shutil.copyfile(ROOT / "site" / name, dist / name)
    updated_at = datetime.now(timezone.utc)
    payload = {"updated_at": updated_at.isoformat(), "sample": bool(samples),
               "sources": {key: label for key, (label, _) in sources.items()},
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
