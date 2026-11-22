import json
import re
import unittest
from unittest.mock import patch

from ddgs.exceptions import DDGSException

from collect import (
    address_region, event_in_scope, event_place, eventus_events,
    BOARDS, EVENT_PAGES, board_events, bexco_events, drop_event_duplicates, event_when, kintex_events, kmi_events,
    mabik_events, naver_events, page_event,
    NOR_SHIPPING, announcements, bistep_planning, bizinfo_api, bizinfo_events, classify_information, date_range,
    agency_name, agency_region, agency_registry, city_regions, content_regions, drop_hub_duplicates, iris, region_hint, stated_regions, komeri, kstartup_ages, kstartup_api, merge_exhibitions, nia_planning, nor_shipping, period_note, planning_fields, stated_target,
    pohang_support, record,
)
from support_taxonomy import classify_support
from target_rules import age_bands, judge, other_trades_only, sector_profile, tech_only


class TargetRulesTest(unittest.TestCase):
    def test_keeps_maritime_and_open_programs_and_drops_others(self):
        cases = [
            ("2026년 친환경 쇄빙ㆍ내빙선 신조 지원사업", True, "해양 특화"),
            ("[경남] 거제시 조선협력사 중소기업 육성자금", True, "해양 특화"),
            ("2026년 중소기업 수출물류비 지원사업", True, "업종 무관"),
            ("조선일보 연계 중소기업 홍보 지원", True, "업종 무관"),
            ("[부산] 소상공인 경영안정자금 지원", False, "소상공인 대상"),
            ("[전남] 완도군 청년어촌정착 지원사업", False, "어업인 개인 지원"),
            ("수산자원보호 직접지불금 신청 공고", False, "어업인 개인 지원"),
            ("AI융합 의료기기 성능 평가 지원", False, "다른 업종 한정"),
            ("해외 저작권 바우처 사업 수행기관 모집", False, "기업지원 아님"),
            ("서천 해양 블루바이오 예비창업자 지원", True, "해양 특화"),
            ("(부산센터) 2026년 제10회 제대군인 창업 워크숍 개최 안내", False, "개인 대상"),
            ("2026년 범부처 통합연구지원시스템 운영지원사업 신규과제 공모", False, "기업지원 아님"),
            ("[울산] 2026년 미래내일 일경험 인턴형 참여기업 모집 공고", True, "업종 무관"),
            ("[충북] 2026년 2차 미취업청년 취업연계 일경험 지원사업 참여기업 모집", True, "업종 무관"),
        ]
        for title, keep, label in cases:
            with self.subTest(title=title):
                self.assertEqual(judge(title), (keep, label))

    def test_stated_target_drops_farmer_and_fisher_only_programs(self):
        self.assertEqual(judge("과수 고품질 시설현대화사업", stated="농업경영정보 등록한 농업인 - 농업법인"),
                         (False, "농업인 대상"))
        self.assertEqual(judge("농특산물 TV홈쇼핑 지원", stated="관내 농가 및 농식품 가공업체"),
                         (False, "농업·농식품 대상"))
        self.assertEqual(judge("K-푸드페어 홍보", stated="한국 농림축산식품 제조ㆍ수출업체(※순수 수산물 수출업체 제외)"),
                         (False, "농업·농식품 대상"))
        self.assertEqual(judge("바로마켓 참여자", stated="농축수산물 농식품을 직접 생산 가공하는 농업인, 작목반"),
                         (False, "농업인 대상"))
        self.assertEqual(judge("지역 상품 발굴", stated="중소기업 ① 공산품 및 농축수산물의 가공품 한정")[0], True)
        self.assertEqual(judge("수출 지원", stated="농식품 및 수산식품 수출업체")[0], True)
        self.assertEqual(judge("일자리 지원", stated="관내 기업체 - 농식품 가공업, 제조업, 레저업 등")[0], True)
        self.assertEqual(judge("청년 일자리", stated="도내 주소지를 둔 기업ㆍ농가ㆍ소상공인")[0], True)
        self.assertEqual(judge("수출 조사", stated="농식품(신선농산물 및 가공농산물) 수출기업 및 농가"),
                         (False, "농업·농식품 대상"))
        self.assertEqual(judge("착한가격업소 신규지정 모집"), (False, "소상공인 대상"))
        self.assertEqual(judge("충주시 농업안정기금 이자차액 지원사업", stated="충주시에 주소를 둔 농ㆍ어업인, 생산자단체 및 농업법인")[0],
                         False)
        self.assertEqual(judge("창업경진대회 왕중왕전 청중평가단 모집"), (False, "기업지원 아님"))
        self.assertEqual(judge("친환경 에너지절감장비 보급", stated="연근해어업 허가를 받은 어업인"),
                         (False, "어업인 개인 지원"))
        self.assertEqual(judge("수산물 직거래 택배비 지원", stated="어업인, 어업법인 및 생산자단체")[0], True)

    def test_sector_profile_reads_industries_from_title_target_and_source(self):
        industries = lambda *args, **kwargs: sector_profile(*args, **kwargs).get("industries")
        self.assertEqual(industries("수산식품 가공설비 지원사업"), ["fish_process"])
        self.assertEqual(industries("포장재 지원", "관내 수산식품기업"), ["fish_process"])
        self.assertEqual(industries("리스크안전망 구축", "수산물 수출입 업체(중소ㆍ중견기업)"), ["fish_trade"])
        self.assertEqual(industries("수산 분야 청년 창업 지원"), ["fish_catch", "fish_process", "fish_trade"])
        self.assertEqual(industries("어선사고 예방시스템 구축"), ["fish_catch"])
        # The publisher (e.g. 한국조선해양기자재연구원) never decides the industry; the text does.
        self.assertIsNone(industries("창업기업 패키지 지원"))
        self.assertIsNone(industries("수출 경쟁력 강화", "수출실적분(선박, 항공)"))
        self.assertIsNone(industries("K-푸드 콜드풀링"))
        self.assertIsNone(industries("2026년 기업환경 개선사업 참여기업 모집"))
        self.assertIsNone(industries("침해사고 예방을 위한 취약점 점검 무료 지원"))
        self.assertEqual(industries("국적선사 친환경 선박 전환 지원"), ["port", "ship"])
        self.assertEqual(industries("2026년 제주항 화물유치 지원사업 참여업체 모집"), ["port"])

    def test_tech_only_reads_technology_companies_from_the_target_line(self):
        self.assertEqual(tech_only("부산 소재 AI솔루션 보유 기업, 스타트업, AI개발사(자), 대학원생 등"), ["ai"])
        self.assertEqual(tech_only("지역 미래모빌리티 분야 기업 및 전후방 연관기업"), ["mobility"])
        self.assertEqual(tech_only("AI 활용 및 도입 수요가 있는 상시 근로자 20인 이상 중소기업"), [])
        self.assertEqual(tech_only("관내 제조업, 지식산업, 정보통신산업 중소기업"), [])
        self.assertEqual(tech_only("창업 7년 이내 기업 ※ 중점분야: 바이오·헬스, AI·빅데이터"), [])
        self.assertEqual(sector_profile("입주기업 모집", "서울시에 주소지를 둔 기후테크 기업 및 예비창업자").get("tech_only"),
                         ["green"])

    def test_judgments_come_from_the_text_not_the_publisher(self):
        self.assertEqual(judge("반도체 장비 국산화 지원", "해양수산과학기술진흥원"), (False, "다른 업종 한정"))
        self.assertEqual(judge("수출 지원", "", "", "수산물 가공업체"), (True, "해양 특화"))
        self.assertEqual(sector_profile("2026년도 4차 혁신제품 지정 시행 공고"), {})
        self.assertEqual(region_hint("스타트업 온라인 심화상담 지원"), ["전국"])
        self.assertEqual(region_hint("PoC 지원", "부산 소재 AI솔루션 보유 기업"), ["부산"])
        self.assertEqual(region_hint("수출 지원", "사업자등록증상 부산ㆍ울산ㆍ경남 소재 기계ㆍ조선 업종 기업"), ["경남", "부산", "울산"])
        self.assertEqual(stated_regions("서울시에 주소지를 둔 기후테크 기업"), ["서울"])
        self.assertEqual(stated_regions("전국 중소기업"), [])
        self.assertEqual(stated_regions("울산광역시 남구 내 소재하거나 이전 예정인 기업"), ["울산"])
        self.assertEqual(region_hint("전북형 스마트 제조AI 시범공장 조성사업 공고"), ["전북"])
        self.assertEqual(region_hint("2026년 인천창조경제혁신센터 창업-BuS 프로그램 참여기업 모집 공고"), ["전국"])
        self.assertEqual(region_hint("대구스타트업 리더스포럼 IR피칭", "전국 7년 이내 창업기업"), ["전국"])
        self.assertEqual(region_hint("2026년 광명시 투자유치 보조금 지원 대상기업 모집 재공고"), ["경기"])
        self.assertEqual(region_hint("2026년 예산군 로케이션 인센티브 제작지원 사업 공고"), ["충남"])
        self.assertEqual(region_hint("수산물 직거래", "주민등록이 여수시로 등록된 어업법인"), ["전남"])
        self.assertEqual(region_hint("2026년 남양주시 기업 지원"), ["경기"])
        self.assertEqual(city_regions("고성군 중소기업"), [])
        self.assertEqual(region_hint("블루바이오 예비창업자 지원", "소재지 : 서천군 및 타지역 거주(재직) 또는 창업 예정자"), ["전국"])

    def test_content_comes_before_the_title(self):
        target = "제주특별자치도 이외 지역의 국제화물을 제주항을 경유하여 수출하는 화주 및 국제물류주선업자, 선사"
        self.assertEqual(region_hint("2026년 제주항 화물유치 지원사업 참여업체 모집", target, ["제주"]), ["전국"])
        self.assertEqual(region_hint("스마트공장 지원", "중소기업", (), "개요 ☞ 부산광역시 소재 제조기업 ☞ 지원"), ["부산"])
        self.assertEqual(region_hint("2026년 광명시 투자유치 보조금"), ["경기"])
        self.assertEqual(region_hint("수출 상담회", "", ["울산"]), ["울산"])
        self.assertEqual(content_regions("전북형 시범공장", "도내 제조기업"), [])
        self.assertNotIn("manufacturing", sector_profile("수출 제조기업 지원", "관내 중소기업"))

    def test_trades_outside_ocean_and_fisheries(self):
        for target in ("당진시 소재 철강산업 및 전ㆍ후방 기업", "여수국가산업단지에 위치한 석유화학 관련 업종",
                       "재사용 배터리를 활용하는 이차전지산업 관련 기업", "문화콘텐츠 제작사(문화산업전문회사 제외)",
                       "자동차부품기업", "우주ㆍ항공ㆍ방산 분야 중소ㆍ중견 제조기업", "국내 중소ㆍ중견 전장부품 기업",
                       "이차전지 관련 전ㆍ후방 기업 - 이차전지 소재ㆍ부품 관련 기업"):
            with self.subTest(target=target):
                self.assertTrue(other_trades_only(target))
        for target in ("기계ㆍ조선ㆍ자동차 업종 기업", "경상남도 소재 식품 및 화장품 기업", "관내 중소기업",
                       "제조, 건설 등 11개 업종에 해당하는 중소ㆍ중견기업", "기계ㆍ부품ㆍ철강산업 제조기업"):
            with self.subTest(target=target):
                self.assertFalse(other_trades_only(target))
        industries = lambda target: sector_profile("지원사업", target).get("industries")
        self.assertEqual(industries("경상남도 소재 식품 및 화장품 기업"), ["fish_process"])
        self.assertIsNone(industries("기계ㆍ부품ㆍ철강산업 제조기업"))
        self.assertIsNone(industries("에너지 관련 기업 및 대학ㆍ연구기관"))
        self.assertIsNone(industries("중소기업, 유통ㆍ무역회사 - 해외 물류비"))
        self.assertEqual(industries("기계ㆍ조선ㆍ자동차 업종 기업"), ["ship"])

    def test_agency_guide_reads_agency_locations(self):
        self.assertEqual(agency_region("대구창조경제혁신센터"), "대구")
        self.assertEqual(agency_region("기초자치단체", "부산광역시"), "부산")
        self.assertEqual(agency_region("여수시"), "전남")
        self.assertEqual(agency_region("남서울대학교 창업보육센터"), "")
        self.assertEqual(agency_region("한국산업기술기획평가원", "산업통상부"), "")
        registry = agency_registry([{"agency": "한국무역보험공사"}],
                                   {"한국무역보험공사": {"region": "서울", "last_seen": "2026-11-20"}}, "2026-11-21")
        self.assertEqual(registry["한국무역보험공사"], {"region": "", "last_seen": "2026-11-21"})
        self.assertEqual(agency_name("(재) 대구창조경제혁신센터 대표이사"), "대구창조경제혁신센터")
        self.assertEqual(agency_name("서울기후테크산업지원센터장"), "서울기후테크산업지원센터")
        registry = agency_registry([{"agency": "부산테크노파크", "agency_region": "부산"}],
                                   {"울산테크노파크": {"region": "울산", "last_seen": "2026-11-01"}}, "2026-11-21")
        self.assertEqual(registry["부산테크노파크"], {"region": "부산", "last_seen": "2026-11-21"})
        self.assertEqual(registry["울산테크노파크"], {"region": "울산", "last_seen": "2026-11-01"})
        # Main agencies are listed before any notice of theirs is collected.
        self.assertEqual(registry["부산창조경제혁신센터"], {"region": "부산", "last_seen": ""})
        self.assertEqual(registry["포항테크노파크"]["region"], "경북")
        self.assertEqual(agency_region("부산산업과학혁신원"), "부산")
        registry = agency_registry([], {"BISTEP": {"region": "", "last_seen": "2026-11-21"}}, "2026-11-22")
        self.assertNotIn("BISTEP", registry)
        self.assertEqual(registry["부산산업과학혁신원"], {"region": "부산", "last_seen": "2026-11-21"})

    def test_food_and_lodging_programs_are_left_out(self):
        self.assertEqual(judge("함안 맛집ㆍ멋집 지정 신청 공고"), (False, "음식점·숙박 대상"))
        self.assertEqual(judge("2차 식품안심업소 인센티브 지원 공고"), (False, "음식점·숙박 대상"))
        self.assertEqual(judge("인증 지원", stated="일반ㆍ휴게음식점, 제과점"), (False, "음식점·숙박 대상"))
        self.assertEqual(judge("가루쌀 전문 생산단지 지원사업", stated="농협, 영농조합법인, 농업회사법인"),
                         (False, "농업·농식품 대상"))
        self.assertEqual(judge("웰컴 스테이 지원사업", stated="대전광역시로 사무ㆍ제조 공간을 이전한 7년 이내 기업")[0], True)
        self.assertEqual(judge("고용 지원", stated="제조업, 음식점업 등 관내 중소기업")[0], True)

    def test_target_line_decides_industry_limits(self):
        industries = lambda *args: sector_profile(*args).get("industries")
        self.assertIsNone(industries("IP거래 네트워크(원자력·조선·해양수산) 참가기업 모집",
                                     "아래와 같은 고민이 있는 기업이라면 누구나 신청하실 수 있습니다."))
        profile = sector_profile("해양수산 국내전시회(부산 국제수산 EXPO) 참가 지원",
                                 "도내 소재한 해양수산산업 및 전ㆍ후방 연관산업 분야 중소기업")
        self.assertEqual(profile, {"maritime_common": True})
        self.assertIsNone(industries("한국농수산식품유통공사(aT) 안전성 검사비 지원사업", "농식품 수출업체"))
        self.assertIsNone(industries("지역 상품 발굴 코칭", "공산품 및 농축수산물의 가공품 한정"))
        # The notice's content decides; the title counts only when there is no content.
        self.assertIsNone(industries("수산식품 가공설비 지원사업", "관내 중소기업"))
        self.assertEqual(industries("가공설비 지원사업", "관내 중소기업", "관내 수산식품 가공업체의 설비 개선을 지원"),
                         ["fish_process"])
        self.assertEqual(industries("수산식품 가공설비 지원사업"), ["fish_process"])
        self.assertEqual(industries("수출 지원", "수산물 수출입 업체(중소ㆍ중견기업)"), ["fish_trade"])
        # Shippers of any trade may apply, so the program is not limited to one industry.
        self.assertEqual(sector_profile("제주항 화물유치 지원사업",
                                        "화주 및 국제물류주선업자, 선사 - 대상품목 : 농림수산물, 생활용품 등 모든 수출품"),
                         {"maritime_common": True})
        self.assertNotIn("maritime_common", sector_profile("기업환경 개선사업 참여기업 모집", "관내 중소기업"))

    def test_research_infrastructure_needs_equipment_words(self):
        self.assertNotIn("marine_tech", sector_profile("2026년도 해양수산 R&D사업 기술수요조사 공고 안내"))
        self.assertEqual(sector_profile("2026년 해양수산 연구장비 렌탈지원사업")["marine_tech"], ["m_infra"])

    def test_sector_profile_marks_technology_and_openness(self):
        self.assertEqual(sector_profile("2026년 해양수산 연구장비 렌탈지원사업"),
                         {"maritime_common": True, "marine_tech": ["m_infra"]})
        profile = sector_profile("AI 완전자율운항선박 기술개발사업")
        self.assertEqual((profile["marine_tech"], profile["innovation"]), (["m_engineering"], ["ai", "mobility"]))
        self.assertEqual(sector_profile("첨단 GPU 활용 지원 사업")["innovation"], ["ai"])
        self.assertNotIn("innovation", sector_profile("DAI 지원사업"))
        self.assertEqual(sector_profile("수출 지원", "본사 또는 공장이 부산에 소재한 중소기업"), {})
        self.assertEqual(sector_profile("수출 지원", "도내 중소 수출(예정) 제조기업"), {"manufacturing": True})
        self.assertEqual(sector_profile("육성자금", "제조업, 지식서비스업 중소기업"), {})

    def test_support_type_prefers_title_over_official_field(self):
        entry = record("bizinfo", "PBLN_1", "[부산] 서구 2026년 수산식품 가공설비 지원사업 추가 사업자 모집 공고",
                       "https://www.bizinfo.go.kr/x", "support", eligibility="수산물 가공 및 수출업체",
                       support_hints={"types": ["management"]})
        classify_support(entry)
        self.assertEqual(entry["support"]["types"], ["infrastructure"])
        entry = record("bizinfo", "PBLN_2", "2026년 중소기업제품 전용판매장 참여기업 모집 공고",
                       "https://www.bizinfo.go.kr/y", "support", topic="해외 관광객 대상 판매", support_hints={"types": ["commercial"]})
        classify_support(entry)
        self.assertEqual(entry["support"]["types"], ["commercial"])

    def test_age_bands_follow_the_startup_act(self):
        self.assertEqual(age_bands("예비창업자 대상 교육"), ["prestartup"])
        self.assertEqual(age_bands("예비·초기창업자 모집"), ["prestartup", "y0_3"])
        self.assertEqual(age_bands("창업 7년 이내 법인"), ["y0_3", "y3_7"])
        self.assertEqual(age_bands("창업 후 10년 이내 신산업 기업"), ["y0_3", "y3_7", "y7_10"])
        self.assertEqual(age_bands("업력 3년 이상 기업"), ["y3_7", "y7_10", "y10_plus"])
        self.assertEqual(age_bands("관내 창업기업"), ["y0_3", "y3_7"])
        self.assertEqual(age_bands("중소기업 및 창업기업"), [])
        self.assertEqual(age_bands("중소기업"), [])
        self.assertEqual(age_bands("디자인기업 및 디자인 활용 기업(중소기업) - 디자인관련 예비창업자"), [])

    def test_small_merchant_target_is_dropped_unless_companies_qualify(self):
        self.assertEqual(judge("배달 홍보 지원", target="소상공인")[0], False)
        self.assertEqual(judge("홍보 지원", target="중소기업, 소상공인")[0], True)


