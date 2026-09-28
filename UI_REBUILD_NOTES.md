# UI 리빌드 노트 (ui-rebuild → static-demo → fix-exchanges → security-hardening)

기준 문서: `~/portfolio/DESIGN.md` (다크 핀테크 대시보드, 한국식 상승·하락 색, 브랜드 강조색 **민트 `#3ce8a0` 확정**)
작업일: 2026-09-28

---

## 보안 강화 (security-hardening 브랜치)

공개 저장소 위협 점검(로컬 `PUBLIC_THREAT_REVIEW.md`)에서 남은 항목을 조치했다. 텔레그램 봇 항목(H1, M2, M3)은 봇 코드 삭제로 제외했다.

### 변경 요약

| 요청 | 조치 | 점검 항목 |
|---|---|---|
| 1. 비공개 API는 스케줄러만 호출 | `_wallet_status_loop`(지갑 상태, 60초)·`_withdraw_info_loop`(출금 가능 정보, 6시간)·`_payload_refresh_loop`(공개 시세 페이로드, 5초)를 lifespan에서 시작·종료한다. `_compute_gaps_payload`는 비공개 API를 부르지 않고 `_WALLET_CACHE`를 읽는다. `/api/gaps`·`/ws/gaps`는 `_LATEST_PAYLOAD`만 반환한다(준비 전 `503`). 요청이 들어올 때 출금 한도 로딩을 시작하던 코드는 삭제했다 | H2 |
| 2. refresh-limits 보호 | `ADMIN_TOKEN` 미설정 시 404. 설정 시 `X-Admin-Token`(상수 시간 비교) + 쿨다운(`ADMIN_REFRESH_COOLDOWN_SEC`, 최소 60초, `429`+`Retry-After`). 진행 중이면 409. `/api/limits-status`도 관리자 전용 | H2 |
| 3. 출금 한도 금액 제거 | `withdraws/chance`에서 `can_withdraw` 불리언만 파싱·저장한다. 공개 필드는 `withdraw_status {upbit_can_withdraw, bithumb_can_withdraw}`이고, 기존 `withdraw_limits`(금액)와 `wl_progress`는 삭제했다. 지갑 오류 원문 대신 `auth_error`/`rate_limited`/`upstream_error` 코드를 쓴다 | M1, L3 |
| 4. 문서 기본 끔 | `docs_url`·`redoc_url`·`openapi_url`은 `ENABLE_API_DOCS=1`일 때만 설정 | L1 |
| 5. CORS | `CORS_ALLOW_ORIGINS` 설정 시에만 미들웨어(GET만, 헤더·자격 증명 불허). 기본은 미들웨어 없음(같은 출처만) | L2 |
| 6. 속도 제한·WS 상한 | IP별 토큰 버킷(`RATE_LIMIT_PER_MIN`, `/static/*` 제외, WebSocket 연결 시도 포함), WebSocket 전체·IP별 슬롯(`WS_MAX_CONNECTIONS`/`WS_MAX_PER_IP`, accept 전 거부 → uvicorn에서 HTTP 403). 수신 태스크로 끊김을 감지해 슬롯을 즉시 반납 | H2, L4 |
| (추가) 응답 압축 | `GZipMiddleware(minimum_size=1024)`: 실측 `/api/gaps` 2,387,166 → 296,424 bytes | H2 |
| 7. 테스트 | `tests/` 27개(pytest), `requirements-dev.txt`, `pytest.ini` | — |
| 8. 문서 | README "공개 서버 운영" 절과 "테스트" 절, `.env.example` 변수 9개(이름만), `CLAUDE.md` 구조 설명 | — |
| 프론트엔드 | 공개 페이지의 "출금한도" 버튼과 관련 JS 삭제(관리자 전용이 됨). 모달은 금액 대신 "출금 가능 여부"(가능·불가·알 수 없음 표시)를 보여준다. 오류 코드는 한글 라벨로 표시. 폰트 subset 재생성 | — |

### 결정과 이유

| # | 결정 | 이유 |
|---|---|---|
| S1 | refresh-limits는 **제거하지 않고 관리자 전용**으로 남겼다(토큰 미설정 시 404로 사실상 제거 상태) | 요청의 두 선택지를 합쳤다. 기본은 외부에서 존재 자체가 보이지 않고, 운영자가 필요할 때만 토큰으로 켠다 |
| S2 | 공개 필드 이름을 `withdraw_limits`에서 `withdraw_status`로 바꿨다 | 금액이 없다는 것을 이름으로 드러내고, 옛 클라이언트가 금액 필드를 기대하지 않게 한다 |
| S3 | 속도 제한·WS 상한은 새 의존성 없이 직접 구현했다(slowapi 미사용) | 로직이 짧고, 의존성·공급망을 늘리지 않는다. 클라이언트 IP는 uvicorn의 `--proxy-headers`(기본 `127.0.0.1` 신뢰)에 맡기고 `X-Forwarded-For`를 직접 믿지 않는다 |
| S4 | WebSocket Origin 검사는 `CORS_ALLOW_ORIGINS`가 설정됐을 때만 한다 | 설정이 없을 때 Host 헤더와 비교하면, 프록시가 Host를 바꾸는 환경(nginx 기본값)에서 정상 사용자까지 막을 수 있다 |
| S5 | 테스트용 `KIMGAP_SKIP_DOTENV=1` 스위치를 넣었다 | 테스트가 실제 키가 든 `.env`를 읽지 않게 한다. 테스트는 httpx 비동기 요청과 `websockets.connect`도 모두 막는다 |
| S6 | 페이로드 계산이 실패하면 마지막 성공 페이로드를 유지한다 | 일시적 거래소 오류로 화면이 비지 않게 하고, 오류 원문은 로그에만 남긴다 |
| S7 | GZip을 추가했다(요청 목록 밖) | 실측 결과 페이로드가 2.4MB라, 연결 상한만으로는 대역폭 증폭을 충분히 막지 못한다. 변경 위험이 낮다 |

### 검증 결과

