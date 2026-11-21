"""Decide whether a notice belongs on the portal for maritime companies.

The portal serves ocean, fisheries, shipping, port and shipbuilding (including
equipment) companies. Notices open to any industry are kept, notices limited to
another industry are dropped, and so are small-merchant programs, support for
individual fishers and notices that are not company support at all.
"""

import re

MARITIME = re.compile(
    r"해양|수산|(?<!농)어업|(?<!농)어촌|어항|어선|양식장|양식어|양식업|스마트\s*양식|해운|선박|선사|항만|"
    r"조선(?!일보|대학|대)|기자재(?=.*(?:조선|선박))|해사(?:안전|산업|법|클러스터)|크루즈|블루\s*바이오|"
    r"해상\s*풍력|원양|해저|수중|극지|쇄빙|북극\s*항로|오션|ocean|marine|maritime",
    re.I,
)
NOT_SUPPORT = re.compile(
    r"채용|입찰|용역|운영기관\s*(?:모집|선정)|수행기관\s*(?:모집|선정)|위탁기관|평가위원|심사위원|위원\s*모집|"
    r"자문단\s*모집|강사\s*모집|멘토\s*모집|포상|유공|시상식|결과\s*(?:발표|공고|안내)|선정\s*결과|최종\s*선정|"
    r"합격자|취소\s*공고|운영\s*제안\s*모집|구직자|통합연구지원시스템\s*운영|(?<![A-Za-z])TEST(?![A-Za-z])|"
    r"청중\s*평가단|평가단\s*모집|관람객\s*모집"
)
INDIVIDUAL_FISHERS = re.compile(r"직불|직접\s*지불|어촌\s*정착|어업인|어업\s*활동|건강\s*검진|영어\s*정착|농어촌\s*민박|귀어|생계")
INDIVIDUALS = re.compile(r"제대\s*군인|장병|구직자|미취업자|대학생|청소년|어르신")
FARMERS = re.compile(r"농업인|농업\s*법인|농가|농업\s*경영체|임업인|축산")
COMPANIES = re.compile(r"기업|업체|사업자|소공인|(?<!농)(?<!축)(?<!림)수산|(?<!농)어업(?!인)")
# Farm products and farm-food firms; fisheries words other than inside 농수산·농축수산 keep a notice.
FARM_TARGET = re.compile(r"농업인|농업\s*(?:회사\s*)?법인|영농|농협|농가|작목반|농식품|농특산물|농림축산|농산물|농축산물")
FOOD_LODGING = re.compile(r"음식점|맛집|멋집|식품\s*안심|안심\s*(?:식당|업소)|모범\s*음식|제과점|숙박\s*(?:업|시설)|민박|게스트\s*하우스")
# "어업인" names individual fishers, who are out of scope, so it does not keep a farm program.
FISHERY_WORD = re.compile(r"(?<!농)(?<!축)(?<!림)수산|(?<!농)어업(?!인)|어촌|양식|해양")
# Company words not tied to farm products ("관내 기업체", "기업ㆍ농가", "제조업") keep a notice open.
OPEN_LIST = re.compile(r"공산품|제조업|중소\s*기업|(?<![가-힣])기업(?:체|[ㆍ·,\s])|모든\s*(?:기업|업종)|누구나|업종\s*(?:무관|제한\s*없)")
# Clauses that name who is left out, such as "(※순수 수산물 수출업체 제외)".
EXCLUDED_CLAUSE = re.compile(r"[(（][^()（）]*제외[^()（）]*[)）]|※[^※\n]*제외")
FISHER_ONLY = re.compile(r"어업인")
FISHER_COMPANY = re.compile(r"법인|기업|업체|회사|영어조합|생산자\s*단체")
SMALL_MERCHANTS = re.compile(r"소상공인|자영업|가맹점|골목\s*상권|전통\s*시장|상점가|카드\s*수수료|지역\s*화폐|동백전|폐업|착한\s*가격")
OTHER_INDUSTRY = re.compile(
    r"의료기기|의료|헬스\s*케어|병원|제약|신약|화장품|뷰티|(?<!블루)(?<!해양)바이오|농업|농촌|농산|농식품|농기계|"
    r"비료|축산|농가|한의약|한방|임산물|임업|산림|목재|원자력|원전|항공|우주|방산|국방|자동차|모빌리티|반도체|디스플레이|"
    r"이차\s*전지|섬유|패션|의류|봉제|신발|가구|주얼리|귀금속|게임|영화|애니메이션|웹툰|음악|공연|예술|관광|숙박|"
    r"외식|음식점|건설|건축|부동산|철도|국가유산|문화재|체육|스포츠|공예|한복|전통주|커피|반려|펫|돌봄|요양|"
    r"사회적\s*경제|사회\s*연대\s*경제|사회적\s*기업|협동조합|마을기업|광업|스마트팜|GAP|로컬\s*푸드|콘텐츠|출판|서점"
)