class OfficialApiTest(unittest.TestCase):
    def test_date_ranges_keep_start_end_and_time(self):
        self.assertEqual(date_range("20261118 ~ 20261125"), ("2026-11-18", "2026-11-25", ""))
        self.assertEqual(date_range("2026-11-16 ~ 2026-12-18 18:00"), ("2026-11-16", "2026-12-18", "18:00"))
        self.assertEqual(date_range("20261218"), ("", "2026-12-18", ""))
        self.assertEqual(date_range("예산 소진시까지"), ("", "", ""))

    def test_kstartup_api_keeps_open_eligible_notices_with_official_fields(self):
        items = [
            {"pbanc_sn": "179815", "biz_pbanc_nm": "KDB NextONE 부산 6기 모집", "pbanc_rcpt_bgng_dt": "20261116",
             "pbanc_rcpt_end_dt": "20261218", "pbanc_ntrp_nm": "(주)시리즈벤처스", "supt_regin": "부산",
             "biz_enyy": "1년미만,3년미만,7년미만", "supt_biz_clsfc": "시설ㆍ공간ㆍ보육",
             "aply_trgt": "일반기업", "aply_trgt_ctnt": "창업 7년 이내 법인"},
            {"pbanc_sn": "1", "biz_pbanc_nm": "마감된 공고", "pbanc_rcpt_end_dt": "20261101"},
            {"pbanc_sn": "2", "biz_pbanc_nm": "소상공인 온라인 판로 지원", "pbanc_rcpt_end_dt": "20261230"},
        ]

        def get(name, url):
            self.assertEqual(name, "kstartup_api")
            self.assertIn("serviceKey=a%2Bb", url)
            return json.dumps({"data": items, "totalCount": 3}).encode()

        with patch("collect.kst_today", return_value="2026-11-21"):
            row, = kstartup_api(get, "a+b")
        classify_support(row)
        self.assertEqual(row["id"], "kstartup:179815")
        self.assertTrue(row["url"].startswith("https://www.k-startup.go.kr/"))
        self.assertEqual((row["opens"], row["deadline"]), ("2026-11-16", "2026-12-18"))
        self.assertEqual(row["ages"], ["y0_3", "y3_7"])
        self.assertEqual(kstartup_ages("예비창업자,1년미만,3년미만,5년미만,7년미만,10년미만,10년이상"), [])
        self.assertEqual(kstartup_ages("10년이상"), ["y10_plus"])
        self.assertEqual(kstartup_ages("7년미만"), ["y0_3", "y3_7"])
        self.assertEqual(kstartup_ages("예비창업자,7년미만"), ["prestartup", "y0_3", "y3_7"])
        self.assertEqual(kstartup_ages("10년미만"), ["y0_3", "y3_7", "y7_10"])
        self.assertEqual(row["publisher"], "(주)시리즈벤처스")
        self.assertEqual(row["support"]["regions"], ["부산"])
        self.assertIn("scaleup", row["support"]["stages"])
        self.assertIn("infrastructure", row["support"]["types"])
        self.assertNotIn("support_hints", row)

    def test_bizinfo_api_routes_rnd_and_reads_regions(self):
        items = [
            {"pblancId": "PBLN_1", "pblancNm": "[부산] 해양산업 기술 경쟁력 강화 지원", "excInsttNm": "부산경제진흥원",
             "jrsdInsttNm": "부산광역시", "reqstBeginEndDe": "20261101 ~ 20261130", "trgetNm": "중소기업",
             "pldirSportRealmLclasCodeNm": "기술", "hashtags": "기술,부산", "creatPnttm": "2026-11-01 09:00:00"},
            {"pblancId": "PBLN_2", "pblancNm": "2026년 3차 기계장비산업기술개발사업 신규지원 대상과제 공고",
             "excInsttNm": "한국산업기술기획평가원", "jrsdInsttNm": "산업통상부",
             "reqstBeginEndDe": "20261029 ~ 20261130", "hashtags": "서울,부산,대구,경남"},
            {"pblancId": "PBLN_3", "pblancNm": "[경남] 일반음식점 우수업소 지정", "reqstBeginEndDe": "20261201"},
        ]
        with patch("collect.kst_today", return_value="2026-11-21"):
            rows = bizinfo_api(lambda name, url: json.dumps({"jsonArray": items}).encode(), "key")
        support, rnd = rows
        classify_support(support)
        self.assertEqual(support["support"]["regions"], ["부산"])
        self.assertTrue(support["maritime"])
        self.assertEqual(rnd["category"], "rnd")
        self.assertEqual(rnd["planning_stage"], "application")
        self.assertEqual(rnd["publisher"], "한국산업기술기획평가원")
        self.assertNotIn("period_note", support)

    def test_bizinfo_api_keeps_undated_period_wording(self):
        items = [{"pblancId": "PBLN_9", "pblancNm": "2026년 수출 바우처 지원", "reqstBeginEndDe": "예산 소진시까지"},
                 {"pblancId": "PBLN_8", "pblancNm": "2026년 판로 지원", "reqstBeginEndDe": "상시 접수"},
                 {"pblancId": "PBLN_7", "pblancNm": "2026년 홍보 지원", "reqstBeginEndDe": ""}]
        with patch("collect.kst_today", return_value="2026-11-21"):
            rows = bizinfo_api(lambda name, url: json.dumps({"jsonArray": items}).encode(), "key")
        self.assertEqual([row.get("period_note") for row in rows], ["예산 소진 시까지", "상시 접수", None])
        self.assertEqual(period_note("2026-11-16 ~ 2026-12-11"), "")

    def test_iris_reads_every_list_page(self):
        def item(number, title):
            return (f'<li><a onclick="f_bsnsAncmListForm_view(\'{number}\',\'x\',\'{number}\',\'1\',\'a\',\'b\','
                    f'\'2026/12/01\')">{title}</a></li>')
        pages = {1: item(1, "2026년 A 기술개발사업 공고") + item(2, "2026년 B 기술개발사업 공고"),
                 2: item(3, "2026년 C 기술개발사업 공고"), 3: ""}
        calls = []

        def get(name, url):
            number = int(re.search(r"pageIndex=(\d+)", url)[1])
            calls.append(number)
            return f"<ul>{pages.get(number, '')}</ul>".encode()

        rows = iris(get)
        self.assertEqual([row["title"][6:7] for row in rows], ["A", "B", "C"])
        self.assertEqual(calls, [1, 2, 3])

    def test_stated_target_reads_the_line_after_the_first_marker(self):
        self.assertEqual(stated_target("개요입니다. ☞ 관내 수산식품기업 ☞ 포장재 지원"), "관내 수산식품기업")
        self.assertEqual(stated_target("요약만 있는 공고"), "")

    def test_bizinfo_events_drop_finished_events(self):
        items = [
            {"eventInfoId": "EVEN_1", "nttNm": "[전국] 해운 수출 상담회 개최", "eventBeginEndDe": "20261201 ~ 20261202",
             "areaNm": "전국", "eventInfoTyNm": "상담회", "bizinfoUrl": "https://www.bizinfo.go.kr/e/1",
             "rceptPd": "2026-11-20 ~ 2026-11-28"},
            {"eventInfoId": "EVEN_2", "nttNm": "지난 설명회", "eventBeginEndDe": "20261101 ~ 20261101",
             "bizinfoUrl": "https://www.bizinfo.go.kr/e/2"},
        ]
        with patch("collect.kst_today", return_value="2026-11-21"):
            row, = bizinfo_events(lambda name, url: json.dumps({"jsonArray": items}).encode(), "key")
        self.assertEqual((row["category"], row["event_start"], row["deadline"]),
                         ("domestic", "2026-12-01", "2026-11-28"))

    def test_bizinfo_events_keep_ocean_and_ai_events_and_move_training_to_support(self):
        def item(number, title, kind, text=""):
            return {"eventInfoId": f"EVEN_{number}", "nttNm": title, "eventBeginEndDe": "20261201 ~ 20261202",
                    "areaNm": "경기", "eventInfoTyNm": kind, "nttCn": text,
                    "bizinfoUrl": f"https://www.bizinfo.go.kr/e/{number}", "originEngnNm": "경기테크노파크"}
        items = [
            item(1, "[강원] 2027년 석탄산업전환지역 지원사업 통합 설명회", "사업설명회"),
            item(2, "[전국] 2027년 유통산업 전망 세미나", "세미나/포럼", "유통 데이터 기반 전략을 공유합니다."),
            item(3, "[울산] AI 트렌드 세미나 개최", "세미나/포럼"),
            item(4, "[경기] 기업 성장 포럼", "세미나/포럼", "해운·항만 기업의 디지털 전환을 다룹니다."),
            item(5, "[경기] 중소기업 재직자 AI 업무 자동화 실무교육", "교육"),
            item(6, "[경기] 오가노이드 활용 및 분석기술 교육", "교육"),
            item(7, "[세종] 새로일하기센터 직업교육 훈련생 모집", "교육"),
            item(8, "[경기] 온라인수출 물류 전문 교육 및 상담회", "교육@수출상담회"),
        ]
        with patch("collect.kst_today", return_value="2026-11-21"):
            rows = bizinfo_events(lambda name, url: json.dumps({"jsonArray": items}).encode(), "key")
        by_id = {row["id"].split("_")[-1]: row for row in rows}
        self.assertEqual(sorted(by_id), ["3", "4", "5", "8"])
        self.assertEqual({key: by_id[key]["category"] for key in by_id},
                         {"3": "domestic", "4": "domestic", "5": "support", "8": "support"})
        self.assertEqual(by_id["5"]["deadline"], "2026-12-01")
        self.assertEqual(by_id["5"]["support_hints"]["types"], ["people"])

    def test_training_titles_are_tagged_as_people_support(self):
        for title, expected in (
            ("2026년 탄소배출권 실무교육 안내", True),
            ("[강동구 청년해냄센터] 성공 창업 스쿨 참가자 모집 공고", True),
            ("27년 창업지원사업대비 IR피칭 역량강화 무료특강", True),
            ("한국기술교육대학교 오픈이노베이션 프로그램 참여기업 모집", False),
            ("인천 연수구 중소기업 판로 지원", False),
        ):
            entry = {"id": "x:1", "category": "support", "title": title}
            classify_support(entry)
            self.assertEqual("people" in entry.get("support", {}).get("types", []), expected, title)

    def test_komeri_reads_period_and_target_from_recent_notices(self):
        listing = ('<div class="bbsBox"><div class="title bo_tit"><a href="https://www.komeri.re.kr/bbs/board.php?'
                   'bo_table=business&amp;wr_id=231">울산지역 GVC 진출 기업지원사업 수혜기업 모집</a></div>'
                   '<div class="date">2026-11-17</div></div>'
                   '<div class="bbsBox"><div class="title bo_tit"><a href="https://www.komeri.re.kr/bbs/board.php?'
                   'bo_table=business&amp;wr_id=10">오래된 공고</a></div><div class="date">2025-01-02</div></div>')
        detail = ('<div id="bo_v_con">□ 지원대상 : 울산지역 조선해양기자재 중소기업\n'
                  '□ 모집기간 : 2026. 11. 16. (월) ~ 2026. 11. 28. (금), 18시 까지</div>')

        def get(name, url):
            return (detail if "wr_id=231" in url else listing).encode()

        with patch("collect.kst_today", return_value="2026-11-21"):
            row, = komeri(get)
        self.assertEqual(row["deadline"], "2026-11-28")
        self.assertEqual(row["eligibility"], "울산지역 조선해양기자재 중소기업")

    def test_hub_duplicates_keep_kstartup_copy(self):
        first = record("kstartup", "1", "2026 해양수산 창업 지원 모집", "https://example.org/", "support")
        copy = record("bizinfo", "PBLN_1", "2026 해양수산 창업 지원 모집", "https://example.org/b", "support")
        rows = {row["id"]: row for row in (first, copy)}
        drop_hub_duplicates(rows)
        self.assertEqual(list(rows), ["kstartup:1"])