| 검사 | 결과 |
|---|---|
| pytest (새로 설치한 venv: FastAPI 0.141 / Starlette 1.7) | ✅ 30 passed (리뷰 반영 후) |
| pytest (`.venv`와 같은 버전: FastAPI 0.135.3 / Starlette 1.0.0) | ✅ 30 passed |
| 코드 리뷰(서브에이전트) | 중간 2건 반영: WebSocket 연결에 속도 제한이 없던 문제, 실제 uvicorn에서 끊긴 연결이 슬롯을 계속 잡던 문제. 낮음 중 5건 반영: `.env`의 `GAP_WS_INTERVAL_SEC` 무시 버그, 429에 CORS 헤더 누락, 토큰 미설정 시 GET이 405로 경로 존재가 드러나던 점, close 코드 문서, CORS 자기 출처 안내. 나머지는 아래 남은 이슈에 기록 |
| 수정 전 `main` 코드에 같은 테스트 | 26개 중 23개 실패(통과 3개는 문서 켜기 테스트): 테스트가 보안 동작을 실제로 검증함을 확인 |
| 실서버 스모크(uvicorn, `KIMGAP_SKIP_DOTENV=1`로 키 미로드, 공개 API만) | ✅ 첫 페이로드 준비, 금액 필드 없음, 문서 3종 404, 관리자 2종 404, 외부 출처 CORS 헤더 없음, IP당 WS 3번째 거부(HTTP 403), WS 갱신 푸시, 분당 30 제한에서 40연속 중 24건 429, gzip 적용. 서버 오류 로그 0건 |
| 정적 검사 | ✅ pyflakes(main, scripts, tests), py_compile, node --check, html-validate, **ESLint 0건** |
| 데모 30초 관찰 | ✅ 다른 출처·WS·`/api`·`/ws` 요청 0, CSP 위반 0, 오류 0, 출금 버튼 없음, 모달 출금 표시에 숫자 없음. 스크린샷 9장 재촬영 |
| 운영 모드 회귀(정적 배치) | ✅ `live`는 `/ws/gaps` 연결 시도, `?mock=1` 정상 |

### 남은 이슈

- 페이로드가 약 2.4MB(압축 시 약 0.3MB)다. 현물·선물 합계 목록과 거래소별 목록이 같은 행을 두 번 싣는다. 프론트엔드는 합계 목록만 쓰므로, 거래소별 목록을 빼면 절반 가까이 줄일 수 있다(응답 스키마 변경이라 이번에는 하지 않았다).
- 보안 헤더(CSP, HSTS, X-Frame-Options)는 운영 서버 앱에는 아직 없다(정적 데모는 `_headers`로 적용됨). 리버스 프록시에서 넣거나 미들웨어를 추가해야 한다.
- 속도 제한·WS 상한은 프로세스 메모리 기준이다. 워커를 여러 개 띄우면 워커마다 따로 센다(현재 배포는 `--workers 1`).
- 리뷰에서 나온 낮음 항목 중 이번에 고치지 않은 것(사용자 요청으로 범위를 줄임):
  - 속도 제한기 키 수가 활성 IP가 많으면 상한(10,000)을 넘을 수 있다.
  - `ADMIN_TOKEN`은 ASCII만 동작한다(README에 명시).
  - 종료 시 관리자가 시작한 갱신 태스크는 취소하지 않는다.
  - 첫 페이로드가 초기 지갑 조회(최대 20초)를 기다린다.
  - 페이로드 계산이 계속 실패해도 화면에 "지연" 표시가 없다.
  - 지갑 조회가 한 번 실패하면 다음 주기까지 입출금 정보가 비어 보인다.
  - WebSocket 클라이언트마다 JSON을 다시 직렬화한다.
  - GZip이 이미 압축된 정적 파일(woff2)도 다시 압축한다.
- `withdraws/chance`의 `can_withdraw` 필드는 업비트 문서 기준이다. 빗썸 응답에서 이 필드가 없으면 값은 `null`(알 수 없음)로 표시된다. 실키로는 확인하지 못했다.

---

## 거래소 수정 (fix-exchanges 브랜치)

### OKX 구현 상태 조사 (작업 전)

| 계층 | 있던 것 | 없던 것 |
|---|---|---|
| 백엔드 수집 | 기동 시 공개 레지스트리(`/api/v5/public/instruments` SPOT·SWAP), 김프 기준가 fallback용 현물 REST 티커 | **WebSocket 가격 수신**, 스왑 REST 티커, 가격 스냅샷, lifespan 시작·종료 |
| API 응답 | `gaps` 행의 `okx_spot_symbol`·`okx_futures_symbol`, `meta.okx_*_registry`, `ref_usdt_stats.okx` | **`okx_spot_comparisons`·`okx_futures_comparisons`**, 현물·선물 합계 목록 포함, `meta.okx_*_price_symbols`·`okx_*_compared` |
| 프론트엔드 | 코인 모달의 상장 카드, `EXCHANGES.okx` 로고 | 상단 "해외 시세 수신" 칩, `findGapRow`의 OKX 목록 검색, 푸터 설명 |
| 목업 | 상장 심볼, 기준가 출처 | 비교 행(`COMPARE_EX`에서 제외돼 있었음), OKX 메타 |

→ 결론: 레지스트리까지만 있고, 다른 4곳처럼 **시세를 받아 비교 탭에 보여주는 경로가 통째로 빠져 있었다.**

### 변경 요약

| 파일 | 내용 |
|---|---|
| `gap_dashboard/main.py` | OKX를 Bybit·Bitget과 같은 구조로 완성: `OKX_PUBLIC_WS`, `_OKX_SPOT_WS_PRICES`/`_OKX_SWAP_WS_PRICES`/`_OKX_PRICE_LOCK`/`_OKX_WS_TASKS`, `_okx_ws_ticker_loop`(`tickers` 채널, 50개씩 구독), `_start/_stop_okx_ws_tasks`, `_fetch_okx_usdt_swap_prices`, `_okx_price_snapshots`(WS 가격 수가 `max(100, 레지스트리의 80%)` 미만이면 REST로 채움). `_compute_gaps_payload`에 OKX 비교 행·메타·응답 키 추가, 현물·선물 합계 목록에 포함. **공개 API만 사용, API 키 없음** |
| `gap_dashboard/static/binance-logo.png` (신규) | 225×225 RGB PNG(Bybit·OKX와 같은 형식). Simple Icons의 바이낸스 SVG(CC0, 상표는 바이낸스 소유)를 공식 색 `#F0B90B`로 어두운 배경에 렌더링 |
| `gap_dashboard/static/index.html` | 바이낸스 로고 연결, "해외 시세 수신"에 OKX 칩 추가, `findGapRow`에 OKX 목록, 푸터 거래소 목록에 OKX |
| `gap_dashboard/static/mock-data.js` | 비교 대상에 OKX 추가(`okx_spot_comparisons`·`okx_futures_comparisons`, 메타), OKX 레지스트리 수를 실제 조회값(현물 406, 스왑 477)에 맞춤 |
| `gap_dashboard/static/fonts/` | `main.py`의 새 문구로 subset 재생성(475자, 104 KiB) |
| `README.md` | 해외 거래소 5곳과 공개 API만 쓴다는 설명 |

### 결정과 이유

