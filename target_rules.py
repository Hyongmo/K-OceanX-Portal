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
    r"합격자|취소\s*공고|운영\s*제안\s*모집|구직자"
)
INDIVIDUAL_FISHERS = re.compile(r"직불|직접\s*지불|어촌\s*정착|어업인|어업\s*활동|건강\s*검진|영어\s*정착|농어촌\s*민박|귀어|생계")
SMALL_MERCHANTS = re.compile(r"소상공인|자영업|가맹점|골목\s*상권|전통\s*시장|상점가|카드\s*수수료|지역\s*화폐|동백전|폐업")
OTHER_INDUSTRY = re.compile(
    r"의료기기|의료|헬스\s*케어|병원|제약|신약|화장품|뷰티|(?<!블루)(?<!해양)바이오|농업|농촌|농산|농식품|농기계|"
    r"비료|축산|임산물|임업|산림|목재|원자력|원전|항공|우주|방산|국방|자동차|모빌리티|반도체|디스플레이|"
    r"이차\s*전지|섬유|패션|의류|봉제|신발|가구|주얼리|귀금속|게임|영화|애니메이션|웹툰|음악|공연|예술|관광|숙박|"
    r"외식|음식점|건설|건축|부동산|철도|국가유산|문화재|체육|스포츠|공예|한복|전통주|커피|반려|펫|돌봄|요양|"
    r"사회적\s*경제|사회\s*연대\s*경제|사회적\s*기업|협동조합|마을기업|광업|스마트팜|GAP|로컬\s*푸드|콘텐츠|출판|서점"
)


def judge(title, organizer="", target=""):
    """Return (keep, label) for a notice title, its organizer and its stated target."""
    title = title or ""
    if NOT_SUPPORT.search(title):
        return False, "기업지원 아님"
    if INDIVIDUAL_FISHERS.search(title):
        return False, "어업인 개인 지원"
    if SMALL_MERCHANTS.search(title) or (SMALL_MERCHANTS.search(target or "") and not re.search(r"중소|창업|벤처|기업", target or "")):
        return False, "소상공인 대상"
    if MARITIME.search(f"{title} {organizer or ''}"):
        return True, "해양 특화"
    if OTHER_INDUSTRY.search(title):
        return False, "다른 업종 한정"
    return True, "업종 무관"