class SupportTaxonomyTest(unittest.TestCase):
    def test_formal_rnd_and_company_certification_use_their_own_categories(self):
        planning = record("tp_planning", "joint", "산학연 공동R&D 과제기획", "https://example.org/", "rnd")
        classify_support(planning)
        self.assertNotIn("support", planning)
        certification = record("kimst_notice", "designation", "혁신제품 지정 시행 공고", "https://example.org/", "support")
        classify_support(certification)
        self.assertEqual(certification["support"]["types"], ["certification"])

    def test_company_stage_does_not_replace_support_type(self):
        entry = record("kstartup", "179824", "ICT 청년창업지원센터 입주 모집", "https://example.org/", "support")
        classify_support(entry)
        self.assertEqual(entry["support"]["stages"], ["prestartup", "early"])
        self.assertEqual(entry["support"]["types"], ["infrastructure", "incubation"])
        self.assertIn("사업장 등록·이전", entry["eligibility"])

    def test_investor_matching_does_not_imply_direct_equity(self):
        event = record("kstartup", "a", "엔젤투자 설명회 상담부스 모집", "https://example.org/", "support")
        classify_support(event)
        self.assertEqual(event["support"]["types"], ["finance"])
        self.assertEqual(event["support"]["methods"], ["matching"])
        self.assertNotIn("stages", event["support"])

    def test_one_notice_can_match_both_pohang_support_tracks(self):
        def get(name, url):
            return ('<h2 class="title">해양기업 지원사업</h2>'
                    '<div><span class="s_title">사업수행기관</span><div class="txt">포항테크노파크</div></div>'
                    '<div><span class="s_title">신청기간</span><div class="txt">2026.04.17 ~ 2026.04.30</div></div>'
                    '<div><span class="s_title">사업개요</span><div class="txt"><p>택 1</p>'
                    '<p>R&amp;D 지원 : 수요연계형 개발</p><p>사업화 지원 : 시제품 제작 및 시험분석</p></div></div>').encode()

        notice, = pohang_support(get)
        classify_support(notice)
        self.assertEqual([t["name"] for t in notice["support_tracks"]], ["R&D 지원", "사업화 지원"])
        self.assertIn("research", notice["support"]["types"])
        self.assertIn("testing", notice["support"]["types"])
        # Only the publisher (포항테크노파크) points to 경북 here, so no region is claimed.
        self.assertNotIn("regions", notice["support"])


