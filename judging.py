"""The one judging step every notice and event goes through.

Collectors hand over raw material only: title, the stated target ("신청 대상"), the notice text,
the official fields of the source and the publisher. This module decides, in one order for
every source:

    1. kind      support notice, R&D, or event (K-Startup files events among its notices)
    2. include   company support at all, and not limited to another trade or to individuals
    3. regions   who may apply by location
    4. ages      company age bands
    5. sea       whether it is an ocean and fisheries notice or event

and, for the whole set, which listings are the same notice or event.

The order of evidence is the same for every question: the stated target first, then the
notice text, then the title, and the official field of the source last. The dictionaries
(sea words, other trades, non-company programs) live here once, so a fix reaches every source
and the site alike (review of 2026-11-22: eleven sea-word lists had drifted apart).
"""

import re
from difflib import SequenceMatcher

from target_rules import (FARM_TARGET, FARMERS, FISHER_COMPANY, FISHER_ONLY, FISHERY_WORD, FOOD_LODGING,
                          INDIVIDUAL_FISHERS, INDIVIDUALS, COMPANIES, EXCLUDED_CLAUSE, OPEN_LIST, NOT_SUPPORT,
                          OTHER_INDUSTRY, SEA, SMALL_MERCHANTS, age_bands, other_trades_only, training_scope)

# ---------- 1. kind ----------

# Taking part only (a talk, a meetup, a demo day to watch) is an event; being chosen for something
# (an IR slot, a program, a booth, a space) is support.
ATTEND_WORD = re.compile(r"포럼|밋업|meetup|네트워킹|커뮤니티\s*데이|데모\s*데이|DEMO\s*DAY|홈\s*커밍|home\s*coming|오픈\s*마이크|"
                         r"세미나|컨퍼런스|콘퍼런스|토크|강연|설명회|창업\s*행사|파운더스|클럽", re.I)
CHOSEN_WORD = re.compile(r"(?<![A-Za-z])IR(?![A-Za-z])|피칭|(?:참여|참가)\s*(?:기업|스타트업|팀)\s*(?:을\s*)?모집|입주|선발|"
                         r"창업\s*-?\s*BuS|매칭|이용권|바우처|지원\s*(?:사업|\(|$)", re.I)


def notice_kind(source, title, official=None, content=""):
    """"event" for a K-Startup listing that is a gathering to attend, else "support". The title and
    the opening of the notice ("… 참여기업 모집을 다음과 같이 공고") say whether anyone is chosen."""
    official = official or {}
    if source != "kstartup":
        return "support"
    gathering = "행사" in official.get("분류", "") or bool(ATTEND_WORD.search(title))
    return "event" if gathering and not CHOSEN_WORD.search(f"{title} {(content or '')[:200]}") else "support"


# ---------- 2. include ----------

# Small-merchant programs are left out unless they also name ordinary companies. Words that only
# borrow the phrase (an SME owner's accident insurance, an SME certificate, a fund's name) do not count.
SME_NAMED = re.compile(r"(?<!재해)중소\s*기업(?!\s*(?:사업주|확인|기본법|부|육성\s*자금))|중\s*[ㆍ·]\s*소\s*기업|"
                       r"(?<![가-힣])중기업|"
                       r"중소\s*[ㆍ·]\s*(?:중견|벤처)\s*기업|중견\s*기업")
TITLE_COMPANY = re.compile(r"중소\s*기업(?!부)|스타트업|창업\s*기업|벤처\s*기업(?!부)")
# Ordinary companies in a target line ("예비창업자 및 7년 이내 창업기업", "중소ㆍ벤처기업").
OPEN_NOUN = re.compile(r"(?:청년\s*)?창업\s*기업|예비\s*창업자|스타트업|중소\s*[ㆍ·]?\s*(?:중견|벤처)?\s*기업(?!\s*(?:기본법|부))|"
                       r"중\s*[ㆍ·]\s*소\s*기업|모든\s*기업|누구나|업종\s*(?:무관|제한\s*없)")
SEPARATOR = re.compile(r"\s*(?:및|또는|,|ㆍ|·|/)\s*")


