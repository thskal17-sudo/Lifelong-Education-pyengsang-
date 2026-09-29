from gia.extract.attachments import extract_text, file_extension, hwp_text_from_streams
from gia.extract.deadline import parse_deadline
from tests.helpers import make_docx, make_hwp_section, make_hwpx, make_pdf
from datetime import date


def test_hwpx():
    res = extract_text(make_hwpx(["강사 모집 공고", "접수기간: 2026. 10. 15.(목) 17:00까지"]), "공고문.hwpx")
    assert res.ok and "접수기간" in res.text
    assert parse_deadline(res.text, date(2026, 9, 21)).deadline.isoformat() == "2026-10-15T17:00:00+09:00"


def test_docx():
    res = extract_text(make_docx(["제출기한 2026.09.30.(수)"]), "안내.DOCX")
    assert res.ok and "제출기한" in res.text


def test_pdf():
    res = extract_text(make_pdf("Due 2026. 9. 30. 18:00"), "notice.pdf")
    assert res.ok and "2026. 9. 30." in res.text


def test_hwp_records():
    stream = make_hwp_section(["모집\t공고", "접수기간: 2026. 10. 1.(목)까지"], compressed=True)
    text = hwp_text_from_streams([stream], compressed=True)
    assert "모집\t공고" in text and "접수기간" in text
    raw = make_hwp_section(["평문"], compressed=False)
    assert hwp_text_from_streams([raw], compressed=False).strip() == "평문"


def test_hwp_not_ole():
    res = extract_text(b"not an ole file", "x.hwp")
    assert not res.ok and "HWP" in res.error


def test_unsupported_and_empty():
    assert not extract_text(b"...", "image.jpg").ok
    assert not extract_text(make_hwpx([""]), "empty.hwpx").ok


def test_file_extension():
    assert file_extension("https://x.org/files/공고문.HWP?x=1") == ".hwp"
    assert file_extension("https://x.org/download.do?fileId=3") == ""


def test_extract_text_strips_lone_surrogates():
    """HWP 본문을 UTF-16 으로 풀 때 섞여 드는 짝 없는 서로게이트를 없앤다 (진주보건대 첨부, 2026-09-23).

    남아 있으면 build_posting 의 content_hash 계산에서 UnicodeEncodeError 가 나고 수집 전체가 멈춘다.
    """
    from gia.extract.attachments import extract_text
    raw = "모집 공고\ud83d 강사 모집\udc00 끝".encode("utf-8", "surrogatepass")
    res = extract_text(raw, "notice.txt")
    assert res.ok
    assert "강사 모집" in res.text
    res.text.encode("utf-8")  # 예외가 없어야 한다


# --- 2026-09-29: 경남 저장소에서 찾은 것을 옮긴다 ---

def test_filename_comes_from_query_when_path_has_none():
    """'download.asp?file=공고문.pdf' 꼴로 주는 곳이 있다.

    경로만 보면 확장자가 '.asp' 라 형식을 모르는 파일로 버려진다.
    """
    from gia.extract.attachments import file_extension, filename_from_url

    url = "https://example.org/site/download.asp?bid=1&file=2026+%EA%B3%B5%EA%B3%A0%2Epdf"
    assert file_extension(filename_from_url(url)) == ".pdf"
    # 경로에 이름이 있으면 그것을 그대로 쓴다
    assert filename_from_url("https://x/a/공고문.hwp") == "공고문.hwp"
    # 쓸 이름이 없으면 경로 끝을 돌려준다(기존 동작)
    assert filename_from_url("https://x/view.do?id=3") == "view.do"


def test_notice_attachment_is_read_before_blank_form():
    """첨부는 몇 개까지만 읽는다. 빈 응시원서가 그 칸을 다 쓰면 알맹이가 안 나온다."""
    from gia.pipeline import _attachment_rank

    names = [
        "[서식7] 프로그램 운영 제안서.hwp",
        "지원서류응시원서 등 8종.hwp",
        "2026.외부강사채용공고.hwp",
    ]
    assert sorted(names, key=_attachment_rank)[0] == "2026.외부강사채용공고.hwp"
    # 이름에 '공고'가 함께 있으면 서식으로 밀어내지 않는다
    assert _attachment_rank("강사 모집 공고 및 서식.hwp") < _attachment_rank("응시원서.hwp")
