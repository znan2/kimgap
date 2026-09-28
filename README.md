# 차익 대시보드 (kimgap)

업비트·빗썸 가격 괴리와 해외 거래소 5곳(Binance, Bybit, Bitget, OKX, Gate.io)의 현물·USDT 무기한 선물 대비 김치 프리미엄을 실시간으로 보여주는 대시보드입니다.

## 데모 실행·빌드 (백엔드 없이)

```bash
python3 scripts/build_demo.py                      # dist/ 에 정적 파일 생성 (표준 라이브러리만 사용)
python3 -m http.server 8080 --directory dist       # 로컬에서 확인: http://127.0.0.1:8080/
```

- `dist/`는 정적 파일만 있어서 Netlify, Cloudflare Pages, GitHub Pages 같은 정적 호스팅에 폴더째 올리면 됩니다. `dist/`는 git에서 제외됩니다.
- 데모는 **서버 API, WebSocket, 거래소 API를 호출하지 않습니다.** 브라우저 안에서 가상 데이터를 만들고 3초마다 갱신해 실시간 화면을 흉내 냅니다. 화면 상단에 "데모 데이터로 동작 중"이 표시됩니다.
- 데모 데이터에는 실제 잔고, 지갑 주소, 출금 한도 금액이 없습니다.
- 보안 헤더
  - `dist/_headers`(Netlify·Cloudflare Pages 형식)에 CSP `connect-src 'self'`를 비롯한 헤더를 넣습니다.
  - `_headers`를 지원하지 않는 호스팅(GitHub Pages, `http.server`)을 위해 같은 CSP를 `<meta>`로도 넣습니다. `frame-ancestors`는 헤더에만 적용됩니다.

## 실행 모드

같은 `gap_dashboard/static/index.html`을 설정 하나로 나눠 씁니다.

| 모드 | 설정 | 동작 |
|---|---|---|
| 운영 (`live`) | `<meta name="kimgap-mode" content="live">` (소스 기본값) | 서버 `WebSocket /ws/gaps`로 실데이터 수신 |
| 데모 (`demo`) | 빌드 스크립트가 `content="demo"`로 바꿈 | `static/mock-data.js` 가상 데이터만 사용, 네트워크 호출 없음 |
| 운영 페이지 목업 확인 | 운영 URL에 `?mock=1` | 데모와 같은 가상 데이터로 렌더링(개발·스크린샷용) |

## 실데이터 모드 실행

```bash
pip install -r requirements.txt
cp .env.example .env        # 거래소 API 키(선택)를 채운다
uvicorn gap_dashboard.main:app --host 127.0.0.1 --port 8000
```

- 브라우저에서는 `http://127.0.0.1:8000/`(루트)로 엽니다. 자산 경로가 상대 경로(`static/…`)라서 `/static/index.html`로 열면 폰트·로고가 404가 됩니다.
- 해외 5개 거래소는 모두 **공개 API만** 씁니다(API 키 없음). 기동 시 REST로 USDT 현물·무기한 심볼 목록을 받고, 티커 WebSocket으로 가격을 유지하며, 부족하면 REST 티커로 채웁니다.
- API 키가 없어도 시세·김프는 동작합니다. 키가 있으면 네트워크별 입출금 상태와 코인별 출금 가능 여부를 함께 보여줍니다(출금 한도 금액은 수집·공개하지 않음).
- 키는 **조회 권한만** 주고(주문·출금·입금 권한은 끔), 허용 IP를 실행 서버로 제한하세요. 코드는 `GET /v1/status/wallet`, `GET /v1/withdraws/chance`만 호출합니다.
- 공개 서버로 운영하려면 아래 "공개 서버 운영" 절을 확인하세요.

## 공개 서버 운영

아래 보호 장치는 코드에 적용돼 있고, 별도 설정 없이도 안전한 쪽이 기본값입니다. 변수 이름은 `.env.example`에 있습니다.

