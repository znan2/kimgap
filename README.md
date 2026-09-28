# 차익 대시보드 (kimgap)

업비트·빗썸 가격 괴리와 해외 거래소(Binance, Bybit, Bitget, Gate.io) 대비 김치 프리미엄을 실시간으로 보여주는 대시보드입니다.

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
- API 키가 없어도 시세·김프는 동작합니다. 키가 있으면 입출금 상태와 출금 한도를 함께 보여줍니다.
- 키는 **조회 권한만** 주고(주문·출금·입금 권한은 끔), 허용 IP를 실행 서버로 제한하세요. 코드는 `GET /v1/status/wallet`, `GET /v1/withdraws/chance`만 호출합니다.
- 공개 서버로 운영하려면 먼저 다음을 적용하세요.
  - `POST /api/refresh-limits`에 인증을 추가한다(현재 인증 없음).
  - FastAPI `/docs`, `/openapi.json`을 끈다.
  - 리버스 프록시에 요청 속도와 연결 수 제한을 둔다.

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