class InformationClassificationTest(unittest.TestCase):
    def test_routes_research_results_and_event_participation_by_purpose(self):
        cases = [
            ("kimst_notice", "result", "KIMST 지원 연구, 해양방사능오염 신속탐지 기술 개발", "patent", None),
            ("nipa", "16953", "한-베트남 AI 디지털 포럼 전시 부스 참가기업 모집", "international", "2026-10-29"),
            ("nipa", "16922", "베트남 포럼 운영 대행 용역 입찰공고", "support", None),
            ("kstartup", "179822", "강원권 LIPS 민간운영사 연합 INVESTOR DAY", "domestic", "2026-12-01"),
            ("nipa", "16967", "하노이 IT지원센터 입주기업 모집", "support", None),
        ]
        for source, key, title, category, event_start in cases:
            with self.subTest(title=title):
                notice = record(source, key, title, "https://example.org/", "support")
                classify_information(notice)
                self.assertEqual(notice["category"], category)
                self.assertEqual(notice.get("event_start"), event_start)


class PlanningTest(unittest.TestCase):
    def test_nipa_uses_the_published_deadline_time(self):
        def get(name, url):
            return ('<table><tr><td><a href="/home/2-2/17006">GPU 모집</a>'
                    '신청기간 : 2026-11-19 11:00 ~ 2026-11-24 15:00</td><td>2026-11-19</td>'
                    '</tr></table>').encode()

        entry, = announcements(get, "nipa", "https://www.nipa.kr/home/2-2", "tr a", None, "support")
        self.assertEqual(entry["opens"], "2026-11-19")
        self.assertEqual(entry["deadline"], "2026-11-24")
        self.assertEqual(entry["deadline_time"], "15:00")

    def test_bistep_falls_back_to_verified_partner_publication(self):
        def get(name, url):
            if "btis.bistep.re.kr" in url:
                return ('<div class="viewTypeA"><h2>해양 R&D 기획 수요조사</h2>⑥해양 '
                        '부산 소재 산·학·연 등 연구개발주체 공고 및 접수기간 : '
                        '2026.10.26. ~ 11.13. 마. 접수방법</div>').encode()
            raise OSError("Source unavailable")

        entry, = bistep_planning(get)
        self.assertEqual(entry["deadline"], "2026-11-13")
        self.assertEqual(entry["eligibility"], "부산 소재 산·학·연 등 연구개발주체")
        self.assertEqual(entry["planning_stage"], "demand")

    def test_participation_type_and_deadline_remain_distinct(self):
        self.assertEqual(planning_fields("연구개발사업 RFP 초안 사전공시", "2026.10.26.(월) ~ 11.4.(수) 18:00"),
                         {"planning_stage": "opinion", "opens": "2026-10-26",
                          "deadline": "2026-11-04", "deadline_time": "18:00"})
        self.assertEqual(planning_fields("[예비공고] R&D 기획지원사업", "2026-11-16 ~ 2026-11-27"),
                         {"planning_stage": "preview"})
        self.assertEqual(planning_fields("기업주도형 산학연 공동R&D 과제기획", "")["planning_stage"], "joint")
        self.assertEqual(planning_fields("중소기업 R&D 기획 지원", "")["planning_stage"], "planning")
        self.assertEqual(planning_fields("AI 학습용 데이터 구축 수요조사", "2026년 11월 9일~11월 18일")["deadline"],
                         "2026-11-18")

    def test_nia_uses_detail_for_the_proposal_deadline(self):
        title = "2027년 AI 성능강화 데이터 구축 수요조사"

        def get(name, url):
            if "list.do" in url:
                return f'<table><tr><td class="subject"><a class="btnView" data-key="10573">{title}</a></td></tr></table>'.encode()
            return (f'<div class="newsView"><p>{title}</p><p>조사대상 : 국민 누구나<br>'
                    '조사기간 : 2026년 11월 9일(월) ~ 11월 18일(수)</p></div>').encode()

        entry, = nia_planning(get)
        self.assertEqual(entry["planning_stage"], "demand")
        self.assertEqual(entry["eligibility"], "국민 누구나")
        self.assertEqual(entry["deadline"], "2026-11-18")


