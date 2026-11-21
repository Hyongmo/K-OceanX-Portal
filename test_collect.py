import json
import unittest
from unittest.mock import patch

from ddgs.exceptions import DDGSException

from collect import (
    NOR_SHIPPING, announcements, bistep_planning, bizinfo_api, bizinfo_events, classify_information, date_range,
    drop_hub_duplicates, komeri, kstartup_api, merge_exhibitions, nia_planning, nor_shipping, period_note, planning_fields,
    pohang_support, record,
)
from support_taxonomy import classify_support
from target_rules import judge


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
            ("[울산] 2026년 미래내일 일경험 인턴형 참여기업 모집 공고", True, "업종 무관"),
            ("[충북] 2026년 2차 미취업청년 취업연계 일경험 지원사업 참여기업 모집", True, "업종 무관"),
        ]
        for title, keep, label in cases:
            with self.subTest(title=title):
                self.assertEqual(judge(title), (keep, label))

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

    def test_bizinfo_events_drop_finished_events(self):
        items = [
            {"eventInfoId": "EVEN_1", "nttNm": "[전국] 수출 상담회 개최", "eventBeginEndDe": "20261201 ~ 20261202",
             "areaNm": "전국", "eventInfoTyNm": "상담회", "bizinfoUrl": "https://www.bizinfo.go.kr/e/1",
             "rceptPd": "2026-11-20 ~ 2026-11-28"},
            {"eventInfoId": "EVEN_2", "nttNm": "지난 설명회", "eventBeginEndDe": "20261101 ~ 20261101",
             "bizinfoUrl": "https://www.bizinfo.go.kr/e/2"},
        ]
        with patch("collect.kst_today", return_value="2026-11-21"):
            row, = bizinfo_events(lambda name, url: json.dumps({"jsonArray": items}).encode(), "key")
        self.assertEqual((row["category"], row["event_start"], row["deadline"]),
                         ("domestic", "2026-12-01", "2026-11-28"))

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
        self.assertEqual(notice["support"]["regions"], ["경북"])


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
