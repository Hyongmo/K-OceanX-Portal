"""Assign discovery tags without turning them into eligibility claims."""

import re


TYPES = {
    "research": "기업 기술개발 지원",
    "technical": "기술지원·제품 고도화",
    "testing": "실증·시험 지원",
    "infrastructure": "공간·인프라 확보",
    "incubation": "창업보육·액셀러레이팅",
    "commercial": "사업화·국내 판로",
    "export": "수출·해외진출",
    "finance": "자금조달·투자유치",
    "people": "인재 확보·역량 강화",
    "management": "지식재산·경영",
    "certification": "인증·지정",
}
STAGES = {
    "prestartup": "예비창업",
    "early": "초기창업",
    "market": "사업화·시장진입",
    "scaleup": "성장·스케일업",
    "transition": "성숙·사업전환",
    "restart": "재창업",
}
METHODS = {
    "funding": "사업비·비용 지원",
    "access": "공간·장비·데이터 제공",
    "service": "교육·멘토링·컨설팅",
    "matching": "매칭·상담 연계",
    "equity": "직접투자",
    "loan": "융자·보증",
}
REGIONS = (
    "전국", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "해외",
)

TYPE_TERMS = {
    "technical": r"기술\s*(지원|애로)|시제품|제품\s*(고도화|개선)",
    "testing": r"실증|테스트베드|시험[·ㆍ\s]*(분석|평가|인증)|인증\s*지원|규제\s*(특례|샌드박스)",
    "infrastructure": r"입주|입점기업|사무공간|창업공간|공동장비|연구장비|GPU|데이터셋\s*제공",
    "incubation": r"창업\s*보육|인큐베이팅|[액엑]셀러레이팅|오픈이노베이션|KDB\s*NextONE|청년창업지원센터",
    "commercial": r"사업화|마케팅|국내\s*판로|공공조달|제품\s*출시",
    "export": r"수출|해외진출|해외\s*전시|해외\s*판로|하노이|베트남.*포럼|인도.*전시회",
    "finance": r"투자\s*(유치|설명회|연계)|엔젤투자|INVESTOR\s*DAY|펀드|정책자금|융자|이차보전",
    "people": r"채용|인력\s*(양성|지원)|인턴\s*(지원|매칭)|교육생|재직자\s*교육|아카데미",
    "management": r"지재권|지식재산|특허\s*(출원|전략)|기술이전|경영\s*컨설팅|회계\s*지원",
    "certification": r"혁신제품\s*지정|신기술\s*(인증|활용실적\s*증명)|인증\s*(신청|대상|시행)",
}
STAGE_TERMS = {
    "prestartup": r"예비\s*창업|예비\s*[,·ㆍ／/]\s*초기\s*창업",
    "early": r"초기\s*창업|창업\s*3년\s*(이내|이하|미만)",
    "market": r"시장\s*진입\s*(기업|단계)|사업화\s*단계",
    "scaleup": r"스케일\s*업|성장\s*단계|고성장\s*(기업|스타트업)",
    "transition": r"사업\s*전환|업종\s*전환",
    "restart": r"재창업|재도전",
}
METHOD_TERMS = {
    "funding": r"기획비|연구개발비|시제품\s*제작비|채용장려금|보조금|바우처",
    "access": r"입주|입점기업|사무공간|창업공간|공동장비|연구장비|GPU\s*활용",
    "service": r"컨설팅|멘토링|아카데미|교육생|재직자\s*교육",
    "matching": r"투자자\s*연계|투자\s*설명회|INVESTOR\s*DAY|매칭\s*(지원|부스|행사)|1\s*:\s*1\s*상담",
    "loan": r"융자|정책자금\s*대출|신용보증|이차보전",
}

# Facts reviewed against the linked K-Startup notices. Regions describe the program,
# while eligibility preserves the actual regional requirements or preferences.
REVIEWED = {
    "kstartup:179815": {
        "types": ("incubation", "infrastructure", "finance", "export"),
        "stages": ("early", "scaleup"),
        "methods": ("access", "service", "matching", "equity"),
        "regions": ("부산",),
        "eligibility": "혁신성장산업의 창업 7년 이내 법인. 부울경 소재 및 일부 전략산업 기업 우대.",
    },
    "kstartup:179824": {
        "types": ("infrastructure", "incubation"),
        "stages": ("prestartup", "early"),
        "methods": ("access", "service"),
        "regions": ("서울",),
        "eligibility": "만 39세 이하 ICT·AI·빅데이터 등 예비창업자 또는 창업 3년 이하 기업. 입주 후 사업장 등록·이전 조건 적용.",
    },
    "kstartup:179832": {
        "methods": ("matching",),
        "regions": ("서울",),
    },
}


def classify_support(entry):
    if entry["category"] != "support":
        return
    review = REVIEWED.get(entry["id"], {})
    title = entry["title"]
    if re.search(r"용역\s*(입찰|대행)|^(?:\[마감\]\s*)?KIMST 지원 연구\s*,", title):
        return
    text = " ".join((title, entry.get("topic", ""), entry.get("eligibility", "")))
    types = {key for key, pattern in TYPE_TERMS.items() if re.search(pattern, text, re.I)}
    stages = {key for key, pattern in STAGE_TERMS.items() if re.search(pattern, text)}
    methods = {key for key, pattern in METHOD_TERMS.items() if re.search(pattern, text, re.I)}
    region = entry.get("place", "")
    prefix = re.match(r"^\[([^\]]+)\]", title)
    regions = {value for value in (region, prefix[1] if prefix else "") if value in REGIONS}
    if entry["source"] == "jcia":
        regions.add("전남")
    for track in entry.get("support_tracks", ()):
        types.update(track["types"])

    labels = {"types": (TYPES, types), "stages": (STAGES, stages),
              "methods": (METHODS, methods), "regions": (REGIONS, regions)}
    details = {}
    for field, (options, values) in labels.items():
        marked = values.union(review.get(field, ()))
        if marked:
            details[field] = [option for option in options if option in marked]
    if details:
        entry["support"] = details
    if review.get("eligibility"):
        entry.setdefault("eligibility", review["eligibility"])