class NorShippingTest(unittest.TestCase):
    def test_collects_only_facts_from_official_page(self):
        official_page = """
        <meta property="og:title" content="Nor-Shipping 2027">
        <h2>7–11 JUNE 2027 | EXHIBITION 8–11 JUNE | NOVA SPEKTRUM</h2>
        <a href="/the-exhibition/">Visit</a>
        <a href="https://another.example/becomeanexhibitor/">Exhibit</a>
        """.encode()
        lookup_cases = (
            ([{"href": "https://nor-shipping.com.example/the-exhibition/"},
              {"href": "https://www.nor-shipping.com/the-exhibition/", "title": "Wrong date"}],
             None,
             "https://www.nor-shipping.com/"),
            (DDGSException("No results found."), [{"url": "http://www.nor-shipping.com/"}],
             "https://www.nor-shipping.com/"),
            (DDGSException("No results found."), [], NOR_SHIPPING),
        )
        for response, mwmbl_results, expected_url in lookup_cases:
            with self.subTest(mwmbl_results=mwmbl_results), patch("collect.DDGS") as search:
                lookup = search.return_value.text
                if isinstance(response, Exception):
                    lookup.side_effect = response
                else:
                    lookup.return_value = response

                def get(source, url):
                    if source == "mwmbl":
                        self.assertIsNotNone(mwmbl_results)
                        self.assertTrue(url.startswith("https://api.mwmbl.org/api/v2/search/?"))
                        return json.dumps({"results": mwmbl_results}).encode()
                    self.assertEqual((source, url), ("nor_shipping", expected_url))
                    return official_page

                row, = nor_shipping(get)
                self.assertEqual(lookup.call_args.kwargs["backend"], "duckduckgo")
                self.assertEqual(row["title"], "Nor-Shipping 2027")
                self.assertEqual(row["event_start"], "2027-06-07")
                self.assertEqual(row["exhibition_start"], "2027-06-08")
                self.assertEqual(row["exhibition_end"], "2027-06-11")
                self.assertEqual(row["visit_url"], NOR_SHIPPING + "the-exhibition/")
                self.assertNotIn("exhibit_url", row)