def _open_target(target):
    """True when the target names ordinary companies that no other trade qualifies: not one
    preceded by a trade ("의료기기 … 중소기업"), followed by one ("중소기업 「화장품법」…"), or
    narrowed to a subset ("중소ㆍ벤처기업 중 … 바이오 관련 기업"). The first company noun is the
    one that defines who may apply; later ones describe the program ("중소 기업 대응력 강화")."""
    for found in list(OPEN_NOUN.finditer(target or ""))[:1]:
        # The clause the noun stands in: back to the last line break or note mark.
        clause = max(target.rfind("\n", 0, found.start()), target.rfind("※", 0, found.start()),
                     target.rfind(" - ", 0, found.start()))
        before = target[max(clause + 1, found.start() - 120):found.start()]
        after = target[found.end():found.end() + 20]
        if OTHER_INDUSTRY.search(before):
            continue
        if re.match(r"\s*중(?![가-힣])", after):
            continue
        head = after[:SEPARATOR.search(after).start()] if SEPARATOR.search(after) else after
        if OTHER_INDUSTRY.search(head):
            continue
        return True
    return False


TRADE_SUBJECT = re.compile(rf"(?:{OTHER_INDUSTRY.pattern})\s*(?:산업|소재|부품|분야|제품|기술|융합)")


def include(title, target="", official_target="", training=False):
    """(keep, reason). Reads the title, the stated target line and the source's own target field."""
    title, target, official_target = title or "", target or "", official_target or ""
    kept = EXCLUDED_CLAUSE.sub(" ", target)
    if NOT_SUPPORT.search(title):
        return False, "기업지원 아님"
    if INDIVIDUAL_FISHERS.search(title):
        return False, "어업인 개인 지원"
    if INDIVIDUALS.search(title) and "기업" not in title:
        return False, "개인 대상"
    if training:
        keep, reason = training_scope(title)
        if not keep:
            return False, reason
    if FARMERS.search(kept) and not COMPANIES.search(kept):
        return False, "농업인 대상"
    if FARM_TARGET.search(kept) and not FISHERY_WORD.search(kept) and not (OPEN_LIST.search(kept) or _open_target(kept)):
        return False, "농업·농식품 대상"
    if FISHER_ONLY.search(target) and not FISHER_COMPANY.search(target):
        return False, "어업인 개인 지원"
    if FOOD_LODGING.search(title) or (FOOD_LODGING.search(kept) and not OPEN_LIST.search(kept) and
                                      not FISHERY_WORD.search(kept)):
        return False, "음식점·숙박 대상"
    if SMALL_MERCHANTS.search(title) and not TITLE_COMPANY.search(title) and not SME_NAMED.search(kept):
        return False, "소상공인 대상"
    if SMALL_MERCHANTS.search(official_target) and not re.search(r"중소|창업|벤처|기업", official_target) and \
            not (SME_NAMED.search(kept) or _open_target(kept) or TITLE_COMPANY.search(title) or SEA.search(title)):
        return False, "소상공인 대상"
    if SMALL_MERCHANTS.search(kept) and not (SME_NAMED.search(kept) or OPEN_LIST.search(kept) or _open_target(kept) or
                                             TITLE_COMPANY.search(title)) and not SEA.search(title):
        return False, "소상공인 대상"
    # A sea notice stays; then a trade named in the target decides, and the title only when the
    # target does not open the notice to ordinary companies.
    if SEA.search(f"{title} {kept}"):
        return True, "해양 특화"
    if other_trades_only(kept):
        return False, "다른 업종 한정(신청 대상)"
    if OTHER_INDUSTRY.search(title) and not _open_target(kept):
        return False, "다른 업종 한정"
    # A title whose subject is another trade ("항공 소재부품 기술개발", "AI x 바이오 융합기술") is
    # limited to it whoever the target line names; a trade word in a name ("한국공항공사",
    # "방산혁신클러스터 헬프데스크", "미디어 콘텐츠 확산") is not.
    if TRADE_SUBJECT.search(title):
        return False, "다른 업종 한정"
    return True, "업종 무관"


# ---------- 3. regions ----------

LOCAL_ONLY = re.compile(r"(?:관내|도내|시내|군내|구내)\s*(?:에\s*)?(?:소재|사업장|본사|기업|중소|업체|소상공인|창업)")


