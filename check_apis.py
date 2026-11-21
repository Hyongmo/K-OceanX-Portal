"""공식 지원사업 API 확인 실행.

기업마당(지원사업정보·행사정보)과 K-Startup 공고 API를 인증키로 호출해
건수와 항목별 채움 비율, 제목 표본만 기록한다. 인증키와 응답 원문은 남기지 않으며
포털 데이터나 공개 화면에는 영향을 주지 않는다.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# 2026-11-21 웹 화면 수집 시험에서 확인한 접수 중 공고 건수(비교 기준)
WEB_BASELINE = {"기업마당 지원사업": 1303, "K-Startup 공고": 135}
TIMEOUT = 60


def mask(text, keys):
    for key in keys:
        if key:
            text = text.replace(key, "***")
            text = text.replace(urllib.parse.quote(key, safe=""), "***")
    return text


def call(url, params, key_param, key):
    # 공공데이터포털 키는 이미 인코딩된 값이 등록될 수 있으므로 그대로 붙인다.
    encoded_key = key if "%" in key else urllib.parse.quote(key, safe="")
    query = urllib.parse.urlencode(params)
    full = f"{url}?{key_param}={encoded_key}&{query}"
    request = urllib.request.Request(full, headers={"User-Agent": "K-OceanX-Portal API check"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.status, response.read().decode("utf-8", "replace")


def find_items(value):
    """응답 안에서 가장 큰 '항목 목록'(딕셔너리 리스트)을 찾는다."""
    best = []
    if isinstance(value, list):
        if value and all(isinstance(v, dict) for v in value):
            best = value
        for v in value:
            found = find_items(v)
            if len(found) > len(best):
                best = found
    elif isinstance(value, dict):
        for v in value.values():
            found = find_items(v)
            if len(found) > len(best):
                best = found
    return best


def structure(value, depth=0):
    """값은 빼고 응답의 뼈대(키 이름)만 보여 준다."""
    if depth > 2:
        return "…"
    if isinstance(value, dict):
        return {k: structure(v, depth + 1) for k, v in list(value.items())[:12]}
    if isinstance(value, list):
        return [f"목록 {len(value)}건"] + ([structure(value[0], depth + 1)] if value else [])
    return type(value).__name__


def report(name, items, title_keys):
    print(f"  항목 수: {len(items)}")
    if name in WEB_BASELINE:
        print(f"  웹 화면 시험(11.21) 건수: {WEB_BASELINE[name]}")
    if not items:
        return
    keys = sorted({k for item in items for k in item})
    print("  항목별 채움 비율:")
    for key in keys:
        filled = sum(1 for item in items if str(item.get(key, "") or "").strip())
        print(f"    {key}: {filled}/{len(items)} ({filled * 100 // len(items)}%)")
    print("  제목 표본:")
    for item in items[:5]:
        title = next((str(item[k]) for k in title_keys if item.get(k)), "(제목 없음)")
        print(f"    - {title[:80]}")


def check(name, url, params, key_param, key, title_keys, paged=None, secrets=()):
    print(f"\n== {name}")
    if not key:
        print("  인증키가 등록되어 있지 않아 건너뜀")
        return False
    try:
        items = []
        if paged:
            page = 1
            while page <= 30:
                status, body = call(url, {**params, paged: page}, key_param, key)
                data = json.loads(body)
                if page == 1:
                    print(f"  HTTP {status}")
                    print("  응답 구조:", json.dumps(structure(data), ensure_ascii=False)[:600])
                batch = find_items(data)
                items.extend(batch)
                total = data.get("totalCount") or data.get("matchCount") if isinstance(data, dict) else None
                if not batch or (total and len(items) >= int(total)):
                    break
                page += 1
        else:
            status, body = call(url, params, key_param, key)
            print(f"  HTTP {status}")
            data = json.loads(body)
            print("  응답 구조:", json.dumps(structure(data), ensure_ascii=False)[:600])
            items = find_items(data)
        report(name, items, title_keys)
        return bool(items)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        print(f"  실패: HTTP {error.code} {mask(detail, secrets)}")
    except json.JSONDecodeError as error:
        print(f"  실패: JSON이 아닌 응답 ({error.msg}) {mask(body[:300], secrets)}")
    except Exception as error:  # 확인 실행이므로 원인만 남기고 다음 API로 넘어간다
        print(f"  실패: {type(error).__name__} {mask(str(error), secrets)[:300]}")
    return False


def main():
    biz = os.environ.get("BIZINFO_API_KEY", "").strip()
    event = os.environ.get("BIZINFO_EVENT_API_KEY", "").strip() or biz
    kstartup = os.environ.get("KSTARTUP_API_KEY", "").strip()
    secrets = (biz, event, kstartup)
    results = [
        check("기업마당 지원사업", "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do",
              {"dataType": "json", "searchCnt": "0"}, "crtfcKey", biz,
              ("pblancNm", "title"), secrets=secrets),
        check("기업마당 행사정보", "https://www.bizinfo.go.kr/uss/rss/bizinfoEventApi.do",
              {"dataType": "json", "searchCnt": "0"}, "crtfcKey", event,
              ("nttNm", "title"), secrets=secrets),
        check("K-Startup 공고", "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01",
              {"perPage": "100", "returnType": "json", "cond[rcrt_prgs_yn::EQ]": "Y"}, "serviceKey", kstartup,
              ("biz_pbanc_nm", "intg_pbanc_biz_nm", "title"), paged="page", secrets=secrets),
    ]
    print(f"\n성공 {sum(results)}/{len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