| # | 결정 | 이유 |
|---|---|---|
| E1 | 바이낸스 로고는 런타임에 외부에서 받지 않고, 개발 시점에 Simple Icons SVG를 한 번 받아 PNG로 만들어 커밋했다 | CSP(`img-src 'self'`)와 "외부 URL 금지" 요구. Simple Icons 아이콘 데이터는 CC0이고, 로고는 거래소 식별 용도로만 쓴다(다른 거래소 로고와 같은 용도) |
| E2 | OKX WebSocket은 프로토콜 ping을 끄고, 20초 동안 수신이 없으면 문자열 `"ping"`을 보낸다. **ping 뒤에도 20초 동안 아무 메시지가 없으면 재연결한다** | OKX 공식 규칙(30초 무수신 시 연결 종료, 문자열 ping/pong). 리뷰에서 처음 버전은 pong을 확인하지 않아, 반쯤 끊긴 연결에서 멈춘 가격을 실시간처럼 계속 쓴다는 지적을 받아 고쳤다(다른 거래소의 `ping_timeout`과 비슷하게 약 40초 안에 감지) |
| E5 | `_build_exchange_comparison_rows`에 `symbol_format` 인자(기본값 `{base}USDT`)를 더해, OKX는 레지스트리 로드 실패 시에도 `BTC-USDT` / `BTC-USDT-SWAP`로 표시한다 | 리뷰 지적 반영. 다른 거래소는 기본값이라 동작이 바뀌지 않는다 |
| E3 | 스왑 REST 가격의 베이스는 레지스트리(`ctValCcy`)의 instId→베이스 매핑을 우선한다 | 레지스트리와 같은 기준으로 비교 행 심볼이 맞도록 한다 |
| E4 | 백엔드 검증은 uvicorn을 띄우지 않고, `main.py`에서 `.env` 로드 3줄을 AST로 뺀 사본을 메모리에서 실행했다 | `.env`(API 키)를 읽지 않고, 인증 API를 호출하지 않은 채 공개 API로만 확인하기 위해서다 |

### 검증 결과

| 검사 | 결과 |
|---|---|
| OKX 공개 API 실측(키 미로드 확인) | ✅ 레지스트리 현물 406·스왑 477, REST 현물 406·스왑 477. WebSocket 두 연결이 45초 동안 유지, BTC 가격 9번 변경. 비교 행 현물·선물 모두 정상(`BTC-USDT`, `BTC-USDT-SWAP`). 태스크 정리 확인 |
| `_compute_gaps_payload()` 1회 실행(공개 API만, 지갑 모드 `off`) | ✅ 응답에 `okx_spot_comparisons`·`okx_futures_comparisons`, 메타 `okx_spot_compared` 226·`okx_futures_compared` 226. `spot_compared`와 `futures_compared`가 거래소별 합과 일치, 합계 목록에 5개 거래소 모두 포함 |
| 데모 30초 네트워크 관찰 | ✅ 다른 출처 0, WebSocket 0, `/api`·`/ws` 0, CSP 위반 0, 콘솔 오류 0. 요청 8건(로고 5개 포함) |
| 로고 표시(데모) | ✅ 상단 칩, 해외 현물·선물 표, 코인 모달에서 Binance·Bybit·Bitget·OKX·Gate.io 로고가 모두 로드됨(`naturalWidth > 0`). 현물·선물 탭에 OKX 행 있음 |
| 운영 모드 회귀 | ✅ `live`는 `/ws/gaps` 연결 시도, `?mock=1`은 로고 5개 로드 |
| 정적 검사 | ✅ `pyflakes`(main.py, scripts), `py_compile`, `node --check`, `html-validate`. ESLint는 기존과 같은 3건(운영 WS 코드의 빈 `catch`)만 남음 |
| OKX WS 끊김 감지(로컬 가짜 서버, 타임아웃만 1초로 줄인 사본) | ✅ pong을 안 주는 서버에서는 6.5초 동안 3번 재연결하고 새 가격을 받음. pong을 주는 서버에서는 ping 6번 동안 재연결 0회 |
| 심볼 fallback | ✅ 레지스트리가 비어도 OKX는 `BTC-USDT`, `BTC-USDT-SWAP`이고, 다른 거래소 기본값(`BTCUSDT`)은 그대로 |
| 코드 리뷰(서브에이전트, 읽기 전용) | 중간 1건(E2), 낮음 1건(E5), 참고 2건. 중간·낮음은 반영하고 위 검사를 다시 실행했다. 참고 중 표 심볼 대체 목록에 `okx_*_symbol`을 추가했고, `findGapRow` 순서는 기능 영향이 없어 그대로 두었다 |

스크린샷 9장(`~/portfolio/assets/kimgap/`)을 이 빌드로 다시 찍었다. `dist/`는 11개 파일, 278 KiB다.

### 남은 이슈

- ~~`bitget-logo.png`는 확장자만 PNG인 JPEG~~ → 후속 정리 9에서 해소
- OKX 로고 원본은 흰 배경에 작은 워드마크라 20px 원형에서는 글자가 작게 보인다.
- ~~`CLAUDE.md`에 OKX 누락~~ → 후속 정리 10에서 해소
- 김프 기준가(`_fetch_reference_usdt_prices`)는 요청마다 5개 거래소 REST를 호출하는 기존 구조 그대로다. OKX WebSocket 캐시를 여기에 재사용하도록 바꾸면 호출이 줄어들지만, 기존 동작 변경이라 하지 않았다.

### 후속 정리 (9~12, fix-exchanges 브랜치 재생성)

`fix-exchanges`가 `main`에 fast-forward로 합쳐진 뒤 브랜치가 삭제돼 있어서, 같은 이름으로 `main`에서 다시 만들어 작업했다.

| # | 변경 | 결정·이유 | 검증 |
|---|---|---|---|
| 9 | `bitget-logo.png`를 실제 PNG로 변환 | 1024×1024 JPEG를 **225×225 RGB PNG**로 줄여 Bybit·OKX·Binance와 형식·크기를 맞췄다(화면 표시는 20px). 56 KB → 19 KB | `file`: `PNG image data, 225 x 225, 8-bit/color RGB`. 데모에서 로고 로드 확인 |
| 10 | `CLAUDE.md`에 OKX 추가 | WebSocket 수신 거래소 목록, 비교 대상 목록, "새 거래소 추가" 절차(`symbol_format`)를 갱신 | — |
| 11 | Gate.io 비교 행에 `symbol_format="{base}_USDT"`(현물·무기한) | OKX와 같은 방식. Gate 레지스트리의 현물 `id`와 무기한 `name`이 모두 `BTC_USDT` 형식이다 | 레지스트리가 비어도 `BTC_USDT`로 표시됨(키 미로드 사본으로 확인) |
| 12 | `disconnectWs`의 `catch (_) {}`를 `catch { /* 이유 */ }`로, `btnWl` 핸들러의 쓰이지 않는 `catch (e)`를 `catch`로 바꿈 | 동작은 같다. catch 변수 생략(ES2019)은 현재 브라우저가 모두 지원한다 | **ESLint 0건**(이전 오류 1·경고 2) |

재검증은 모두 통과했다.