def notice_regions(title, target="", content="", official=(), publisher_region="", tags=(), notice_id=""):
    """Regions a notice is limited to, read from its own content first.

    title [지역] label → stated target → "관내·도내" with the publisher's region → the notice text
    → the source's official region field (K-Startup only) → 전국 when the notice has any text.
    A named region and 전국 are never given together."""
    import collect  # region names and readers live with the collector
    from support_taxonomy import REVIEWED
    if REVIEWED.get(notice_id, {}).get("regions"):
        return list(REVIEWED[notice_id]["regions"])  # checked by hand against the notice
    named = collect.content_regions(title, target, content)
    named = [name for name in named if name != "전국"] or named
    if not named and publisher_region and publisher_region != "전국" and LOCAL_ONLY.search(target or ""):
        named = [publisher_region]
    if not named:
        official = [name for name in official if name and name != "전국"]
        if official:
            named = sorted(set(official))
    if not named and tags and not (target or "").strip() and not (content or "").strip():
        named = [name for name in collect.SHORT_REGIONS for tag in tags if name in tag][:2]
    if not named and ((target or "").strip() or (content or "").strip() or official is not None):
        named = ["전국"]
    return named


# ---------- 4. ages ----------


def notice_ages(title, target="", content="", official=""):
    """Company age bands. The stated target decides when there is one (no age words there means no
    limit); otherwise the notice text, then the source's official field (K-Startup), then the title."""
    import collect
    if (target or "").strip():
        return age_bands(target)
    if (content or "").strip():
        found = age_bands(content)
        if found:
            return found
    if official:
        return collect.kstartup_ages(official)
    return age_bands(title)


# ---------- 5. events ----------

EVENT_AI = re.compile(r"(?<![A-Za-z])(?:AI|AX)(?![A-Za-z])|인공지능|데이터|생성형|LLM|머신\s*러닝|딥\s*러닝", re.I)
# AI events kept are industry and policy gatherings; courses and hands-on sessions are not
# (user decision 2026-11-22). Housing sales fairs are advertising too (user, 2026-11-22).
AI_PRACTICE = re.compile(r"실무|교육|강의|강좌|클래스|과정|특강|아카데미|부트\s*캠프|자격|활용법|사용법|실습|따라\s*하기|노하우")
EVENT_COMMERCIAL = re.compile(
    r"마케팅|광고|쇼핑몰|스마트\s*스토어|상세\s*페이지|쇼츠|유튜브|인스타|틱톡|커머스|세일즈|"
    r"강의|클래스|수강|부트\s*캠프|자격증|교육생|국비\s*지원|채용|취업|승무원|"
    r"입주\s*박람회|분양|모델\s*하우스|아파트|부동산")


# Logistics events count when who holds them or what is presented is about the sea (user decision
# 2026-11-23: 물류를 넣되 주최·주관·발표 주제를 본다), e.g. KMI's 미래물류기술포럼.
LOGISTICS = re.compile(r"물류|로지스틱스|공급망|(?<![A-Za-z])(?:SCM|logistics)(?![A-Za-z])", re.I)
HOST_OR_TOPIC = re.compile(r"(?:공동\s*)?(?:주최|주관|후원)|기조\s*(?:강연|연설)|주제\s*발표|발제|발표|세션|강연|토론|좌장|"
                           r"프로그램|주제")
OPENS = re.compile(r"개최|연다|열린다|마련한다|진행한다")


def host_and_topics(content):
    """Who holds the event and what is presented: lines naming 주최·주관·후원 or the programme
    (기조강연, 발표, 세션, 토론), and in a press report the one who opens it ("○○은 … 개최한다")."""
    parts = []
    for line in re.split(r"(?<=다)\.\s*|\n", content or ""):
        found = HOST_OR_TOPIC.search(line)
        if found:
            parts.append(line[found.start():found.start() + 160])
        if OPENS.search(line):
            parts.append(re.split(r"(?<=[은는이가])\s", line.strip(), maxsplit=1)[0][:120])
    return "\n".join(parts)


def event_in_scope(title, content="", title_only=False):
    """Ocean and fisheries events (title, or the event's own text), logistics events whose host or
    programme is about the sea, and AI or data industry and policy events (title). Press reports are
    judged on their title alone (title_only), since a regional news round-up mentions the sea in
    passing; for a logistics report its host and programme are read as well."""
    title = title or ""
    if EVENT_COMMERCIAL.search(title):
        return False
    if SEA.search(title if title_only else f"{title} {content or ''}"):
        return True
    if LOGISTICS.search(title) and SEA.search(host_and_topics(content)):
        return True
    return bool(EVENT_AI.search(title)) and not AI_PRACTICE.search(title)


# ---------- the same notice or event ----------