class ExhibitionMergeTest(unittest.TestCase):
    def test_merges_new_matches_and_preserves_kotra_notices(self):
        official = record("organizer", "2027", "Ocean-Tech 2027", "https://organizer.example/",
                          "international", event_start="2027-06-07", event_end="2027-06-11",
                          exhibition_start="2027-06-08", exhibition_end="2027-06-11")
        first = record("gep", "1", "2027 해양 기술 전시회 [Ocean Tech]", "https://www.gep.or.kr/gept/1",
                       "international", event_start="2027-06-08", event_end="2027-06-11", deadline="2027-01-08")
        second = record("gep", "2", "Ocean–Tech 2027", "https://www.gep.or.kr/gept/2",
                        "international", event_start="2027-06-08", event_end="2027-06-11", deadline="2027-01-15")
        other_edition = {**second, "id": "gep:3", "title": "Ocean Tech 2028",
                         "event_start": "2028-06-08", "event_end": "2028-06-11"}
        unknown_dates = {**second, "id": "gep:4", "event_end": ""}
        rows = {row["id"]: row for row in (official, first, second, other_edition, unknown_dates)}

        merge_exhibitions(rows)

        self.assertEqual(set(rows), {official["id"], other_edition["id"], unknown_dates["id"]})
        self.assertEqual(official["event_start"], "2027-06-07")
        self.assertEqual(official["gep_notices"],
                         [{field: notice[field] for field in ("title", "url", "deadline")}
                          for notice in (first, second)])

    def test_keeps_ambiguous_matches(self):
        fields = {"event_start": "2027-06-08", "event_end": "2027-06-11"}
        first = record("org1", "a", "Ocean Tech 2027", "https://first.example/", "international", **fields)
        second = record("org2", "b", "Ocean-Tech 2027", "https://second.example/", "international", **fields)
        notice = record("gep", "1", "Ocean Tech 2027", "https://www.gep.or.kr/gept/1",
                        "international", **fields)
        rows = {row["id"]: row for row in (first, second, notice)}

        merge_exhibitions(rows)

        self.assertEqual(len(rows), 3)
        self.assertNotIn("gep_notices", first)
        self.assertNotIn("gep_notices", second)