- pyflakes, `py_compile`, `node --check`, `html-validate`
- 데모 30초 관찰: 다른 출처·WebSocket·`/api`·`/ws` 요청, CSP 위반, 오류가 모두 0건. 로고 5개 로드
- 운영 모드 회귀 없음
- 스크린샷 9장 다시 저장. `dist/`는 11개 파일, 241 KiB

---

## 정적 데모 (static-demo 브랜치)

### 빌드 방법

```bash
python3 scripts/build_demo.py                   # dist/ 생성 (표준 라이브러리만 사용, 재실행 시 결과 동일)
python3 -m http.server 8080 --directory dist    # http://127.0.0.1:8080/
```

`dist/` 구성(10개 파일, 약 273 KiB):

- `index.html`: `kimgap-mode=demo` + CSP `<meta>`
- `static/mock-data.js`, 거래소 로고 4개
- `static/fonts/`: subset 폰트, OFL, README
- `_headers`

`dist/`는 `.gitignore`에 추가했다.

### 변경 요약

| 파일 | 내용 |
|---|---|
| `gap_dashboard/static/index.html` | `<meta name="kimgap-mode" content="live">` 설정으로 운영과 데모를 구분(운영 코드 삭제 없음). 자산 경로를 상대 경로(`static/…`)로, 폰트를 self-host subset으로 바꿈. 데모 모드는 3초 타이머로 갱신하고 "데모 데이터로 동작 중" 표시, 하단 안내 문구, 출금한도 버튼 비활성화 |
| `gap_dashboard/static/mock-data.js` | 출금 한도 필드와 금액 제거. 무작위 행보 대신 **평균 회귀 노이즈**(시장 공통 + 거래소별)로 바꿔 오래 켜 두어도 값이 자연스럽게 기준 근처에서 움직임. `/api/*` 가로채기는 금액 없는 상태 응답만 반환 |
| `scripts/build_demo.py` (신규) | 빌드 스크립트. 인라인 `<script>`·`<style>`의 SHA-256 해시로 CSP를 만들어 `dist/_headers`와 `<meta>`에 넣음 |
| `scripts/subset_font.py` (신규) | Pretendard에서 UI가 쓰는 글자(수집 472자 중 폰트에 있는 471자)만 남긴 subset 생성(개발자용, 빌드에는 불필요) |
| `gap_dashboard/static/fonts/` (신규) | `KimgapSans-Variable.subset.woff2`(103 KiB), `OFL.txt`, `README.md` |
| `README.md` (신규) | 맨 위에 데모 실행·빌드, 실행 모드 표, 실데이터 실행, `data/*.json` 필요 여부 |
| `.gitignore` | `dist/` 추가 |

### 결정과 이유

| # | 결정 | 이유 |
|---|---|---|
| D1 | 모드는 `<meta name="kimgap-mode">`로 정하고, 빌드 스크립트가 `live`를 `demo`로 바꾼다. 운영 페이지의 `?mock=1`은 유지한다 | 소스 파일 하나로 두 모드를 유지하고, 운영 코드(`connectWs` 등)는 그대로 둔다. 쿼리로 데모를 켜는 방식과 달리 빌드 결과물은 사용자가 운영 모드로 바꿀 수 없다 |
| D2 | 데모는 목업 스크립트 로드에 실패해도 WebSocket으로 넘어가지 않고 오류만 표시한다 | "데모는 서버를 호출하지 않는다"는 보장을 실패 경로에서도 지킨다 |
| D3 | 빌드 도구는 파이썬 표준 라이브러리 스크립트 하나로 만들었다(npm, 번들러 도입 없음) | 저장소가 파이썬 프로젝트이고 프론트엔드는 번들 없는 단일 HTML이다. 명령 하나(`python3 scripts/build_demo.py`)로 끝난다 |
| D4 | CSP는 `'unsafe-inline'` 없이 인라인 스크립트·스타일의 **해시**로 허용한다. `default-src 'none'`에 필요한 것만 `'self'`로 연다 | 요구사항은 `connect-src 'self'`이지만, 해시 방식이면 같은 비용으로 XSS 방어까지 강해진다. 인라인 `style=` 속성과 이벤트 핸들러 속성이 없는 것도 확인했다 |
| D5 | 같은 CSP를 `<meta>`로도 넣는다(`frame-ancestors`만 헤더 전용) | `_headers`는 Netlify·Cloudflare Pages에서만 적용된다. GitHub Pages나 `http.server`에서도 `connect-src 'self'`가 걸리게 한다 |
| D6 | Pretendard CDN을 없애고 **subset 폰트를 self-host**했다. 운영 모드도 같은 폰트를 쓴다 | "같은 출처가 아닌 요청 0건" 요구를 만족하려면 외부 폰트를 쓸 수 없다. 전체 패키지(3MB, 92개 파일) 대신 실제 쓰는 471자만 남겨 103 KiB로 줄였다 |
| D7 | subset 폰트 이름을 **Kimgap Sans**로 바꿨다(저작권·상표·디자이너 표기는 유지) | Pretendard는 OFL 1.1에 "Pretendard"가 Reserved Font Name이고, subset은 수정본이다. 보수적으로 해석해 이름을 바꾸고 `OFL.txt`를 함께 배포한다 |
| D8 | 데모와 목업에서 출금 한도는 필드 자체를 없애고, 버튼은 "출금한도 · 데모 제외"로 비활성화했다. 모달에는 "데모 데이터에는 출금 한도를 넣지 않았다"는 안내를 표시한다 | 요구사항(출금 한도 금액 금지). 가짜 숫자를 보여주는 것보다 빈칸과 이유를 보여주는 편이 오해가 적다 |
| D9 | 데모는 3초, `?mock=1`은 5초(운영 기본값과 같음) 간격으로 갱신한다 | 데모는 "살아 있는" 느낌을 주려고 조금 빠르게 했다. 운영 페이지 목업은 실제 주기와 맞췄다 |
| D10 | 상대 경로로 바꿔 서브경로(예: GitHub Pages `/kimgap/`)에서도 동작하게 했다. 목업의 `/api/*` 가로채기도 경로 끝 기준으로 맞춘다 | 운영 FastAPI(`/` → `/static/…`)에서도 같은 상대 경로가 그대로 풀린다. 대신 운영에서 `/static/index.html`로 직접 열면 자산이 404가 되므로 진입점은 `/`로 고정한다(README에 명시) |
| D11 | 빌드 스크립트는 CSP `<meta>` 삽입 위치를 못 찾거나, 해시할 수 없는 인라인 코드(속성 달린 script·style, `on*=`, `style=`)가 있으면 **실패**한다 | 리뷰 지적 반영. CSP가 빠진 채 빌드되거나, 데모가 CSP에 막혀 조용히 깨지는 것을 막는다 |
| D12 | 데모에서는 푸터의 "WebSocket /ws/gaps로 수신" 문장을 숨긴다 | 데모 안내와 서로 어긋나 보이지 않게 한다 |

