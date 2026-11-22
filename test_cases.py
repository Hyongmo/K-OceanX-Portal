"""Score the judging rules against the expected answers in judgment_cases.json.

Every case must pass (REQUIRE_ALL): a rule change that breaks an expected answer stops the
collection before anything is published.

`judgment` asks the judging step (judging.py), the same functions the collector uses.
"""

import json
import re
import unittest
from pathlib import Path

from datetime import date

import collect
import judging
from target_rules import SEA

REQUIRE_ALL = True
CASES = json.loads((Path(__file__).resolve().parent / "judgment_cases.json").read_text(encoding="utf-8"))
EVENT_SOURCES = {"eventus", "naver_event", "bexco", "institution_event", "kmi_event"}


def judgment(case):
    """What the judging step makes of a case: kind, kept or not, regions, ages, sea, event dates."""
    source, title = case["source"], case["title"]
    target, content, official = case.get("target", ""), case.get("content", ""), case.get("official", {})
    kinds = [part.strip() for part in official.get("유형", "").split("@") if part.strip()]
    if source in EVENT_SOURCES or (source == "bizinfo_event" and "교육" not in kinds) or \
            judging.notice_kind(source, title, official, content) == "event":
        if source == "eventus":
            keep = bool(SEA.search(f"{title} {content}")) and not judging.EVENT_COMMERCIAL.search(title)
        else:
            keep = judging.event_in_scope(title, f"{target} {content}", title_only=source == "naver_event")
        got = {"kind": "event", "keep": keep}
        if case.get("published"):
            got["event_start"], got["event_end"] = collect.event_when(content, date.fromisoformat(case["published"]))
        return got
    keep, label = judging.include(title, target, official.get("대상", ""), training=source == "bizinfo_event")
    official_regions = collect.kstartup_regions(official.get("지역", "")) if source == "kstartup" else ()
    regions = judging.notice_regions(title, target, content, official_regions, notice_id=case["id"].split("#")[0])
    ages = judging.notice_ages(title, target, content, official.get("업력", "") if source == "kstartup" else "")
    return {"kind": "support", "keep": keep, "regions": regions, "ages": ages, "maritime": label == "해양 특화"}


def same_notice(a, b):
    """Whether the judging step lists two notices once."""
    category = lambda row: "domestic" if row["source"] in EVENT_SOURCES else "support"
    return judging.same_notice({**a, "category": category(a)}, {**b, "category": category(b)})


def score():
    """Every expected answer compared with today's rules: (passed, failed lines)."""
    passed, failed = 0, []
    for case in CASES["cases"]:
        got = judgment(case)
        for field, want in case["expect"].items():
            have = got.get(field)
            ok = sorted(have or []) == sorted(want) if isinstance(want, list) else have == want
            if ok:
                passed += 1
            else:
                failed.append(f'{case["title"][:40]} | {field}: 정답 {want}, 현재 {have} | {case["why"]}')
    rows = {row["id"]: row for row in CASES["same_notice"]["cases"]}
    for pair in CASES["same_notice"]["pairs"]:
        have = same_notice(rows[pair["a"]], rows[pair["b"]])
        if have == pair["same"]:
            passed += 1
        else:
            failed.append(f'{rows[pair["a"]]["title"][:30]} / {rows[pair["b"]]["title"][:30]} | 같은 공고: '
                          f'정답 {pair["same"]}, 현재 {have} | {pair["why"]}')
    return passed, failed


class JudgmentCasesTest(unittest.TestCase):
    def test_cases_score(self):
        passed, failed = score()
        print(f"\n정답표 채점: {passed}/{passed + len(failed)} 맞음, {len(failed)} 틀림")
        for line in failed:
            print("  틀림 · " + line)
        if REQUIRE_ALL:
            self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
