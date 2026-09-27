/*
 * 목업 데이터 모드 전용 (index.html?mock=1 일 때만 로드된다).
 *
 * - /ws/gaps 페이로드와 같은 모양의 JSON을 브라우저 안에서 만든다. 서버·거래소 API를 호출하지 않는다.
 * - 가격·김프·출금 한도는 모두 가상의 값이다. 실제 시세, 잔고, 지갑 주소가 아니다.
 * - 스키마 기준: gap_dashboard/main.py 의 _compute_gaps_payload() (읽기 전용으로 참고).
 */
(function () {
  "use strict";

  const USDT_KRW_BASE = 1392.0;

  // 결정적 난수 (새로고침해도 같은 첫 화면)
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  let rand = mulberry32(20260928);
  const jitter = (pct) => 1 + (rand() * 2 - 1) * (pct / 100);

  // 해외 상장 코드: B=Binance, Y=Bybit, G=Bitget, O=OKX, T=Gate.io
  const ALL = "BYGOT";
  /**
   * [심볼, 업비트 KRW, 업비트 김프 %(null = 해외 미상장), 빗썸 괴리 %, 옵션]
   * 옵션: spot/fut = 상장 코드, nets = 네트워크 목록, map = 해외 심볼 매핑, dw = 입출금 이슈 시나리오
   */
  const COINS = [
    ["BTC", 158420000, 1.82, 0.04, { nets: ["BTC"] }],
    ["ETH", 5712000, 1.95, -0.07, { nets: ["ETH"] }],
    ["XRP", 4215, 2.31, 0.12, { nets: ["XRP"] }],
    ["SOL", 312400, 1.74, -0.1, { nets: ["SOL"] }],
    ["DOGE", 358, 2.05, 0.28, { nets: ["DOGE"] }],
    ["ADA", 1184, 1.66, -0.17, { nets: ["ADA"] }],
    ["TRX", 482, 1.12, 0.21, { nets: ["TRX"] }],
    ["LINK", 34850, 1.88, 0.14, { nets: ["ETH"] }],
    ["AVAX", 42160, 1.71, -0.24, { nets: ["AVAX-C"] }],
    ["DOT", 9870, 1.52, 0.33, { nets: ["DOT"] }],
    ["SUI", 5420, 2.62, -0.41, { nets: ["SUI"] }],
    ["SHIB", 0.0218, 1.9, 0.46, { nets: ["ETH"] }],
    ["HBAR", 372, 1.43, -0.27, { nets: ["HBAR"] }],
    ["XLM", 610, 2.12, 0.16, { nets: ["XLM"] }],
    ["BCH", 812500, 1.35, -0.09, { nets: ["BCH"] }],
    ["NEAR", 4380, 1.57, 0.52, { nets: ["NEAR"] }],
    ["APT", 11240, 1.28, -0.36, { nets: ["APT"] }],
    ["ETC", 32100, 1.61, 0.19, { nets: ["ETC"] }],
    ["UNI", 14950, 1.49, -0.22, { nets: ["ETH"] }],
    ["AAVE", 452000, 1.33, 0.08, { nets: ["ETH"] }],
    ["ARB", 612, 0.94, 0.61, { nets: ["ARB"] }],
    ["OP", 1338, 1.08, -0.48, { nets: ["OP"] }],
    ["SEI", 468, 3.42, 1.12, { nets: ["SEI"], dw: "bithumb_withdraw_off" }],
    ["ENA", 1092, 4.17, -0.86, { nets: ["ETH"], spot: "BYGOT", fut: "BYGO" }],
    ["PEPE", 0.0196, 2.74, 0.38, { nets: ["ETH"] }],
    ["ONDO", 1684, 1.21, -0.31, { nets: ["ETH"], spot: "BYGT" }],
    ["WLD", 2110, -0.62, 0.27, { nets: ["OP", "ETH"] }],
    ["STX", 1322, 0.88, -0.15, { nets: ["STX"] }],
    ["IMX", 1048, 1.14, 0.44, { nets: ["ETH"] }],
    ["SAND", 482, 5.86, 2.64, { nets: ["ETH", "POLYGON"], dw: "bithumb_full_pause" }],
    ["MANA", 516, 0.71, -0.2, { nets: ["ETH"] }],
    ["ALGO", 402, 1.36, 0.11, { nets: ["ALGO"] }],
    ["BTT", 0.00132, 0.45, -0.58, { nets: ["TRX"], map: "BTTC", fut: "BYGT" }],
    ["ZRO", 4520, -1.34, 0.72, { nets: ["ETH", "ARB"], dw: "upbit_partial_net" }],
    ["ORCA", 3880, 7.92, 3.41, { nets: ["SOL"], spot: "BYGT", fut: "BYG", dw: "orca_restricted" }],
    ["MOVE", 612, -2.18, -0.94, { nets: ["MOVE"], dw: "upbit_deposit_off" }],
    ["JUP", 1262, 1.02, 0.23, { nets: ["SOL"] }],
    ["TIA", 5480, 1.64, -0.39, { nets: ["TIA"] }],
    ["STRAX", 88, 3.8, 1.87, { nets: ["STRAX"], spot: "BGT", fut: "", dw: "upbit_full_pause" }],
    ["KAIA", 214, null, 0.35, { nets: ["KAIA"] }],
    ["MED", 12.4, null, 1.46, { nets: ["MED"], dw: "bithumb_full_pause" }],
    ["MLK", 318, null, -0.82, { nets: ["MLK"] }],
    ["BORA", 142, null, 0.57, { nets: ["KAIA"], dw: "bithumb_unknown" }],
  ];

  const EX_ORDER = ["binance", "bybit", "bitget", "okx", "gate"];
  const EX_CODE = { binance: "B", bybit: "Y", bitget: "G", okx: "O", gate: "T" };
  const EX_LABEL = { binance: "Binance", bybit: "Bybit", bitget: "Bitget", okx: "OKX", gate: "Gate.io" };
  const COMPARE_EX = ["binance", "bybit", "bitget", "gate"]; // 서버 비교 대상과 동일 (OKX는 기준가 소스로만 사용)

  function exSymbol(ex, base, market) {
    if (ex === "okx") return market === "spot" ? `${base}-USDT` : `${base}-USDT-SWAP`;
    if (ex === "gate") return `${base}_USDT`;
    return `${base}USDT`;
  }

  function net(netType, dep, wd) {
    const state = dep && wd ? "working" : dep ? "deposit_only" : wd ? "withdraw_only" : "paused";
    return {
      net_type: netType,
      deposit_available: dep,
      withdraw_available: wd,
      wallet_state: state,
      block_state: dep || wd ? "normal" : "inactive",
    };
  }

  function walletFrom(nets) {
    const dep = nets.some((n) => n.deposit_available);
    const wd = nets.some((n) => n.withdraw_available);
    const full = (n) => !n.deposit_available && !n.withdraw_available;
    return {
      deposit_available: dep,
      withdraw_available: wd,
      all_networks_full_pause: nets.length > 0 && nets.every(full),
      any_network_full_pause: nets.some(full),
      any_network_restricted: nets.some((n) => !n.deposit_available || !n.withdraw_available),
    };
  }

  function networksFor(opts) {
    const base = opts.nets || [];
    let up = base.map((n) => net(n, true, true));
    let bh = base.map((n) => net(n, true, true));
    switch (opts.dw) {
      case "bithumb_withdraw_off":
        bh = base.map((n) => net(n, true, false));
        break;
      case "bithumb_full_pause":
        bh = base.map((n) => net(n, false, false));
        break;
      case "upbit_full_pause":
        up = base.map((n) => net(n, false, false));
        break;
      case "upbit_deposit_off":
        up = base.map((n) => net(n, false, true));
        break;
      case "upbit_partial_net":
        up = [net(base[0], true, true), net(base[1], false, false)];
        break;
      case "orca_restricted":
        up = base.map((n) => net(n, true, false));
        bh = base.map((n) => net(n, false, true));
        break;
      case "bithumb_unknown":
        bh = null;
        break;
      default:
        break;
    }
    return { up, bh };
  }

  // 코인별 상태(가격은 tick마다 흔들린다)
  const state = COINS.map(([sym, krw, kp, bhGap, opts]) => {
    const refUsdt = kp == null ? null : krw / USDT_KRW_BASE / (1 + kp / 100);
    return { sym, upbit: krw, bithumb: krw * (1 + bhGap / 100), refUsdt, opts, nets: networksFor(opts) };
  });
  let usdtKrw = USDT_KRW_BASE;
  // 출금 한도를 조회하는 대상 = 해외 기준가가 있는 종목 (payload의 withdraw_limits 행 수와 일치)
  const LIMIT_TOTAL = state.filter((c) => c.refUsdt != null).length;
  let wl = { status: "done", progress: "", count: LIMIT_TOTAL, ts: Date.now() - 6 * 60 * 1000, loadingTicks: 0 };

  function roundPrice(v) {
    if (v >= 1000) return Math.round(v);
    if (v >= 100) return Math.round(v * 10) / 10;
    if (v >= 1) return Math.round(v * 100) / 100;
    return Number(v.toPrecision(4));
  }

  function withdrawLimitsFor(sym, krw) {
    // 거래소 기본 한도처럼 보이는 가상의 값 (계정 정보 아님)
    const dailyKrw = 500000000;
    return {
      upbit_daily: Number((dailyKrw / krw).toPrecision(4)),
      upbit_remaining_krw: dailyKrw,
      upbit_min: Number((10000 / krw).toPrecision(2)),
      bithumb_daily: Number((dailyKrw / krw).toPrecision(4)),
      bithumb_min: Number((12000 / krw).toPrecision(2)),
    };
  }

  function buildPayload() {
    const t0 = performance.now();
    const gaps = [];
    const perEx = {};
    COMPARE_EX.forEach((ex) => {
      perEx[`${ex}_spot`] = [];
      perEx[`${ex}_futures`] = [];
    });

    state.forEach((c) => {
      const up = roundPrice(c.upbit);
      const bh = roundPrice(c.bithumb);
      const lo = Math.min(up, bh);
      const hi = Math.max(up, bh);
      const base = c.opts.map || c.sym;
      const spotCodes = c.opts.spot != null ? c.opts.spot : c.refUsdt == null ? "" : ALL;
      const futCodes = c.opts.fut != null ? c.opts.fut : c.refUsdt == null ? "" : ALL;
      const row = {
        symbol: c.sym,
        upbit: up,
        bithumb: bh,
        gap_pct: Number((((hi - lo) / lo) * 100).toFixed(4)),
        cheaper_on: up < bh ? "upbit" : bh < up ? "bithumb" : "tie",
      };
      EX_ORDER.forEach((ex) => {
        if (spotCodes.includes(EX_CODE[ex])) row[`${ex}_spot_symbol`] = exSymbol(ex, base, "spot");
        if (futCodes.includes(EX_CODE[ex])) row[`${ex}_futures_symbol`] = exSymbol(ex, base, "futures");
      });
      if (c.refUsdt != null) {
        const upU = up / usdtKrw;
        const bhU = bh / usdtKrw;
        row.kp_upbit = Number((((upU - c.refUsdt) / c.refUsdt) * 100).toFixed(4));
        row.kp_bithumb = Number((((bhU - c.refUsdt) / c.refUsdt) * 100).toFixed(4));
        row.ref_usdt = Number(c.refUsdt.toPrecision(8));
        row.ref_usdt_source = EX_ORDER.find((ex) => spotCodes.includes(EX_CODE[ex])) || null;
      } else {
        row.kp_upbit = null;
        row.kp_bithumb = null;
        row.ref_usdt = null;
        row.ref_usdt_source = null;
      }
      if (c.nets.up) {
        row.upbit_wallet = walletFrom(c.nets.up);
        row.upbit_networks = c.nets.up;
      }
      if (c.nets.bh) {
        row.bithumb_wallet = walletFrom(c.nets.bh);
        row.bithumb_networks = c.nets.bh;
      }
      if (wl.status === "done" && c.refUsdt != null) row.withdraw_limits = withdrawLimitsFor(c.sym, up);
      gaps.push(row);

      if (c.refUsdt == null) return;
      [["spot", spotCodes, 0.03], ["futures", futCodes, 0.09]].forEach(([market, codes, spread]) => {
        COMPARE_EX.forEach((ex, i) => {
          if (!codes.includes(EX_CODE[ex])) return;
          const refX = c.refUsdt * (1 + (market === "futures" ? 0.0004 : 0) + ((i - 1.5) * spread) / 100);
          const upU = up / usdtKrw;
          const bhU = bh / usdtKrw;
          const upG = ((upU - refX) / refX) * 100;
          const bhG = ((bhU - refX) / refX) * 100;
          const cmp = {
            symbol: c.sym,
            mapped_symbol: base,
            exchange: ex,
            exchange_label: EX_LABEL[ex],
            market,
            exchange_symbol: exSymbol(ex, base, market),
            reference_usdt: Number(refX.toPrecision(8)),
            binance_usdt: Number(refX.toPrecision(8)),
            upbit: up,
            bithumb: bh,
            upbit_usdt: Number(upU.toPrecision(8)),
            bithumb_usdt: Number(bhU.toPrecision(8)),
            upbit_gap_pct: Number(upG.toFixed(4)),
            bithumb_gap_pct: Number(bhG.toFixed(4)),
            max_abs_gap_pct: Number(Math.max(Math.abs(upG), Math.abs(bhG)).toFixed(4)),
          };
          cmp[`${ex}_${market}_symbol`] = cmp.exchange_symbol;
          perEx[`${ex}_${market}`].push(cmp);
        });
      });
    });

    const spot = COMPARE_EX.flatMap((ex) => perEx[`${ex}_spot`]);
    const futures = COMPARE_EX.flatMap((ex) => perEx[`${ex}_futures`]);
    const deadOn = (w) => w && w.deposit_available === false && w.withdraw_available === false;
    const limited = (w) => w && (w.deposit_available === false || w.withdraw_available === false);
    const anyFull = (w) => w && w.any_network_full_pause;
    const refStats = {};
    EX_ORDER.forEach((ex) => {
      refStats[ex] = gaps.filter((r) => r.ref_usdt_source === ex).length;
    });
    const reg = (n) => ({ loaded: true, usdt_spot_bases: n });
    const regF = (n) => ({ loaded: true, usdt_perp_bases: n });

    return {
      updated_at_ms: Date.now(),
      latency_ms: Number((142 + (performance.now() - t0) + rand() * 60).toFixed(1)),
      meta: {
        pairs_compared: gaps.length,
        upbit_only: 14,
        bithumb_only: 96,
        usdt_krw: Number(usdtKrw.toFixed(1)),
        wallet: {
          upbit_configured: true,
          bithumb_configured: true,
          upbit_error: null,
          bithumb_error: null,
          mode: "on",
        },
        binance_symbols: 412,
        binance_spot_price_symbols: 412,
        binance_futures_price_symbols: 486,
        binance_spot_compared: perEx.binance_spot.length,
        binance_futures_compared: perEx.binance_futures.length,
        bybit_spot_price_symbols: 628,
        bybit_futures_price_symbols: 512,
        bybit_spot_compared: perEx.bybit_spot.length,
        bybit_futures_compared: perEx.bybit_futures.length,
        bitget_spot_price_symbols: 804,
        bitget_futures_price_symbols: 538,
        bitget_spot_compared: perEx.bitget_spot.length,
        bitget_futures_compared: perEx.bitget_futures.length,
        gate_spot_price_symbols: 2310,
        gate_futures_price_symbols: 610,
        gate_spot_compared: perEx.gate_spot.length,
        gate_futures_compared: perEx.gate_futures.length,
        spot_compared: spot.length,
        futures_compared: futures.length,
        ref_usdt_symbols: gaps.filter((r) => r.ref_usdt != null).length,
        ref_usdt_stats: refStats,
        binance_spot_registry: reg(412),
        binance_futures_registry: regF(486),
        bybit_spot_registry: reg(628),
        bybit_linear_registry: regF(512),
        bitget_spot_registry: reg(804),
        bitget_futures_registry: regF(538),
        okx_spot_registry: reg(301),
        okx_futures_registry: regF(254),
        gate_spot_registry: reg(2310),
        gate_futures_registry: regF(610),
        kp_available: gaps.filter((r) => r.kp_upbit != null).length,
        wl_status: wl.status,
        wl_progress: wl.progress,
        wl_count: wl.status === "done" ? gaps.filter((r) => r.withdraw_limits).length : wl.count,
        wl_ts: wl.ts,
      },
      gaps,
      spot_comparisons: spot,
      futures_comparisons: futures,
      binance_spot_comparisons: perEx.binance_spot,
      binance_futures_comparisons: perEx.binance_futures,
      bybit_spot_comparisons: perEx.bybit_spot,
      bybit_futures_comparisons: perEx.bybit_futures,
      bitget_spot_comparisons: perEx.bitget_spot,
      bitget_futures_comparisons: perEx.bitget_futures,
      gate_spot_comparisons: perEx.gate_spot,
      gate_futures_comparisons: perEx.gate_futures,
      wallet_fully_blocked: gaps.filter((r) => deadOn(r.upbit_wallet) || deadOn(r.bithumb_wallet)),
      wallet_any_network_full_pause: gaps.filter((r) => anyFull(r.upbit_wallet) || anyFull(r.bithumb_wallet)),
      wallet_restricted: gaps.filter((r) => limited(r.upbit_wallet) || limited(r.bithumb_wallet)),
    };
  }

  function tick() {
    usdtKrw = USDT_KRW_BASE * jitter(0.05);
    state.forEach((c) => {
      const move = jitter(0.12);
      c.upbit *= move * jitter(0.03);
      c.bithumb *= move * jitter(0.03);
      if (c.refUsdt != null) c.refUsdt *= move * jitter(0.04);
    });
    if (wl.status === "loading") {
      wl.loadingTicks += 1;
      wl.count = Math.min(LIMIT_TOTAL, wl.loadingTicks * 13);
      wl.progress = `${wl.count}/${LIMIT_TOTAL}`;
      if (wl.loadingTicks >= 3) wl = { status: "done", progress: "", count: LIMIT_TOTAL, ts: Date.now(), loadingTicks: 0 };
    }
    return buildPayload();
  }

  const json = (body) =>
    Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));

  /** /api/* 요청을 목업 응답으로 가로챈다. 목업 모드에서만 호출된다. */
  function install() {
    const realFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      const url = typeof input === "string" ? input : input && input.url;
      const path = url ? new URL(url, location.href).pathname : "";
      if (path === "/api/refresh-limits") {
        if (wl.status === "loading") return json({ status: wl.status, progress: wl.progress, msg: "이미 로딩 중" });
        wl = { status: "loading", progress: `0/${LIMIT_TOTAL}`, count: 0, ts: wl.ts, loadingTicks: 0 };
        return json({ status: "started", msg: "백그라운드 조회 시작" });
      }
      if (path === "/api/limits-status") {
        return json({
          status: wl.status,
          progress: wl.progress,
          cached_count: wl.count,
          cached_at_ms: wl.ts,
          loading: wl.status === "loading",
          last_error: "",
          stats: { upbit_attempted: LIMIT_TOTAL, upbit_success: LIMIT_TOTAL, bithumb_attempted: LIMIT_TOTAL, bithumb_success: LIMIT_TOTAL - 1 },
        });
      }
      if (path === "/api/gaps") return json(buildPayload());
      if (path.startsWith("/api/")) return json({ detail: "mock: 지원하지 않는 경로" });
      return realFetch(input, init);
    };
  }

  window.GapMock = { install, payload: buildPayload, tick };
})();