### 검증 결과

| 검사 | 명령 | 결과 |
|---|---|---|
| **30초 네트워크 관찰** (1440, Playwright Chromium) | `node demo_check.mjs http://127.0.0.1:8766/` (`dist/`를 `_headers` 적용 정적 서버로 서빙) | ✅ **같은 출처가 아닌 요청 0건**, WebSocket 0건, `/api`·`/ws` 요청 0건, CSP 위반 0건, 콘솔·페이지 오류 0건. 30초 동안 전체 요청은 6건(`/`, `mock-data.js`, 폰트, 로고 3개) |
| 응답 헤더 CSP | 위 스크립트 | ✅ `connect-src 'self'` 포함, `default-src 'none'`, 해시 기반 script·style |
| 실시간 갱신 흉내 | 3초 간격 11회 샘플 | ✅ BTC 업비트 가격 11가지, BTC 김프 10가지, 환율 7가지 값. 갱신 시각 매번 바뀜 |
| 데모 표시와 출금 한도 | 위 스크립트 | ✅ 배지 "데모 데이터로 동작 중", 하단 안내 표시, 390px에서 배지 잘림 없음, 버튼 비활성, 모달의 한도 값은 모두 "—" |
| 운영 모드 회귀 | FastAPI 배치(`/`+`/static`)를 흉내 낸 정적 서버 | ✅ `live`에서는 `ws://…/ws/gaps` 연결을 시도하고 목업을 로드하지 않음(백엔드가 없어 "재연결 중…"이 정상). `?mock=1`은 데모 데이터로 동작. 두 경우 모두 외부 요청은 0건(폰트도 self-host) |
| 빌드 재현성 | 두 번 빌드 후 모든 파일 SHA 비교 | ✅ 동일 |
| 빌드 안전장치(음성 테스트) | 임시 사본에 문제를 넣고 빌드 | ✅ charset 표기 변경, `onclick=`, `style=`, `<script type="module">` 4건 모두 빌드가 오류로 멈춤 |
| 코드 리뷰(서브에이전트, 읽기 전용) | `git diff main` + 신규 파일 | High·Medium 0건. Low 3·Nit 3건은 모두 반영(D10~D12, 문서 수정). 리뷰어가 따로 헤드리스 Chrome을 돌렸을 때도 외부·백엔드 요청 0건, CSP 해시 일치, 2,000틱 동안 김프 이탈 최대 0.5%p |
| JS 구문 | `node --check` (인라인, `mock-data.js`) | ✅ |
| HTML | `html-validate` (소스와 `dist/index.html`, `void-style: selfclose`) | ✅ |
| 파이썬 | `pyflakes scripts/`, `py_compile` | ✅ |
| ESLint | `eslint inline.js mock-data.js` | ❌ 오류 1·경고 2. 기존 운영 WebSocket 코드(`disconnectWs`의 `catch (_) {}`)에서 나오며, 이번 작업 범위 밖이라 그대로 두었다(아래 남은 이슈 1) |

**스크린샷(다시 저장):** `~/portfolio/assets/kimgap/`에 아래 "스크린샷 목록"과 같은 9개 파일을 **정적 데모 빌드(`dist/`)** 로 다시 찍었다(1440 × 5, 390 × 4, reduced-motion).

위 결과는 리뷰 반영 뒤의 최종 빌드로 다시 실행한 값이다. Playwright 검증 스크립트(`demo_check.mjs`)와 `_headers`를 적용하는 검증용 정적 서버는 작업용 임시 폴더에서 실행했고 저장소에는 넣지 않았다(Node·Playwright 의존성을 저장소에 들이지 않기 위해).

### 정적 데모에서 남은 이슈

- subset 폰트에 없는 글자(나중에 추가될 UI 문구, 서버가 보내는 새 한글 메시지)는 시스템 폰트로 표시된다. 문구를 바꾸면 `scripts/subset_font.py`를 다시 실행해야 한다.
- `_headers`는 Netlify·Cloudflare Pages 전용 형식이다. 다른 호스팅에서는 `<meta>` CSP만 적용되고, 이 경우 `frame-ancestors`(클릭재킹 방어)는 빠진다.
- 데모의 가격은 정해진 기준값 근처에서만 움직인다. 실제 시장 흐름(추세, 급등락)은 흉내 내지 않는다.

---

## 요약

### 변경 요약

| 파일 | 내용 |
|---|---|
| `gap_dashboard/static/index.html` | DESIGN.md 토큰(표면·텍스트·상승/하락·민트 강조·간격·반경)으로 전면 재작성. 앱 바, KPI 스트립, 해외 시세 수신 칩, 세그먼트 탭과 도구 줄, 고정 헤더 표, 제한·중단 2열 카드, 코인 상세 모달(모바일은 바텀시트)로 구성. 목업 모드(`?mock=1`) 부트스트랩 추가 |
| `gap_dashboard/static/mock-data.js` (신규) | 목업 모드 전용. `/ws/gaps` 페이로드와 같은 모양의 가상 데이터를 브라우저 안에서 생성하고, 주기적으로 가격을 흔들어 갱신. 목업 모드에서만 `/api/*` fetch를 가로채 가상 응답 반환 (static-demo에서 평균 회귀 변동, 출금 한도 제거로 변경됨) |
| `UI_REBUILD_NOTES.md` (신규) | 이 문서 |
| `~/portfolio/DESIGN.md` (저장소 밖) | §2.4 민트 확정과 강조 토큰(`--accent`, `--accent-hover`, `--on-accent`, `--accent-bg`, `--focus-ring`) 추가, §2.5 `--series-1`을 민트로 교체, §5.7 Primary 버튼, §7 대비 검증, §8 체크리스트 갱신 |

**수정하지 않은 것:** `gap_dashboard/main.py`(백엔드·거래소 API·키·출금 한도 로직), 프론트엔드의 API 클라이언트 함수(`gapsWsUrl`, `disconnectWs`, `connectWs`, `startRealtime`, `btnWl` 클릭 핸들러의 `fetch("/api/refresh-limits")`)는 HEAD와 글자 그대로 같습니다.

### 스크린샷 목록

`~/portfolio/assets/kimgap/` (목업 모드, Playwright Chromium, deviceScaleFactor 2, reduced-motion)

