"""Score the judging rules against the expected answers in judgment_cases.json.

For now this only reports how many cases the current rules get right; it does not stop a
collection. Once the judging step is rebuilt, every case must pass (change REQUIRE_ALL to True).

`current_judgment` follows today's rules source by source, as collect.py applies them. When the
judging step is rebuilt as one function, this file calls that function instead.
"""

import json
import re
import unittest
from pathlib import Path

import collect
from support_taxonomy import classify_support
from target_rules import NOT_SUPPORT, age_bands, judge, other_trades_only, training_scope

REQUIRE_ALL = False
CASES = json.loads((Path(__file__).resolve().parent / "judgment_cases.json").read_text(encoding="utf-8"))
EVENT_SOURCES = {"eventus", "naver_event", "bexco", "institution_event", "kmi_event"}


def current_judgment(case):
    """What today's rules make of a case: kind, kept or not, regions, ages, maritime."""
    source, title = case["source"], case["title"]
    target, content, official = case.get("target", ""), case.get("content", ""), case.get("official", {})
    kinds = [part.strip() for part in official.get("유형", "").split("@") if part.strip()]
    if source in EVENT_SOURCES or (source == "bizinfo_event" and "교육" not in kinds):
        return {"kind": "event", "keep": collect.event_in_scope(title, content)}
    if source == "bizinfo_event":
        keep, label = judge(title)
        keep = keep and training_scope(title)[0]
        regions = collect.region_hint(title, "", (), content)
    elif source == "kstartup":
        keep, label = judge(title, "", official.get("대상", ""), target)
        regions = collect.kstartup_regions(official.get("지역", ""))
        named = [name for name in collect.content_regions(title, target) if name != "전국"]
        if named:
            regions = named
        elif "전국" in regions or re.search(r"지역\s*(?:제한\s*(?:없|무관)|무관)|(?<![가-힣])전국|타\s*지역", target):
            regions = ["전국"]
    elif source == "bizinfo":
        keep, label = judge(title, "", official.get("대상", ""), target)
        regions = collect.region_hint(title, target, (), content)
    else:
        keep, label = True, ""
        regions = collect.content_regions(title, target, content) or (["전국"] if (target or content).strip() else [])
    keep = keep and not NOT_SUPPORT.search(title) and not other_trades_only(target)
    entry = {"id": case["id"], "category": "support", "title": title, "topic": content, "eligibility": target,
             "support_hints": {"regions": regions}}
    classify_support(entry)
    if source == "kstartup":
        ages = collect.kstartup_ages(official.get("업력", ""))
    else:
        ages = age_bands(f"{target} {content}" if (target or content).strip() else title)
    return {"kind": "support", "keep": keep, "regions": entry.get("support", {}).get("regions", []),
            "ages": ages, "maritime": label == "해양 특화"}


def same_notice(a, b):
    """Whether today's rules list two notices once (only K-Startup over Bizinfo is merged)."""
    key = lambda title: re.sub(r"[^가-힣A-Za-z0-9]", "", title)[:40]
    sources = {a["source"], b["source"]}
    if sources == {"kstartup", "bizinfo"}:
        return key(a["title"]) == key(b["title"])
    if sources <= EVENT_SOURCES:
        name = lambda row: re.sub(r"\[[^\]]*\]|\W|20\d{2}년?|제\s*\d+\s*회", "", collect.event_name(row["title"]))[:20]
        return name(a) == name(b) and a.get("event_start") == b.get("event_start")
    return False


def score():
    """Every expected answer compared with today's rules: (passed, failed lines)."""
    passed, failed = 0, []
    for case in CASES["cases"]:
        got = current_judgment(case)
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