def judge(title, organizer="", target="", stated=""):
    """Return (keep, label) for a notice title, its target field and stated target line.

    The organizer is accepted for callers' convenience but never decides anything."""
    title = title or ""
    if NOT_SUPPORT.search(title):
        return False, "기업지원 아님"
    if INDIVIDUAL_FISHERS.search(title):
        return False, "어업인 개인 지원"
    if INDIVIDUALS.search(title) and "기업" not in title:
        return False, "개인 대상"
    stated_kept = EXCLUDED_CLAUSE.sub(" ", stated or "")
    if FARMERS.search(stated_kept) and not COMPANIES.search(stated_kept):
        return False, "농업인 대상"
    if FARM_TARGET.search(stated_kept) and not FISHERY_WORD.search(stated_kept) and not OPEN_LIST.search(stated_kept):
        return False, "농업·농식품 대상"
    if FISHER_ONLY.search(stated or "") and not FISHER_COMPANY.search(stated or ""):
        return False, "어업인 개인 지원"
    if FOOD_LODGING.search(title) or (FOOD_LODGING.search(stated_kept) and not OPEN_LIST.search(stated_kept) and
                                      not FISHERY_WORD.search(stated_kept)):
        return False, "음식점·숙박 대상"
    if SMALL_MERCHANTS.search(title) or (SMALL_MERCHANTS.search(target or "") and not re.search(r"중소|창업|벤처|기업", target or "")):
        return False, "소상공인 대상"
    # Who publishes a notice says nothing about who may apply; only its title and stated target do.
    if MARITIME.search(f"{title} {stated_kept}"):
        return True, "해양 특화"
    if OTHER_INDUSTRY.search(title):
        return False, "다른 업종 한정"
    return True, "업종 무관"