class EventCollectionTest(unittest.TestCase):
    def test_event_dates_are_read_from_labels_and_event_sentences(self):
        from datetime import date
        for text, written, expected in (
            ("국립부경대학교는 오는 8일 오후 2시 부경컨벤션홀에서 '2026 대한민국 해양수산 대포럼'을 개최한다고 6일 밝혔다.",
             date(2026, 7, 6), ("2026-07-08", "")),
            ("해진공은 22일 부산 아스티호텔에서 열리는 ‘정책 포럼’을 통해 시스템을 공개한다고 16일 밝혔다.",
             date(2026, 7, 16), ("2026-07-22", "")),
            ("부산시는 오는 8일부터 사흘간 파라다이스호텔에서 'PNLG 포럼'을 개최한다고 6일 밝혔다.",
             date(2026, 9, 6), ("2026-09-08", "2026-09-10")),
            ("해양수산부는 11월 3일(화)부터 5일(목)까지 BPEX에서 '세계해양포럼'을 개최한다고 밝혔다.",
             date(2026, 11, 2), ("2026-11-03", "2026-11-05")),
            ("해양수산부는 ’26.10.26.(월)부터 27.(화)까지 BPEX에서 기념행사를 개최한다.",
             date(2026, 10, 25), ("2026-10-26", "2026-10-27")),
            ("◈ 11.3.~5. 부산항국제전시컨벤션센터에서 개최", date(2026, 11, 2), ("2026-11-03", "2026-11-05")),
            ("■ 일시 : 2026. 12. 3.(목) 14:00~17:00\n■ 장소 : 부산 벡스코", date(2026, 11, 10), ("2026-12-03", "")),
            ("공사는 지난 11일 블룸버그와 공동으로 개최한 세미나에서 분석했다고 12일 밝혔다.",
             date(2026, 2, 12), ("2026-02-11", "")),
            ("세미나 자료를 공개했다. 문의는 담당 부서로.", date(2026, 2, 12), ("", "")),
        ):
            with self.subTest(text=text[:20]):
                self.assertEqual(event_when(text, written), expected)

    def test_kmi_seminars_keep_coming_ones(self):
        listing = ('<ul><li><a href="view.do?rbsIdx=165&amp;idx=807"><span class="tit">2026 해양시민포럼</span>'
                   '<span class="data">2026-12-09</span></a></li>'
                   '<li><a href="view.do?rbsIdx=165&amp;idx=805"><span class="tit">국제협력 콘퍼런스</span>'
                   '<span class="data">2026-11-04</span></a></li></ul>')
        with patch("collect.kst_today", return_value="2026-11-22"):
            row, = kmi_events(lambda name, url: listing.encode())
        self.assertEqual((row["id"], row["event_start"], row["url"]),
                         ("kmi_event:807", "2026-12-09", "https://www.kmi.re.kr/web/board/view.do?rbsIdx=165&idx=807"))

    def test_bexco_keeps_ocean_and_ai_events(self):
        def item(seq, kind, title, period):
            return (f'<li><a href="/kor/CMS/EventScheduleMgr/view.do?mCode=MN214&amp;&amp;event_seq={seq}">'
                    f'<span class="eventIcon">{kind}</span><span class="subject">{title}</span>'
                    f'<span class="date">{period}</span><span class="place">제1전시장</span></a></li>')
        first = item(1, "전시", "부산데이터위크 2026", "2026-12-01 ~ 2026-12-02") + item(
            2, "전시", "국제게임전시회 지스타 2026", "2026-11-19 ~ 2026-11-22") + item(
            3, "전시", "2027 국제조선해양산업전", "2027-10-20 ~ 2027-10-23")
        pages = {"1": first}
        def get(name, url):
            return pages.get(re.search(r"page=(\d+)", url)[1], "<ul></ul>").encode()
        with patch("collect.kst_today", return_value="2026-11-22"):
            rows = bexco_events(get)
        self.assertEqual([(row["title"], row["event_start"], row["event_end"]) for row in rows],
                         [("부산데이터위크 2026", "2026-12-01", "2026-12-02"),
                          ("2027 국제조선해양산업전", "2027-10-20", "2027-10-23")])

    def test_press_reports_become_dated_events_once(self):
        item = {"title": "8일 부경대서 &apos;2026 대한민국 해양수산 대포럼&apos;",
                "description": "국립부경대학교는 오는 8일 오후 2시 부경컨벤션홀에서 '2026 대한민국 해양수산 대포럼'을 개최한다고 6일 밝혔다.",
                "link": "https://n.news.naver.com/mnews/article/014/1", "originallink": "https://www.fnnews.com/1",
                "pubDate": "Mon, 06 Jul 2026 10:10:00 +0900"}
        copy = dict(item, link="https://n.news.naver.com/mnews/article/001/2")
        held = dict(item, title="해양수산 포럼 성료", link="https://n.news.naver.com/mnews/article/001/3")
        def get(name, url, headers=None):
            if name == "naver":
                return json.dumps({"items": [item, copy, held]}).encode()
            return "<html><body><div id='dic_area'>부경컨벤션홀에서 열린다.</div></body></html>".encode()
        with patch.dict("os.environ", {"NAVER_CLIENT_ID": "a", "NAVER_CLIENT_SECRET": "b"}), \
                patch("collect.kst_today", return_value="2026-07-06"):
            row, = naver_events(get)
        self.assertEqual((row["title"], row["event_start"], row["category"], row["url"]),
                         ("2026 대한민국 해양수산 대포럼", "2026-07-08", "domestic",
                          "https://n.news.naver.com/mnews/article/014/1"))

    def test_boards_read_event_notices_and_their_date_lines(self):
        board = next(item for item in BOARDS if item["key"] == "ksoe")
        listing = ('<table><tr><td><a href="board.php?bo_table=conference&amp;wr_id=46">2026년 해양플랜트설계연구회 추계워크숍 '
                   '• 행사명 : 2026년 해양플랜트설계연구회 추계워크숍</a></td><td>2026-11-20</td></tr>'
                   '<tr><td><a href="board.php?bo_table=conference&amp;wr_id=45">2026년도 추계학술대회</a></td>'
                   '<td>2026-06-16</td></tr></table>')
        detail = '<div id="bo_v_con">• 행사명 : 워크숍\n• 일자 : 2026년 11월 26일(목) ~ 11월 27일(금)\n• 장소 : 통영 해양과학관</div>'
        def get(name, url):
            return (detail if "wr_id=46" in url else listing).encode()
        row, = board_events(get, board, "2026-11-22")
        self.assertEqual((row["title"], row["event_start"], row["event_end"], row["publisher"]),
                         ("2026년 해양플랜트설계연구회 추계워크숍", "2026-11-26", "2026-11-27", "한국해양공학회"))

    def test_overseas_exhibitions_of_the_register_go_to_the_overseas_list(self):
        board = next(item for item in BOARDS if item["key"] == "kr")
        listing = "<ul><li><a href=\"javascript:frmView('AbC123==', 'N', '' );\">SMM 2027</a></li></ul>"
        detail = '<div id="real_contents">SMM 2027 국제 조선·해양 전시회\n행사 정보\n날짜\n2027년 9월 7-10일\n지역\n독일 함부르크\n</div>'
        def get(name, url):
            return (detail if "BF_View" in url else listing).encode()
        row, = board_events(get, board, "2026-11-22")
        self.assertEqual((row["category"], row["event_start"], row["event_end"], row["event_region"]),
                         ("international", "2027-09-07", "2027-09-10", "독일 함부르크"))

    def test_event_page_takes_the_dates_of_the_edition_in_its_heading(self):
        event = next(item for item in EVENT_PAGES if item["key"] == "wof")
        html = "<html><head><title>2027 제21회 세계해양포럼</title></head><body>2027년 10월 26일 ~ 28일 BPEX</body></html>"
        row, = page_event(lambda name, url: html.encode(), event, "2026-11-22")
        self.assertEqual((row["title"], row["event_start"], row["event_end"]),
                         ("2027 제21회 세계해양포럼", "2027-10-26", "2027-10-28"))

    def test_kintex_keeps_ocean_and_ai_events_from_its_list(self):
        def card(number, title, period):
            return (f'<a class="btn-square-item" href="javascript:fnView(\'./view.do\', {number});">'
                    f'<div class="item-subject">{title}</div><div class="item-date">{period}</div></a>')
        pages = {"1": card(1, "2026 스마트건설·안전·AI 엑스포", "2026.11.25~2026.11.27") +
                      card(2, "제55회 맘앤베이비엑스포", "2026.11.26~2026.11.29")}
        def get(name, url):
            return pages.get(re.search(r"pageIndex=(\d+)", url)[1], "<div></div>").encode()
        rows = kintex_events(get, "2026-11-22")
        self.assertEqual([(row["title"], row["event_start"], row["event_end"]) for row in rows],
                         [("2026 스마트건설·안전·AI 엑스포", "2026-11-25", "2026-11-27")])

    def test_family_programmes_of_the_biological_resources_centre_stay_out(self):
        html = ('<ul><li><a href="view.do?id=1">오프라인 행사 해양바이오 산업 설명회 행사일시 2026-12-03 ~ 2026-12-03 '
                '대상 기업 관계자</a></li><li><a href="view.do?id=2">오프라인 행사 해양생물 톡톡톡 '
                '행사일시 2026-12-05 ~ 2026-12-05 대상 초등동반 가족</a></li></ul>')
        rows = mabik_events(lambda name, url: html.encode(), "2026-11-22")
        self.assertEqual([row["title"] for row in rows], ["해양바이오 산업 설명회"])

    def test_one_event_from_several_sources_is_listed_once(self):
        records = {
            "a": {"source": "bizinfo_event", "category": "domestic", "title": "[부산] 부산데이터위크 2026", "event_start": "2026-12-01"},
            "b": {"source": "bexco", "category": "domestic", "title": "부산데이터위크 2026", "event_start": "2026-12-01"},
            "c": {"source": "naver_event", "category": "domestic", "title": "2026 부산데이터위크", "event_start": "2026-12-01"},
        }
        drop_event_duplicates(records)
        self.assertEqual(list(records), ["b"])


