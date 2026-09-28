"""정적 데모 빌드: python3 scripts/build_demo.py

gap_dashboard/static 을 dist/ 로 복사하고 index.html 의 실행 모드를 demo 로 바꾼다.
결과물은 서버 API·WebSocket·거래소 API를 호출하지 않으며, 아무 정적 호스팅(Netlify, Cloudflare Pages, GitHub Pages 등)에 올릴 수 있다.

- dist/index.html        <meta name="kimgap-mode" content="demo"> + CSP <meta> (connect-src 'self')
- dist/static/…          mock-data.js, 로고, 폰트
- dist/_headers          Netlify/Cloudflare Pages 형식 보안 헤더 (CSP connect-src 'self' 등)

표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import base64
import hashlib
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "gap_dashboard" / "static"
DIST = ROOT / "dist"
SKIP = {".DS_Store", "index.html"}

MODE_LIVE = '<meta name="kimgap-mode" content="live" />'
MODE_DEMO = '<meta name="kimgap-mode" content="demo" />'


def sha256_source(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def assert_hashable(html: str) -> None:
    """CSP 해시로 허용할 수 없는 인라인 코드가 있으면 빌드를 멈춘다 (데모에서 조용히 깨지는 것 방지)."""
    problems = []
    if re.search(r"<script\s[^>]*>", html) or re.search(r"<style\s[^>]*>", html):
        problems.append("속성이 붙은 <script>/<style> 태그 (해시 대상에서 빠짐)")
    if re.search(r"\son[a-z]+\s*=\s*[\"']", html):
        problems.append("인라인 이벤트 핸들러 속성(on*=)")
    if re.search(r"\sstyle\s*=\s*[\"']", html):
        problems.append("인라인 style= 속성")
    if problems:
        sys.exit("CSP 해시로 허용할 수 없는 인라인 코드: " + ", ".join(problems))


def inline_hashes(html: str, tag: str) -> list[str]:
    # 속성 없는 인라인 블록만 해시한다 (assert_hashable로 다른 형태가 없음을 먼저 확인)
    blocks = re.findall(rf"<{tag}>(.*?)</{tag}>", html, flags=re.S)
    if not blocks:
        sys.exit(f"inline <{tag}> 블록을 찾지 못했습니다")
    return [sha256_source(b) for b in blocks]


def csp(script_hashes: list[str], style_hashes: list[str], for_meta: bool) -> str:
    directives = [
        "default-src 'none'",
        "script-src 'self' " + " ".join(script_hashes),
        "style-src 'self' " + " ".join(style_hashes),
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "object-src 'none'",
    ]
    if not for_meta:  # frame-ancestors 는 <meta> CSP에서 무시되므로 헤더에만 넣는다
        directives.append("frame-ancestors 'none'")
    return "; ".join(directives)


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(SRC, DIST / "static", ignore=lambda _d, names: [n for n in names if n in SKIP])

    html = (SRC / "index.html").read_text(encoding="utf-8")
    if html.count(MODE_LIVE) != 1:
        sys.exit("index.html에서 kimgap-mode live 메타 태그를 정확히 1개 찾지 못했습니다")
    html = html.replace(MODE_LIVE, MODE_DEMO)

    assert_hashable(html)
    scripts = inline_hashes(html, "script")
    styles = inline_hashes(html, "style")
    charset = '<meta charset="utf-8" />'
    if html.count(charset) != 1:
        sys.exit(f"CSP <meta>를 넣을 위치({charset})를 정확히 1개 찾지 못했습니다")
    meta_csp = f'<meta http-equiv="Content-Security-Policy" content="{csp(scripts, styles, for_meta=True)}" />'
    html = html.replace(charset, charset + "\n  " + meta_csp, 1)
    (DIST / "index.html").write_text(html, encoding="utf-8")

    headers = "\n".join(
        [
            "/*",
            f"  Content-Security-Policy: {csp(scripts, styles, for_meta=False)}",
            "  X-Content-Type-Options: nosniff",
            "  Referrer-Policy: no-referrer",
            "  X-Frame-Options: DENY",
            "  Cross-Origin-Opener-Policy: same-origin",
            "  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()",
            "",
        ]
    )
    (DIST / "_headers").write_text(headers, encoding="utf-8")

    files = sorted(p.relative_to(DIST).as_posix() for p in DIST.rglob("*") if p.is_file())
    size = sum((DIST / f).stat().st_size for f in files)
    print(f"dist/ 빌드 완료: 파일 {len(files)}개, {size / 1024:.0f} KiB")
    for f in files:
        print("  " + f)


if __name__ == "__main__":
    main()