# Wrapping that does not change which notice it is: 재공고, 수정, (상시모집), (~11/23까지) …
# A bracket that names a track, an operator or a place ("(인턴형)", "(아이피시)", "(검단지역)") and
# the year stay, so different notices of one program are not merged.
QUALIFIER = re.compile(r"\(\s*(?:수정|변경|재\s*공고|연장|상시\s*모집|추가\s*모집|(?:변경|수정)\s*공고|~[^)]*|[^)]*까지[^)]*)\s*\)|"
                       r"\[[^\]]*\]|(?<=\d년)도|재\s*공고|수정|변경|연장|추가\s*모집|"
                       r"모집|공고|공모|안내|신청|참여자|참가자|[^가-힣A-Za-z0-9]")


def notice_key(title):
    """A title without its wrapping (재공고, 수정, (상시모집), 모집·공고, punctuation)."""
    label = re.match(r"\s*\[([^\]]+)\]", title or "")
    return (label[1] if label else "") + "|" + QUALIFIER.sub("", title or "")


EVENT_NAME = re.compile(r"([가-힣A-Za-z0-9]{2,20}?)\s*(?:주간|포럼|세미나|컨퍼런스|콘퍼런스|박람회|엑스포|위크|공청회|"
                        r"심포지엄|대회|페어|쇼|토론회|설명회)", re.I)


def event_core(title):
    """The name an event goes by, without year or edition: "2026 북극협력주간" → 북극협력주간."""
    text = re.sub(r"20\d{2}\s*년?|제\s*\d+\s*회|\d+\s*일|[’'‘\"“”「」『』<>《》〈〉]", " ", title or "")
    text = re.sub(r"(?<=[가-힣])\s+(?=[가-힣])", "", text)
    found = EVENT_NAME.search(text)
    return (found[0] if found else text).replace(" ", "")


def named_in(core, entry):
    """True when an event's name (five letters or more, spaces left out) appears in another listing's
    title or text: "부산데이터위크" in a notice titled "Busan Data Week 2026 …" whose text says
    "부산 데이터 위크 2026"."""
    return len(core) >= 5 and core in re.sub(r"\s+", "", f'{entry.get("title", "")} {entry.get("_text", "")}')


def same_notice(a, b):
    """True when two listings are one notice (support) or one event."""
    if a.get("category") in ("domestic", "international") or b.get("category") in ("domestic", "international"):
        if not (a.get("event_start") and b.get("event_start")):
            return False
        a_end, b_end = a.get("event_end") or a["event_start"], b.get("event_end") or b["event_start"]
        if a["event_start"] > b_end or b["event_start"] > a_end:
            return False
        one, two = event_core(a["title"]), event_core(b["title"])
        return one == two or SequenceMatcher(None, one, two).ratio() >= 0.75 or \
            named_in(one, b) or named_in(two, a)
    regions_a, regions_b = a.get("regions"), b.get("regions")
    if regions_a and regions_b and set(regions_a) != set(regions_b):
        return False
    return notice_key(a["title"]) == notice_key(b["title"])


SOURCE_RANK = {"manual_event": -1, "kmi_event": 0, "bexco": 1, "institution_event": 2, "kstartup": 3,
               "eventus": 4, "nipa": 4, "kimst_rnd": 4, "kimst_notice": 4, "bizinfo": 6, "bizinfo_event": 7,
               "press_event": 8, "naver_event": 9}


def keep_order(entry):
    """Which copy of a notice is kept: the source that states it best, then the latest notice
    (a 재공고 replaces its 공고)."""
    newer = 0 if re.search(r"재\s*공고|수정|변경", entry["title"]) else 1
    return SOURCE_RANK.get(entry["source"], 5), newer, -len(entry.get("event_end") or "")


def drop_duplicates(records):
    """Keep one listing of each notice and each event; returns the ids left out.

    Notices compare by their unwrapped title (and region, when both name one); events by name and
    overlapping dates. Other records (trend articles, patents) are left as they are."""
    order = sorted((entry for entry in records.values() if entry["category"] in ("support", "rnd", "domestic", "international")),
                   key=keep_order)
    events, notices, dropped = [], {}, []
    for entry in order:
        if entry["category"] in ("domestic", "international"):
            if any(same_notice(entry, other) for other in events):
                dropped.append(entry["id"])
            else:
                events.append(entry)
            continue
        regions = tuple(sorted(entry.get("support", {}).get("regions") or entry.get("regions") or ()))
        seen = notices.setdefault(notice_key(entry["title"]), [])
        if any(not regions or not other or set(regions) == set(other) for other in seen):
            dropped.append(entry["id"])
        else:
            seen.append(regions)
    for key in dropped:
        del records[key]
    return dropped
