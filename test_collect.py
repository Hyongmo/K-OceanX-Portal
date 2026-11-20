import json
import unittest
from unittest.mock import patch

from ddgs.exceptions import DDGSException

from collect import NOR_SHIPPING, merge_exhibitions, nor_shipping, record


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