| 항목 | 적용 내용 | 설정(환경변수, 기본값) |
|---|---|---|
| 거래소 호출과 요청 분리 | 거래소 API는 서버 내부 스케줄러만 호출합니다. `/api/gaps`와 `/ws/gaps`는 마지막 캐시만 반환하므로, 요청이 몇 번 오든 거래소 호출 수는 늘지 않습니다. 첫 페이로드가 준비되기 전에는 `/api/gaps`가 `503`을 돌려줍니다 | 공개 시세 `GAP_WS_INTERVAL_SEC`(5초), 지갑 입출금 상태(비공개) `WALLET_STATUS_INTERVAL_SEC`(60초, 최소 30), 출금 가능 정보(비공개) `WITHDRAW_INFO_INTERVAL_SEC`(21600초, 최소 600) |
| 관리자 엔드포인트 | `POST /api/refresh-limits`(출금 가능 정보 즉시 갱신)와 `GET /api/limits-status`는 `ADMIN_TOKEN`을 설정하지 않으면 경로가 등록되지 않아 **어떤 메서드로도 404**입니다. 토큰은 ASCII 문자로 정하세요. 설정하면 `X-Admin-Token` 헤더가 필요하고(없으면 401, 틀리면 403), 갱신은 쿨다운이 지나야 다시 할 수 있습니다(`429` + `Retry-After`). 공개 페이지에는 버튼이 없습니다 | `ADMIN_TOKEN`(비움), `ADMIN_REFRESH_COOLDOWN_SEC`(600초, 최소 60) |
| 출금 정보 공개 범위 | 공개 응답에는 코인별 `withdraw_status`의 출금 가능 여부(`upbit_can_withdraw`, `bithumb_can_withdraw`, 불리언)만 들어 있습니다. 한도·잔여·최소 금액은 서버가 수집하지도 않습니다. 거래소 오류 원문 대신 `auth_error`, `rate_limited`, `upstream_error` 코드만 공개합니다 | — |
| API 문서 | `/docs`, `/redoc`, `/openapi.json`은 기본으로 꺼져 있습니다 | `ENABLE_API_DOCS=1`일 때만 켜짐 |
| CORS | 기본은 CORS 헤더 없음(같은 출처만)입니다. 설정한 출처에만 GET을 허용하고, 자격 증명은 허용하지 않습니다. 설정하면 브라우저 WebSocket의 `Origin`도 같은 목록으로 제한하므로 **대시보드 자신의 출처도 목록에 넣어야** 합니다 | `CORS_ALLOW_ORIGINS`(쉼표 구분, 예: `https://example.com`) |
| 요청 속도 제한 | IP별 분당 요청 수를 넘으면 `429`와 `Retry-After`를 돌려줍니다. WebSocket 연결 시도도 같은 한도에 포함됩니다. `/static/*`은 제외합니다 | `RATE_LIMIT_PER_MIN`(120) |
| WebSocket 연결 상한 | 전체와 IP별 동시 연결 수를 넘으면 연결을 거부합니다(연결 수락 전 거부라 클라이언트에는 HTTP 403으로 보임). 끊긴 연결의 자리는 바로 반납됩니다 | `WS_MAX_CONNECTIONS`(200), `WS_MAX_PER_IP`(5) |
| 응답 압축 | 1KB 이상 HTTP 응답은 gzip으로 보냅니다(`/api/gaps` 약 2.4MB → 약 0.3MB). WebSocket은 uvicorn의 permessage-deflate가 압축합니다 | — |

- **리버스 프록시 뒤에서 실행할 때**: 속도 제한과 연결 상한은 클라이언트 IP 기준입니다. uvicorn은 기본적으로 `127.0.0.1`에서 온 `X-Forwarded-For`를 신뢰해 실제 IP로 바꿉니다(`--proxy-headers`, `--forwarded-allow-ips`). 프록시가 다른 주소에 있으면 `--forwarded-allow-ips`에 그 주소를 지정하세요. 지정하지 않으면 모든 사용자가 프록시 IP 하나로 묶여 제한됩니다.
- **거래소 키**: 조회 권한만 주고, 허용 IP를 서버로 제한하세요.

## 테스트

```bash
pip install -r requirements-dev.txt
python -m pytest
```

테스트는 `.env`를 읽지 않고(`KIMGAP_SKIP_DOTENV=1`), 거래소로 나가는 네트워크 호출을 모두 막은 상태에서 실행됩니다.

### `data/*.json` 스냅샷이 필요한가요?

**필요 없습니다.**

- `gap_dashboard/main.py`는 `data/` 폴더를 읽지도 쓰지도 않습니다.
- 입출금 상태와 네트워크 정보는 요청마다 업비트·빗썸 `/v1/status/wallet`에서 실시간으로 받습니다.
- 해외 거래소 심볼 목록은 서버 기동 시 각 거래소 공개 API에서 받습니다.

`data/raw_networks_*.json`, `rpc_mapping_*.json`, `unique_networks_*.json`은 초기 커밋(2026-04-07)에 함께 들어간 참고용 스냅샷입니다.

- `raw_networks`: 거래소별 코인·네트워크 입출금 상태
- `rpc_mapping`: 체인별 공개 RPC 주소
- `unique_networks`: 네트워크 목록

이 파일들을 만든 스크립트는 저장소와 히스토리 어디에도 없어서 **재생성 방법은 제공하지 않습니다.** 같은 정보가 필요하면 `/v1/status/wallet` 응답을 그대로 저장하면 됩니다. 스냅샷은 지금 `.gitignore`(`data/*.json`)로 제외됩니다.

## 폰트

UI 폰트는 Pretendard(SIL OFL 1.1)에서 쓰는 글자만 남긴 subset `Kimgap Sans`를 저장소 안에 두고 씁니다. CDN을 쓰지 않습니다. 자세한 내용은 `gap_dashboard/static/fonts/README.md`에 있고, 다시 만드는 방법은 `scripts/subset_font.py`에 있습니다.

## 구조

- `gap_dashboard/main.py`: FastAPI 백엔드(시세 수집, 김프 계산, `/api/*`, `/ws/gaps`)
- `gap_dashboard/static/index.html`: 프론트엔드(순수 JS, 디자인 토큰 기반)
- `gap_dashboard/static/mock-data.js`: 데모·목업 데이터 생성기
- `scripts/build_demo.py`: 정적 데모 빌드
- `UI_REBUILD_NOTES.md`: UI 리빌드와 정적 데모의 결정 사항·검증 기록