# Industries are the nine top-level classes of the ocean and fisheries industry
# classification approved by Statistics Korea (2018). A notice tagged with an
# industry is meant for companies in that industry.
INDUSTRIES = {
    "resource": r"해상\s*풍력|해양\s*(?:에너지|자원|광물|공간|건설|구조물)|조력|파력|심해|해저|준설",
    "port": r"해운|(?:해운|외항|국적|컨테이너)\s*선사|선주|항만(?!\s*건설)|화물\s*유치|물동량|부두|컨테이너\s*(?:터미널|선)|해상\s*(?:운송|물류|화물)|항로|"
            r"스마트\s*항만|하역|도선",
    "ship": r"조선(?!일보|대학|대)|선박|해양\s*플랜트|자율\s*운항|쇄빙|함정|선체|친환경\s*선|LNG\s*선",
    "fish_catch": r"(?<!농)어업|(?<!농)어촌|어항|어선|활어|패류|해조류?|(?<!농)(?<!축)(?<!림)수산\s*(?:자원|종자)|종자\s*산업|어장|"
                  r"스마트\s*양식|육상\s*양식|양식\s*(?:업|장|어|산업|기업|시설|생물|어류|기술)",
    "fish_process": r"(?<!농)(?<!축)(?<!림)수산(?:물)?\s*(?:가공|식품)|젓갈|어묵|김\s*가공|건어물",
    "fish_trade": r"(?<!농)(?<!축)(?<!림)수산물\s*(?:유통|판로|수출|직거래|판매|물류|브랜드|소비|수출입)|위판|(?<!농)(?<!축)(?<!림)수산\s*물류|저온\s*저장",
    "leisure": r"해양\s*(?:관광|레저|스포츠)|마리나|요트|크루즈|낚시|섬\s*관광|어촌\s*관광",
    "equipment": r"기자재|선용품|해양\s*(?:장비|로봇|센서|기기|드론)|수중\s*(?:로봇|드론|센서|통신|데이터)|어구|선박\s*부품",
    "service": r"(?<![가-힣])해사(?:\s*(?:안전|산업|법|클러스터|기술|서비스|분야))|선박\s*금융|해운\s*금융|해양\s*(?:금융|보험|교육|엔지니어링|측량)|해양플랜트\s*서비스",
}
FISHERIES = ("fish_catch", "fish_process", "fish_trade")
# "수산" on its own (not inside 농수산·농축수산·농림수산) names the whole fisheries chain: catch, processing and trade.
GENERAL_FISHERIES = r"(?<!해양)(?<!해양 )(?<!농)(?<!축)(?<!림)수산"
# In a stated target, fisheries words count on their own ("수산물 수출입 업체"),
# while other industries need a company word joined to them ("조선협력사"), so
# that a passing mention such as "수출실적(선박, 항공)" does not count.
TARGET_INDUSTRIES = {
    "fish_catch": r"(?<!농)어업\s*(?:기업|업체|법인|경영체)|어업인|어촌계|양식\s*(?:업|어업|장)",
    "fish_process": r"(?<!농)(?<!축)(?<!림)수산(?:물)?\s*(?:가공|식품)|가공\s*업자",
    "fish_trade": r"(?<!농)(?<!축)(?<!림)수산물\s*(?:유통|수출|수출입|판매)",
    "ship": r"(?:조선|선박)\s?[^\s,·ㆍ()]{0,10}(?:기업|업체|업자|협력사|사업자)|조선소|수리\s*조선",
    "equipment": r"기자재[^\s,·ㆍ()]{0,6}(?:기업|업체|업자)",
    "port": r"(?:해운|항만)[^\s,·ㆍ()]{0,10}(?:기업|업체|업자|사업자)|(?:해운|외항|국적)\s*선사|"
            r"외항\s*화물\s*운송|「?해운법」?\s*상",
    "leisure": r"크루즈\s*(?:선사|관광|여행)|마리나\s*(?:업|사업자)|요트\s*(?:업|사업자)",
    "resource": r"해상\s*풍력|해양\s*(?:에너지|플랜트)\s?[^\s,·ㆍ()]{0,6}(?:기업|사업자)",
}

