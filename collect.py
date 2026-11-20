"""Collect source metadata and build the static K-OceanX portal."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATE = r"\d{4}[-/]\d{2}[-/]\d{2}"
MARINE = re.compile(r"해양|해운|항만|선박|조선소|조선업|조선해양|조선 산업|수산|양식장|스마트\s*양식|해상|북극항로|항만물류|maritime|nor.shipping|ocean|aquaculture", re.I)
AI = re.compile(r"\bAI\b|인공지능|데이터|디지털|로봇|자율|스마트", re.I)
NEWS_TERMS = ("스마트항만", "스마트양식", "자율운항선박", "해양 인공지능", "해상 공급망")


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
        if name in ("kimst_rnd", "kimst_notice"):
            # The KIMST TLS handshake succeeds with curl on the development host.
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


def naver(get, credentials):
    rows = []
    for term in NEWS_TERMS:
        url = params("https://openapi.naver.com/v1/search/news.json", query=term, display=20, sort="date")
        headers = dict(zip(("X-Naver-Client-Id", "X-Naver-Client-Secret"), credentials))
        for item in json.loads(get("naver", url, headers))["items"]:
            # shortcut: match the headline until relevance is evaluated against a labeled sample.
            title = clean(item["title"])
            if not MARINE.search(title):
                continue
            link = next((value for value in (item.get("originallink"), item.get("link"))
                         if value and urlsplit(value).scheme == "https" and urlsplit(value).hostname), None)
            if not link:
                continue
            key = sha256(link.encode()).hexdigest()[:24]
            rows.append(record("naver", key, title, link, "industry", topic=term,
                               published=parsedate_to_datetime(item["pubDate"]).date().isoformat()))
    return rows


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
    credentials = tuple(os.getenv(key) for key in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"))
    if any(credentials) and not all(credentials):
        raise SystemExit("Set both NAVER_CLIENT_ID and NAVER_CLIENT_SECRET")
    if all(credentials) and not samples:
        sources["naver"] = ("네이버 뉴스", lambda fetch: naver(fetch, credentials))

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

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for name in ("index.html", "portal.css", "portal.js"):
        shutil.copyfile(ROOT / "site" / name, dist / name)
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "sample": bool(samples),
               "sources": {key: label for key, (label, _) in sources.items()},
               "records": list(records.values())}
    temporary = dist / "data.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(dist / "data.json")
    print(f"{len(records)} records written to dist/data.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, help="Replay saved HTTP responses from the source checks")
    build(parser.parse_args().samples)
