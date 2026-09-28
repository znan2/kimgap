# fonts

- `KimgapSans-Variable.subset.woff2`: [Pretendard](https://github.com/orioncactus/pretendard) v1.3.9 Variable에서 이 대시보드가 쓰는 글자(ASCII, UI 한글 356자, 기호 등 475자)만 남긴 subset이다.
- Pretendard는 SIL Open Font License 1.1(`OFL.txt`)로 배포되고 "Pretendard"가 예약 폰트 이름(Reserved Font Name)이다. subset은 수정본이므로 폰트 이름을 **Kimgap Sans**로 바꿨다. 저작권·상표·디자이너 표기는 원본 그대로 두었다.
- 다시 만들려면 `scripts/subset_font.py`의 설명을 따른다. UI에 새 한글 문구가 생기면 다시 실행한다. subset에 없는 글자는 시스템 폰트로 표시된다.