# Ocean and fisheries technology follows the 13 top-level classes of the ocean and
# fisheries science and technology classification (KIMST, revised 2024).
MARINE_TECH = {
    "m_resource": r"해양\s*(?:자원|광물|에너지|수자원)|해수\s*담수|해상\s*풍력|조력|파력|해양\s*심층수",
    "m_environment": r"해양\s*(?:환경|오염|쓰레기|폐기물|생태|기후|탄소)|블루\s*카본|미세\s*플라스틱|해양\s*기후",
    "m_life": r"해양\s*(?:바이오|생명|생물|신소재)|블루\s*바이오|마린\s*바이오|해조류?\s*소재|수산\s*생명",
    "m_observation": r"해양\s*(?:관측|예보|조사|정보|데이터|위성)|해황|수온\s*(?:관측|예측)",
    "m_engineering": r"해양\s*(?:플랜트|장비|통신|로봇)|선박\s*(?:설계|기술|공학)|수중|자율\s*운항|친환경\s*선|조선(?!일보|대학|대)",
    "m_disaster": r"해양\s*(?:재해|방재|사고)|연안\s*(?:재해|침식)|구난|해일|적조",
    "m_coast_port": r"항만|해안|연안|부두|해운\s*물류",
    "m_safety": r"해양\s*안전|해상\s*(?:교통|안전)|선박\s*(?:안전|운항)|(?<![가-힣])해사(?:\s*(?:안전|산업|법|기술))|항해",
    "m_polar": r"극지|북극|남극|쇄빙",
    "m_aquaculture": r"양식(?!\s*(?:에|을|으로|참조|다운|첨부))|수산\s*(?:종자|질병)|어류\s*백신",
    "m_stock": r"수산\s*자원|어장|어초",
    "m_fishing": r"(?<!농)어업|어선|어구|수산(?:물)?\s*(?:가공|식품|유통)",
    "m_infra": r"(?:해양|수산)[^,·ㆍ()]{0,12}연구\s*(?:장비|시설|인프라)",
}
# Innovative technology follows the 12 new industries of the Ministry of SMEs and
# Startups (six strategic industries and twelve new industries, 2026).
INNOVATION = {
    "ai": r"(?<![A-Za-z])AI(?![A-Za-z])|인공지능|생성형|LLM|GPU|빅\s*데이터|데이터\s*(?:바우처|센터|플랫폼|기반|분석|활용|구축)|"
          r"클라우드|(?<![A-Za-z])AX(?![A-Za-z])|디지털\s*전환|(?<![A-Za-z])DX(?![A-Za-z])",
    "semiconductor": r"반도체|팹리스|(?<![A-Za-z])SoC(?![A-Za-z])",
    "mobility": r"모빌리티|자율\s*(?:운항|주행)|전기\s*차|미래\s*차|UAM|드론|무인\s*(?:이동체|선박)",
    "quantum_security": r"양자|보안|사이버|네트워크|(?<![0-9])[56]G(?![A-Za-z])|통신",
    "robotics": r"로봇|로보틱스|피지컬\s*AI|자동화",
    "life": r"바이오|신약|생명|마이크로바이옴",
    "healthcare": r"헬스\s*케어|디지털\s*헬스|웰니스",
    "content": r"콘텐츠|게임|웹툰|메타버스|실감",
    "defense_space": r"방산|국방|우주|항공|위성|함정",
    "green": r"친환경|탄소|넷\s*제로|(?<![A-Za-z])ESG(?![A-Za-z])|기후|순환\s*경제|재활용",
    "energy": r"에너지|수소|원자력|원전|핵융합|해상\s*풍력|태양광|이차\s*전지|배터리",
    "advanced_manufacturing": r"첨단\s*제조|스마트\s*(?:공장|제조)|센서|자율\s*제조|(?<![A-Za-z])AI\s*팩토리|3D\s*프린팅|디지털\s*트윈",
}
MARITIME_COMMON = re.compile(r"해양|(?<!농)(?<!축)(?<!림)수산|바다|블루\s*(?:이코노미|테크|바이오)|오션|ocean|marine|maritime", re.I)
MANUFACTURING = re.compile(r"스마트\s*공장|제조\s*(?:기업|업|혁신|현장|AI|데이터)|공장|뿌리\s*(?:산업|기업)|금형|소공인")
# A stated target counts as manufacturing only when it asks for manufacturers and
# names no other kind of business; "본사 또는 공장" only says where a company sits.
TARGET_MANUFACTURING = re.compile(r"제조\s*(?:기업|업체)|중소\s*제조|제조업(?!\s*(?:및|또는|,|ㆍ|·|과|이나))|공장\s*등록")
OTHER_BUSINESS = re.compile(r"서비스|지식|정보통신|IT|소프트웨어|업종\s*무관|모든\s*업종|기타|도소매|유통|무역")


def _keys(table, text):
    return [key for key, pattern in table.items() if re.search(pattern, text or "")]


# A support notice is limited to a technology only when its target line names companies of
# that technology ("AI 기업", "로봇기업", "미래모빌리티 분야 기업"). Lines about companies that
# want to adopt or use a technology, priorities, examples or open lists do not limit anyone.
TECH_COMPANY = r"[^,.\n·ㆍ:()※\-]{0,12}?(?:기업|스타트업|창업기업|업체|개발사|제조사)"
TECH_OPEN = re.compile(r"도입|활용|희망|수요|의지|우대|우선|중점|전환|예시|구축이\s*필요|업종\s*일체|제한\s*없")
TECH_LIMIT = {**INNOVATION, "quantum_security": r"양자|보안|사이버"}