class EventusTest(unittest.TestCase):
    def found(self, **fields):
        base = {"id": "1", "subdomain": "host", "title": "", "state": "Start", "disclosure_status": "open",
                "is_ignore": "false", "event_type": "강연/세미나", "min_money": 0, "payway": "false",
                "area": "서울/경기/인천", "start_date": "2026-11-27T05:00:00Z", "close_date": "2026-11-27T08:00:00Z",
                "full_address": "서울 강남구 테헤란로 1", "app_title": "주최 채널", "description": None}
        return {key: {"raw": value} for key, value in {**base, **fields}.items()}

    def run_with(self, results, poster=""):
        def get(name, url, headers=None, data=None):
            if name == "eventus":
                query = json.loads(data)["query"]
                rows = [row for row in results if query in ("", "해양")]
                return json.dumps({"results": rows, "meta": {"page": {"total_pages": 1}}}).encode()
            raise AssertionError(name)
        with patch("collect.kst_today", return_value="2026-11-22"), \
                patch("collect.poster_text", return_value=poster):
            return eventus_events(get)

    def test_ocean_events_are_kept_and_paid_or_marketing_ones_left_out(self):
        rows = self.run_with([
            self.found(id="1", title="기후변화 대응 스마트양식 전환포럼"),
            self.found(id="2", title="해양 AI 실무 마스터 클래스"),
            self.found(id="3", title="해양 데이터 컨퍼런스", min_money=30000, payway="true"),
            self.found(id="4", title="해양문화 축제", event_type="축제"),
            self.found(id="5", title="AI 마케팅 세미나"),
        ])
        self.assertEqual([row["id"] for row in rows], ["eventus:1"])
        self.assertEqual((rows[0]["url"], rows[0]["event_start"], rows[0]["event_region"]),
                         ("https://event-us.kr/host/event/1", "2026-11-27", "서울"))

    def test_coastal_forums_are_judged_by_their_poster(self):
        forum = self.found(id="9", title="제2회 2026 부산 기업 혁신 포럼", area="부산/울산/경남",
                           full_address="부산 동구 중앙대로214번길 7-8", start_date="2026-11-23T05:00:00Z",
                           close_date="2026-11-23T08:00:00Z")
        row, = self.run_with([forum], poster="세션2 조선해양산업의 AX 전략 및 사례")
        self.assertEqual((row["title"], row["event_region"]), ("제2회 2026 부산 기업 혁신 포럼", "부산"))
        self.assertEqual(self.run_with([forum], poster="ESG 경영 사례"), [])

    def test_scope_words_skip_places_and_media_names(self):
        self.assertFalse(event_in_scope("해운대 문화 세미나"))
        self.assertFalse(event_in_scope("TV조선 경제아카데미"))
        self.assertTrue(event_in_scope("한국선급 친환경기술 컨퍼런스"))
        self.assertFalse(event_in_scope("2026년 AI 기반 글로벌 마케팅 혁신 세미나"))
        self.assertEqual((address_region("부산 해운대구 센텀중앙로 55"), event_place("부산 해운대구 벡스코에서")),
                         ("부산", "부산"))


class RegionReadingTest(unittest.TestCase):
    def test_target_regions_include_tenants_and_residents_but_not_preferences(self):
        for title, target, expected in (
            ("대전 팁스타운 팁스아카데미", "대전 팁스타운 입주기업 및 지역 내 창업기업 등", ["대전"]),
            ("생애 최초 경영안정화 교육", "경기도 거주하며, 도내 창업을 희망하는 만 40세 이상", ["경기"]),
            ("수출 지원", "전국 중소기업(대전 소재 기업 우대)", ["전국"]),
            ("수출 부대비용 지원", "중소기업\n** 우대조건: 최초 수출기업, 충청북도 소재 중소기업", []),
            ("[제주창조경제혁신센터] 오픈이노베이션", "국내·외 대기업, 중견기업 및 스타트업", []),
            ("[부산] 판로 지원", "중소기업", ["부산"]),
        ):
            with self.subTest(target=target[:20]):
                self.assertEqual(content_regions(title, target), expected)

    def test_kstartup_target_region_counts_before_the_official_nationwide_field(self):
        item = {"pbanc_sn": "179836", "biz_pbanc_nm": "대전 팁스타운 26년 제3차 팁스아카데미", "pbanc_rcpt_bgng_dt": "20261118",
                "pbanc_rcpt_end_dt": "20261124", "supt_regin": "전국", "aply_trgt_ctnt": "대전 팁스타운 입주기업 및 지역 내 창업기업 등",
                "pbanc_ntrp_nm": "창업진흥원", "rcrt_prgs_yn": "Y"}
        with patch("collect.kst_today", return_value="2026-11-22"):
            rows = kstartup_api(lambda name, url: json.dumps({"data": [item], "totalCount": 1}).encode(), "key")
        self.assertEqual(rows[0]["support_hints"]["regions"], ["대전"])