| 파일 | 뷰포트 | 화면 |
|---|---|---|
| `kimgap-1440-overview.png` | 1440 × 900, 전체 페이지 | 기본 화면(업비트 × 빗썸 탭) + 제한·중단 카드 |
| `kimgap-1440-spot.png` | 1440, 전체 페이지 | 해외 현물 비교 탭 |
| `kimgap-1440-futures.png` | 1440, 전체 페이지 | 해외 선물 비교 탭 |
| `kimgap-1440-issues-filter.png` | 1440 × 900 | "입출금 이슈만" 필터 켠 상태 |
| `kimgap-1440-coin-modal.png` | 1440 × 900 | 코인 상세 모달(ORCA: 입출금 제한 사례) |
| `kimgap-390-overview.png` | 390 × 844 | 모바일 첫 화면 |
| `kimgap-390-overview-full.png` | 390, 전체 페이지 | 모바일 전체 |
| `kimgap-390-spot.png` | 390 × 844 | 모바일 해외 현물 탭(표 영역으로 스크롤) |
| `kimgap-390-coin-modal.png` | 390 × 844 | 모바일 바텀시트 모달(SAND: 빗썸 전 네트워크 중단 사례) |

### 남은 이슈

1. (fix-exchanges 후속 정리 12에서 해소) **ESLint 오류 1건이 남아 있음(수정 금지 범위).** `disconnectWs()`의 `catch (_) {}`(no-empty)와 `catch (e)` 미사용 경고 2건은 원본 HEAD 코드에 이미 있던 것이고, API 클라이언트 로직은 수정하지 말라는 규칙에 따라 그대로 두었다. 고치려면 `catch { /* 이미 닫힌 소켓 */ }` 정도로 바꾸면 된다. HEAD 원본에도 같은 오류가 있음을 확인했다(아래 검증 참고).
2. **실데이터 모드는 화면으로 확인하지 못했다.** 규칙상 백엔드를 띄우지 않았으므로 실제 페이로드(300개 이상 행, `wallet.mode = off/failed`, `usdt_krw = null`)로 렌더링된 모습은 보지 않았다. 목업 스키마는 `main.py`의 `_compute_gaps_payload()`를 읽고 맞췄다. 일반 모드가 기존대로 `ws://…/ws/gaps`에 연결을 시도하고 목업 스크립트를 로드하지 않는 것만 확인했다.
3. **저장소에 기존 테스트·린트 설정·빌드 스크립트가 없다.** 아래 검증은 스크래치패드에 임시로 설치한 도구로 실행했다. 저장소에 lint/test 설정은 추가하지 않았다.
4. `index.html`의 커밋에는 작업 전부터 있던 **사용자의 미커밋 UI 변경**(제목을 "차익 대시보드"로 변경, 디버그 `console.log` 제거)이 함께 들어갔다. 파일을 통째로 다시 썼기 때문에 분리할 수 없었고, 두 변경 모두 새 UI에 유지했다.
5. ~~Pretendard 폰트를 `cdn.jsdelivr.net`에서 불러온다.~~ → static-demo에서 해소: 저장소 안의 subset 폰트(`Kimgap Sans`)를 쓰고 CDN 요청은 없다.
6. Binance 로고 파일이 저장소에 없어 머리글자 모노그램("B")으로 표시한다(원본도 로고 없이 점으로 표시했다).
7. 1180px 이하 태블릿 폭에서는 KPI가 3+2 배치라 둘째 줄 오른쪽 한 칸이 빈다. 390·1440 요구 범위 밖이라 그대로 두었다.
8. `.claude/launch.json`(목업 정적 서버 실행 설정)을 만들었지만 앱 코드가 아니라서 커밋하지 않았다. 필요 없으면 지워도 된다.
9. **정렬 동작은 HEAD와 동일하게 유지했지만 개선 여지가 있다.** 김프·역프 정렬에서 김프가 없는(`null`) 종목은 `Number(null) = 0` 때문에 0% 위치에 섞인다. 기존 코드의 `av == null` 분기가 뜻하는 동작은 "맨 뒤로 보내기"로 보이지만, 정렬은 데이터 처리 동작이라 이번 UI 작업에서는 바꾸지 않았다. 원하면 `kpNum`에 `v == null` 검사를 넣으면 된다.
10. DESIGN.md는 저장소 밖(`~/portfolio`)에 있고 git 저장소가 아니라서 변경 이력이 남지 않는다.

---

## 목업 데이터 모드 사용법

