import json
import unittest
from unittest.mock import patch

from ddgs.exceptions import DDGSException

from collect import NOR_SHIPPING, merge_nor_shipping, nor_shipping


class NorShippingTest(unittest.TestCase):
    def test_merges_only_the_reviewed_edition_and_preserves_kotra_deadline(self):
        official = {"id": "nor_shipping:2027", "event_start": "2027-06-07"}
        notice = {"id": "gep:OVS000029059", "source": "gep", "title": "2027 노르웨이 오슬로 선박 전시회",
                  "url": "https://www.gep.or.kr/gept/notice", "event_start": "2027-06-08",
                  "deadline": "2026-11-20"}
        records = {notice["id"]: notice}
        merge_nor_shipping(records)
        self.assertEqual(records, {notice["id"]: notice})

        records[official["id"]] = official
        merge_nor_shipping(records)
        self.assertEqual(list(records), [official["id"]])
        self.assertEqual(official["event_start"], "2027-06-07")
        self.assertEqual(official["deadline"], "2026-11-20")
        self.assertEqual(official["gep_notice"],
                         {field: notice[field] for field in ("source", "title", "url")})

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
