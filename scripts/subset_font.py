"""대시보드용 폰트 subset 생성 (개발자 전용, 빌드에는 필요 없음).

Pretendard Variable에서 이 저장소 UI가 실제로 쓰는 글자만 남겨
gap_dashboard/static/fonts/KimgapSans-Variable.subset.woff2 를 만든다.
OFL 1.1의 Reserved Font Name("Pretendard") 조항에 따라 수정본(subset)의 폰트 이름은 "Kimgap Sans"로 바꾼다.

준비:
    pip install fonttools brotli
    npm pack pretendard@1.3.9 && tar xzf pretendard-1.3.9.tgz
실행:
    python3 scripts/subset_font.py package/dist/web/variable/woff2/PretendardVariable.woff2

UI 문구를 바꿔 새 한글이 생기면 다시 실행한다. subset에 없는 글자는 브라우저가 시스템 폰트로 대체한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "gap_dashboard" / "static" / "fonts" / "KimgapSans-Variable.subset.woff2"
TEXT_SOURCES = [
    ROOT / "gap_dashboard" / "static" / "index.html",
    ROOT / "gap_dashboard" / "static" / "mock-data.js",
    ROOT / "gap_dashboard" / "main.py",  # 서버가 내려주는 한글 메시지
]
EXTRA = "₩▲▼–—·×→←↑↓…“”‘’°±%‰￦"
FAMILY = "Kimgap Sans"
PS_NAME = "KimgapSans-Variable"


def collect_text() -> str:
    chars = {chr(c) for c in range(0x20, 0x7F)}  # ASCII 전체
    chars.update(EXTRA)
    for src in TEXT_SOURCES:
        for ch in src.read_text(encoding="utf-8"):
            if ord(ch) >= 0x80 and ch.isprintable():
                chars.add(ch)
    return "".join(sorted(chars))


ATTRIBUTION_IDS = {0, 7, 8, 9, 10, 11, 12, 13, 14}  # 저작권·상표·제작자·설명·라이선스: 출처 표기로 유지


def rename(font: TTFont) -> None:
    name = font["name"]
    for rec in list(name.names):
        if rec.nameID in ATTRIBUTION_IDS:
            continue
        if rec.nameID in (1, 16):
            rec.string = FAMILY
        elif rec.nameID == 4:
            rec.string = f"{FAMILY} Variable"
        elif rec.nameID == 6:
            rec.string = PS_NAME
        elif rec.nameID == 3:
            rec.string = f"{PS_NAME};subset"
        elif rec.nameID == 25:  # Variations PostScript Name Prefix
            rec.string = "KimgapSans"
        else:  # fvar 인스턴스 이름 등 (예: PretendardVariable-Thin)
            s = rec.toUnicode()
            if "Pretendard" in s:
                rec.string = s.replace("PretendardVariable", "KimgapSans").replace("Pretendard", FAMILY)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    source = Path(sys.argv[1])
    text = collect_text()
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    font = subset.load_font(str(source), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text=text)
    sub.subset(font)
    rename(font)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subset.save_font(font, str(OUT), opts)
    print(f"{len(text)} chars -> {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