백엔드 없이 정적 파일만 서빙한다. 거래소나 서버 API는 호출하지 않는다.

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory gap_dashboard
```

> **static-demo 이후 변경:** 자산 경로가 상대 경로(`static/…`)로 바뀌어 위 방식(`/static/index.html?mock=1`)으로는 더 이상 열리지 않는다. 대신 `python3 scripts/build_demo.py`로 `dist/`를 만들어 띄우거나, FastAPI 서버에서 `/?mock=1`을 연다(`/static/index.html?mock=1`은 상대 경로가 `/static/static/…`으로 풀려 동작하지 않는다). 문서 맨 위 "정적 데모" 절 참고.

- 목업 데이터는 모두 가상의 값이다. 가격과 김프는 실제 시세가 아니며, 지갑 주소나 잔고는 들어 있지 않다. (처음에는 가짜 출금 한도 값이 있었으나 static-demo에서 **출금 한도 필드를 완전히 제거**했다.)
- 시나리오를 넣어 두었다: ORCA(업비트 출금 불가, 빗썸 입금 불가), SAND·MED(빗썸 전 네트워크 중단), STRAX(업비트 전 네트워크 중단), SEI(빗썸 출금 불가), MOVE(업비트 입금 불가), ZRO(네트워크 일부만 중단, 집계로는 가능), BORA(빗썸 지갑 정보 없음), KAIA·MED·MLK·BORA(해외 미상장이라 김프 없음), BTT(해외 심볼 BTTC 매핑).
- (static-demo 이후) 목업·데모에서는 "출금한도" 버튼이 "출금한도 · 데모 제외"로 비활성화된다.
- 앱 바의 연결 상태에 앰버색 "데모 데이터로 동작 중" 표시가 떠서 실데이터와 구분된다(처음 표기는 "목업 데이터").

---

## 결정과 이유

| # | 결정 | 이유 |
|---|---|---|
| 1 | 단일 `index.html` 구조와 순수 JS를 유지했다(프레임워크·빌드 도입 없음) | 기존 저장소 관례(CLAUDE.md "single-page application, vanilla JS")이고, FastAPI가 파일을 그대로 서빙한다. UI만 바꾸라는 범위에도 맞다 |
| 2 | 목업 데이터는 별도 파일로 두고 `?mock=1`일 때만 동적으로 `<script>`를 삽입한다 | 운영 모드에서는 목업 코드가 로드되지 않게 하려는 것이다. 쿼리 파라미터 없이 자동으로 목업으로 넘어가면 실데이터 장애를 가릴 수 있어서 명시적 스위치로 했다 |
| 3 | 목업 모드에서만 `window.fetch`를 감싸 `/api/*`에 가상 응답을 준다 | 원본 `btnWl` 핸들러를 한 글자도 바꾸지 않고도 목업에서 동작하게 하려는 것이다. `/api/` 외 요청은 원래 fetch로 넘긴다 |
| 4 | "프론트엔드 개발 서버"는 `python -m http.server`로 `gap_dashboard/` 디렉터리만 서빙했다 | 프론트 번들러가 없고, uvicorn으로 `main.py`를 띄우면 시작 시 거래소 WebSocket·REST에 연결한다(실 API 호출 금지 규칙). 정적 서버에서 `/static/…` 경로가 FastAPI 마운트와 같게 유지된다 |
| 5 | 김프·괴리는 한국식 색으로 표시했다: ▲ 빨강 = 국내가 비쌈, ▼ 파랑 = 국내가 쌈, – 회색 = 보합. 부호 화살표는 항상 같이 쓴다 | DESIGN.md §2.3. 원본은 +초록/−빨강이어서 한국식과 반대였다 |
| 6 | 업비트 파랑(`#0c8ce9`)과 빗썸 주황(`#f37321`) 브랜드 색을 제거하고 거래소는 텍스트 라벨로 구분했다 | 업비트 파랑이 하락 파랑과, 빗썸 주황이 경고 앰버·상승 빨강과 충돌한다. DESIGN.md 원칙 "색은 신호에만" |
| 7 | 입출금 상태: 가능은 무채색 아웃라인 "입/출", 불가는 앰버 채움과 테두리에 굵은 글씨, 알 수 없음은 점선 | 원본 초록/빨강 점에서 빨강은 상승색과, 초록은 민트 강조색과 겹친다. DESIGN.md는 경고 앰버를 허용하고, 채움과 아웃라인의 형태 차이로 색 없이도 구분된다. 처음에는 취소선을 넣었는데 작은 한글("입")에서 다른 글자처럼 보여서 뺐다 |
| 8 | 입출금 이슈 행은 왼쪽 2px 앰버 바만 표시한다. 전부 가능한 행의 초록 배경은 없앴다 | 소음을 줄이려는 것이다. 정상 행은 기본 상태이므로 강조하지 않는다 |
| 9 | 위험 배지는 "주의"(1–3%, 앰버 아웃라인)와 "위험"(3% 이상, 앰버 채움)만 남기고 "안전"·"역프" 배지는 없앴다 | 방향(역프)은 ▼ 파랑과 부호가 이미 전달한다. "안전"은 모든 행에 붙어 소음만 늘린다. 배지 색도 상승·하락과 겹치지 않게 앰버로 통일했다 |
| 10 | 민트 강조색은 선택된 탭, 토글 켜짐, 포커스 링, 실시간 연결 점, 브랜드 마크에만 썼다 | DESIGN.md §2.4 "강조색은 선택·주 액션"이다. "출금한도 새로고침"은 주 액션이 아니므로 Secondary 버튼으로 했다 |
| 11 | 원본의 환율 바 + 거래소 카드를 5칸 KPI 스트립 + "해외 시세 수신" 칩 줄로 재구성했다. KPI에 **BTC 김프**를 새로 넣었다 | DESIGN.md §4.3 KPI 스트립 패턴이다. BTC 김프는 `gaps` 행의 `kp_upbit`/`kp_bithumb` 값을 그대로 보여주는 표시일 뿐 새 계산 로직이 아니다 |
| 12 | 표는 가로선만 두고, 헤더를 고정(표 영역 `max-height: min(72vh, 880px)`)했다. 모바일은 가로 스크롤에 종목 열을 고정했다 | DESIGN.md §5.3. 모바일 카드형 목록으로 바꾸면 렌더러가 두 벌이 되므로, 같은 표를 유지하고 고정 열로 가독성을 확보했다 |
| 13 | 도메스틱 표 2단 헤더(colspan)를 1단으로 합치고 입금·출금을 한 칸("입 출")으로 묶었다 | 열이 12개에서 10개로 줄어 밀도가 올라가고 세로 구분선이 필요 없어진다 |
| 14 | "입출금 이슈만" 토글은 해외 현물·선물 탭에서 비활성화한다(툴팁으로 이유 표시) | 원본에서도 해외 탭에서는 필터가 적용되지 않았는데 켤 수는 있어 혼란스러웠다. 동작은 그대로 두고 상태만 드러냈다 |
| 15 | 모달 섹션 순서를 현재 시세 → 네트워크별 입출금 → 출금 한도 → 해외 상장으로 바꾸고, "현재 시세" 요약을 추가했다 | 행을 눌러 들어온 사용자에게 가장 먼저 필요한 것은 가격·김프와 입출금 가능 여부다. 요약은 행에 이미 있는 필드만 보여준다 |
| 16 | 표 행에 `tabindex="0"`과 Enter/Space 열기를 추가했고, 모달을 닫으면 포커스가 원래 자리로 돌아간다 | 키보드 접근성. 원본은 마우스 클릭으로만 열 수 있었다 |
| 17 | 가격 셀이 바뀌면 400ms 동안 `--up-bg`/`--down-bg`로 깜빡인다. `prefers-reduced-motion`이면 끈다 | DESIGN.md §6 |
| 18 | `escHtml`이 따옴표(`"`)도 이스케이프하게 했고, `data-symbol` 등 속성에 넣는 심볼도 이스케이프한다 | 원본은 `data-symbol="${r.symbol}"`에 이스케이프 없이 넣었다. UI 렌더링 방어 강화이며 데이터 흐름은 바뀌지 않는다 |
| 19 | 폰트를 DM Sans와 Syne(Google Fonts)에서 Pretendard Variable(jsDelivr)로 바꿨다 (static-demo에서 self-host subset으로 다시 변경) | DESIGN.md §3.1 한글 UI 권장 서체. 모든 숫자에 `tabular-nums`를 적용했다 |
| 20 | 헤더의 갱신 시각은 `HH:MM:SS` 고정폭으로 표시한다(전체 일시는 툴팁) | ko-KR 로캘의 "4시 45분 44초" 표기는 길고 폭이 계속 바뀐다 |
| 21 | 기존 사용자 미커밋 변경 중 `index.html` 부분만 이번 커밋에 포함했고, 나머지(`main.py` 등)는 커밋하지 않았다 | `index.html`은 전면 재작성이라 분리가 불가능했다. 백엔드 변경은 이번 작업 범위 밖이고 사용자가 진행 중이던 작업이다 |
| 22 | 정렬용 `kpNum`은 HEAD와 똑같이 두고(`null`이 0%로 섞임), 표시용 `numOrNull`을 따로 만들었다 | 리뷰에서 처음 버전이 `kpNum`을 바꿔 김프 없는 종목의 정렬 위치가 HEAD와 달라진 것을 찾았다. 정렬은 표시가 아니라 동작이므로 동등성을 우선했다. HEAD 동작이 의도에 맞는지는 남은 이슈 9에 적었다 |
| 23 | 목업 모드는 `?mock=1`일 때만 켜진다(`?mock=0`은 일반 모드) | 사양 문구와 맞추고 오작동을 막는다 |
| 24 | 목업 모드에서는 fetch 가로채기가 설치될 때까지 "출금한도 새로고침" 버튼을 비활성화한다 | 목업 스크립트가 로드되기 전에 버튼을 누르면 원래 fetch로 실제 `/api/refresh-limits`가 나갈 수 있는 경합을 막는다(FastAPI에서 `/?mock=1`로 연 경우) |
| 25 | 민트는 앱 브랜드 마크(로고 1곳)에도 쓰고, 이를 DESIGN.md §2.4 사용처 목록에 명시했다. "입출금 연동 OK" 상태 점은 무채색으로 바꿨다 | 상태 표시에 민트를 쓰지 않는다는 규칙을 지키려는 것이다. 로고는 신호가 아니라 정체성 표시라서 예외로 문서화했다 |
| 26 | 5초마다 다시 그린 뒤에도 키보드 포커스가 있던 행(같은 표, 같은 심볼)에 포커스를 되돌린다 | 행 키보드 조작(결정 16)이 실시간 갱신 때문에 풀리지 않게 한다 |
| 27 | 모바일(순번 열 숨김)에서는 이슈 앰버 바와 포커스 바를 종목 열에 그린다 | `td:first-child`가 숨겨진 순번 셀을 가리켜 바가 사라지던 문제를 고쳤다 |

---

## 검증

이 저장소에는 빌드 스크립트, 린트 설정, 테스트가 없다(`tests/`, `pytest.ini`, `pyproject.toml`, `package.json`, `.eslintrc*` 모두 없음). 그래서 아래 검사를 스크래치패드의 임시 도구로 실행했다.

| 검사 | 명령 | 결과 |
|---|---|---|
| JS 구문 (인라인 스크립트) | `node --check inline.js` (index.html의 `<script>` 추출) | ✅ 통과 |
| JS 구문 (목업) | `node --check gap_dashboard/static/mock-data.js` | ✅ 통과 |
| 백엔드 구문 (수정 안 함, 실행 안 함) | `.venv/bin/python -m py_compile gap_dashboard/main.py` | ✅ 통과 (import·실행 없이 컴파일만) |
| HTML 검증 | `html-validate --config {recommended + void-style: selfclose}` | ✅ 통과. `void-style`만 기존 파일 관례인 self-closing(`<meta />`)에 맞췄다. 처음 실행에서 나온 `button` type 누락과 빈 `<h3>`는 고쳤다 |
| ESLint (`@eslint/js` recommended, browser globals) | `eslint inline.js mock-data.js` | ❌ 오류 1, 경고 2. 모두 원본 그대로 둔 API 클라이언트 코드(`disconnectWs`의 `catch (_) {}`, `btnWl` 핸들러의 `catch (e)`)에서 나온다. HEAD 원본도 같은 오류 1건과 경고 3건이 나온다(이번 수정으로 `formatTime` 미사용 경고는 없어졌다). 남은 이슈 1 참고 |
| 목업 모드 스모크와 캡처 (Playwright) | `node capture.mjs <assets/kimgap>` | ✅ 확인한 문제 0건. 콘솔 오류·경고 0, pageerror 0, WebSocket 연결 0, 백엔드 `/api`·`/ws` 요청 0, 외부 요청은 폰트 CDN뿐이다. 1440·390에서 페이지 가로 넘침이 없다. 탭 전환, 이슈 필터(결과 1행 이상), 검색 빈 상태 문구, 모달 열기와 Esc 닫기가 동작한다. 출금한도 버튼은 다음 틱에 "로딩…"을 표시한다. 5초 재렌더링 뒤에도 행 포커스가 유지되고 Enter로 모달이 열린다. 390에서 이슈 행 앰버 바가 종목 열에 있다. `?mock=0`은 목업을 로드하지 않는다 |
| 일반 모드 회귀 (Playwright) | `node normal.mjs` | ✅ `mock-data.js`를 로드하지 않고 `ws://127.0.0.1:8765/ws/gaps`에 연결을 시도한다(정적 서버라 "재연결 중…"이 정상). pageerror 0 |
| API 클라이언트·데이터 처리 무수정 | HEAD와 함수 본문을 중괄호 짝으로 잘라 비교 | ✅ `gapsWsUrl`, `disconnectWs`, `connectWs`, `startRealtime`, `btnWl` 클릭 핸들러, `updateWlButton`, `kpNum`, `rowHasPauseIssue`, `filterRowsByTicker`, `findGapRow`가 모두 동일하다. `sortRows`는 사용자가 작업 전에 지운 디버그 `console.log` 3줄만 다르고 로직은 같다 |

## 리뷰 (서브에이전트, 읽기 전용)

치명적인 결함(JS 런타임 오류, XSS, API 클라이언트 변경, 목업 모드의 API·WS 누출)은 없었다. 리뷰어는 DOM 스텁 하네스로 탭 3개 × 정렬 5개 × 필터 on/off × 검색어 4개(XSS 문자열 포함)와 엣지 페이로드(`wallet.mode=off`, `usdt_krw=null`, 필드 누락, 악성 심볼)를 돌렸고, 오류 0건과 이스케이프되지 않은 출력 0건을 확인했다. 지적 7건은 모두 반영했다.

| # | 등급 | 지적 | 조치 |
|---|---|---|---|
| 1 | 중간 | `kpNum` 변경으로 김프 없는 종목의 정렬 위치가 HEAD와 달라짐 | HEAD 구현으로 되돌리고 표시용 `numOrNull`을 분리했다(결정 22) |
| 2 | 중간 | 760px 이하에서 이슈 행 바와 포커스 바가 숨겨진 순번 셀에 그려져 보이지 않음 | 모바일에서는 종목 열에 그린다(결정 27). Playwright로 확인 |
| 3 | 낮음 | 5초 재렌더링 때 행 키보드 포커스 유실 | 포커스를 복원한다(결정 26). Playwright로 확인 |
| 4 | 낮음 | 민트를 브랜드 마크와 "연동 OK" 점에 사용 | 연동 점은 무채색으로 바꾸고, 브랜드 마크는 DESIGN.md에 명시했다(결정 25) |
| 5 | 낮음 | `?mock=0`도 목업 모드가 됨 | `get("mock") === "1"`로 바꿨다(결정 23) |
| 6 | 낮음 | 목업 스크립트 로드 전 버튼 클릭 시 실제 POST 가능성 | 로드 전에는 버튼을 비활성화한다(결정 24) |
| 7 | 낮음 | `.m-row:first-of-type` 선택자가 맞는 요소가 없어 불필요한 구분선이 생김 | `.m-box-head + .m-row`로 고쳤다 |
| 참고 | — | 주석의 "취소선" 문구와 CSS 불일치, 목업 `cached_count`(38)와 `wl_count`(39) 불일치 | 주석을 고쳤고, 목업 한도 개수를 한 상수(`LIMIT_TOTAL`)로 통일했다 |