def tech_only(target):
    """Return the one or two technologies a target line limits a notice to, or []."""
    target = target or ""
    if TECH_OPEN.search(target):
        return []
    keys = [key for key, pattern in TECH_LIMIT.items() if re.search(rf"(?:{pattern}){TECH_COMPANY}", target)]
    return keys if len(keys) <= 2 else []


# Trades outside ocean and fisheries named in a target line. Food makers include seafood
# processors and a list naming 조선 includes shipbuilders, so those count for that maritime
# industry. Machinery, metal and root-industry makers, logistics and energy firms may or may
# not be maritime, so they neither limit nor exclude a notice.
COMPANY_TAIL = r"(?:\([^()]{0,20}\))?[^,.\n()]{0,12}?(?:기업|업체|제작사|사업자|사업체|협력사|업종|산업|제조사)"
OVERLAPPING_TRADES = {
    "ship": r"조선(?!일보|대학|대)",
    "fish_process": r"(?<!농)(?<![농ㆍ·]\s)(?<!건강기능)(?<!기능성)식품",
}
MIXED_TRADES = re.compile(r"(?:기계|금속|뿌리|물류|에너지|조선\s*기자재)" + COMPANY_TAIL)
OTHER_TRADES = re.compile(r"(?:철강|전장\s*부품|석유\s*화학|자동차|미래\s*차|전기\s*차|이차\s*전지|배터리|반도체|디스플레이|화장품|"
                          r"뷰티|바이오\s*헬스|의약품?|의료\s*기기|콘텐츠|문화\s*산업|게임|방송\s*(?:사|제작)|영상물|방산|항공|우주|섬유|패션)"
                          + COMPANY_TAIL)


# Lines that open a notice beyond the trades they name: "제조업 등 11개 업종", "중소기업 또는 …".
# When in doubt a notice is kept, so lists that also admit ventures, young startups, firms in
# transition or "주력산업" in general, and lines that only give examples, do not exclude it.
WIDE_TARGET = re.compile(r"공산품|제조업\s*(?:전반|등)|\d+\s*개\s*업종|중소\s*기업\s*(?:및|,|또는)|또는\s*[^,.\n]{0,10}중소\s*기업|"
                         r"모든\s*(?:기업|업종)|누구나|벤처\s*기업|이노비즈|메인비즈|청년\s*창업|디지털\s*전환|산업\s*전환|"
                         r"탄소\s*배출\s*업종|주력\s*산업|예시|BIG\s*3")


def overlapping_industries(target):
    """Maritime industries reached through another trade named in a target line."""
    return {key for key, word in OVERLAPPING_TRADES.items() if re.search(f"(?:{word}){COMPANY_TAIL}", target or "")}


def other_trades_only(target):
    """True when a target line limits applicants to trades no maritime company belongs to,
    e.g. "철강산업 및 전ㆍ후방 기업", "문화콘텐츠 제작사"."""
    kept = EXCLUDED_CLAUSE.sub(" ", target or "")
    if not OTHER_TRADES.search(kept) or WIDE_TARGET.search(kept) or OPEN_TARGET.search(kept):
        return False
    return not (_keys(TARGET_INDUSTRIES, kept) or overlapping_industries(kept) or MIXED_TRADES.search(kept) or
                MARITIME_COMMON.search(kept) or SEA_TRADES.search(kept))


SEA_TRADES = re.compile(r"선박|조선(?!일보|대학|대)|항만|해운|(?<![가-힣])선사|크루즈|해상\s*풍력|쇄빙|함정")
OPEN_TARGET = re.compile(r"누구나|모든\s*기업|업종\s*(?:무관|제한\s*없)")
BROAD_MARITIME_TARGET = re.compile(r"해양수산\s*(?:산업|기업|분야)[^.\n]{0,20}(?:전\s*[ㆍ·]?\s*후방|연관)|"
                                   r"해양수산\s*(?:관련\s*)?(?:모든|전체)\s*(?:기업|분야)")


