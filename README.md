# K-OceanX 기업성장 정보포털

GitHub Actions로 정보를 수집하고 정적 웹페이지에서 검색하는 초기 시험판입니다. Python 수집기는 제목, 원문 링크, 출처와 확인된 일정만 공개용 JSON으로 내보냅니다. 검색은 브라우저에서 실행합니다.

## 로컬 실행

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python collect.py
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. 기존 정보원 점검 결과로 실행하려면 `python collect.py --samples work`를 사용합니다. 이 옵션에는 로컬에 별도로 보관한 점검 응답이 필요합니다.

## GitHub에서 시험

1. Actions에서 **Collect and publish portal**을 선택하고 **Run workflow**를 누릅니다. 기본값은 실시간 수집 시험이며 **github-pages** 실행 산출물로 결과를 확인할 수 있습니다.
2. Pages의 Source를 GitHub Actions로 설정한 뒤, 배포할 때는 **Run workflow**에서 `publish`를 선택합니다. 모든 수집과 배포는 수동 실행으로 시작합니다.
3. 네이버 API 연결을 시험할 때는 `check_naver`를 선택합니다. 저장소의 `NAVER_CLIENT_ID`와 `NAVER_CLIENT_SECRET`로 뉴스·웹문서 검색 API에 실제 요청을 보내고 질의별 건수와 기관 원문에서 검증한 공고 건수를 기록합니다.

포털의 네이버 뉴스·웹문서 링크는 입력한 검색어를 각 네이버 검색 화면으로 연결합니다. 수동 수집은 웹문서 검색으로 전남정보문화산업진흥원 공고 후보를 찾고, 기관 원문과 첨부 PDF에서 신청 대상과 마감을 확인합니다. 공고 페이지와 PDF의 마감일이 맞는 항목만 포털에 반영하며, 검토한 기준 공고는 매번 원문에서 다시 수집합니다. 이 시험은 전남정보문화산업진흥원의 AI어장 현장실증 공고 양식에 한정됩니다. [네이버 검색 API 특약조건](https://developers.naver.com/products/terms/)에 따라 API 결과는 공개용 JSON이나 Actions 산출물에 포함하지 않습니다.

시험판에는 KIMST, IRIS, NIPA, KMI, KOTRA 해외시장뉴스, GEP, K-Startup, 부산국제수산엑스포가 연결되어 있습니다. 수집은 현재 목록의 첫 페이지와 일부 행사에 한정합니다. 수집 오류가 발생하면 실행을 실패 처리해 불완전한 데이터로 사이트를 교체하는 일을 막습니다.

특허 및 기업마당 인증 연계, 유료자료용 비공개 반입, 이력 보관, 첨부 본문 검색과 LLM은 후속 작업입니다. KOTRA·GEP 목록 조회 및 기관 게시판의 수집 범위와 공개 이용조건은 게시 전에 확인해야 합니다.
