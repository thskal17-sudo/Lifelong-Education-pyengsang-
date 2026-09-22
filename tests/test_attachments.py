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