def _industries(table, text):
    industries = set(_keys(table, text))
    if re.search(GENERAL_FISHERIES, text or "") and not industries.intersection(FISHERIES):
        industries.update(FISHERIES)
    return industries


def sector_profile(title, target="", content=""):
    """Return the industries a notice is meant for and the technologies it concerns.

    Who may apply is read from the notice's content: the stated target line first, then the
    rest of the notice text. The title decides only for a notice that carries no content.
    Who publishes it never counts."""
    kept = EXCLUDED_CLAUSE.sub(" ", target or "")
    body = EXCLUDED_CLAUSE.sub(" ", content or "")
    has_content = bool(kept.strip() or body.strip())
    if OPEN_TARGET.search(kept) or BROAD_MARITIME_TARGET.search(kept):
        industries = set()
    else:
        # In the wider notice text a lone "수산" may be a passing mention, so only target-style
        # phrases ("수산식품 가공업체", "조선 협력사") count there.
        industries = (_industries(TARGET_INDUSTRIES, kept) | overlapping_industries(kept)) or \
            set(_keys(TARGET_INDUSTRIES, body))
        if not industries and not has_content:
            industries = _industries(INDUSTRIES, title)
    profile = {}
    if industries:
        profile["industries"] = [key for key in INDUSTRIES if key in industries]
    elif BROAD_MARITIME_TARGET.search(kept) or MARITIME_COMMON.search(f"{title} {kept} {body}") or \
            SEA_TRADES.search(f"{title} {kept}"):
        # Tagging a notice as maritime limits no one, so its title counts here as well.
        profile["maritime_common"] = True
    for field, table in (("marine_tech", MARINE_TECH), ("innovation", INNOVATION)):
        keys = _keys(table, title)
        if keys:
            profile[field] = keys
    if (TARGET_MANUFACTURING.search(kept) and not OTHER_BUSINESS.search(kept)) or \
            (not has_content and MANUFACTURING.search(title)):
        profile["manufacturing"] = True
    limited = tech_only(target)
    if limited:
        profile["tech_only"] = limited
    return profile


# Company age bands follow the SME Startup Support Act: a startup is a company
# within 7 years of opening, an early startup within 3 years, and new-industry
# startups may be supported up to 10 years.
AGE_BANDS = ("prestartup", "y0_3", "y3_7", "y7_10", "y10_plus")
_BAND_RANGES = {"y0_3": (0, 3), "y3_7": (3, 7), "y7_10": (7, 10), "y10_plus": (10, 99)}


def bands_under(years):
    """Return the running-company bands a limit of "under N years" covers."""
    return [band for band, (lower, _) in _BAND_RANGES.items() if lower < years]


def age_bands(text):
    """Return the company age bands a notice is limited to, or [] when it names none."""
    text = text or ""
    bands = set()
    if re.search(r"예비\s*(?:청년\s*)?창업|예비\s*[,·ㆍ/]\s*(?:초기|창업)", text):
        bands.add("prestartup")
    if re.search(r"초기\s*창업", text):
        bands.add("y0_3")
    for number, bound in re.findall(r"(?:창업|업력|설립|개업)\s*(?:후\s*)?(\d{1,2})\s*년\s*(이내|이하|미만|이상|초과)", text):
        years = int(number)
        if bound in ("이상", "초과"):
            bands.update(band for band, (_, upper) in _BAND_RANGES.items() if upper > years)
        else:
            bands.update(band for band, (lower, _) in _BAND_RANGES.items() if lower < years)
    if not bands.difference({"prestartup"}) and re.search(r"(?<!예비)창업\s*기업", text) and \
            not re.search(r"중소\s*기업|중견|기업\s*누구나|모든\s*기업", text):
        bands.update(("y0_3", "y3_7"))
    # "디자인기업(중소기업) - 예비창업자, 디자이너" also admits running companies.
    if bands == {"prestartup"} and re.search(r"중소\s*기업|기업\s*및|및\s*기업", text):
        return []
    if set(AGE_BANDS) <= bands:
        return []
    return [band for band in AGE_BANDS if band in bands]
