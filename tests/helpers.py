"""테스트용 첨부파일 생성기."""
from __future__ import annotations

import io
import struct
import zipfile
import zlib


def make_hwpx(paragraphs: list[str]) -> bytes:
    ns = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    body = "".join(f'<hp:p xmlns:hp="{ns}"><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>' for t in paragraphs)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">{body}</hs:sec>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", xml)
    return buf.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def make_pdf(text_ascii: str) -> bytes:
    content = f"BT /F1 12 Tf 72 700 Td ({text_ascii}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_hwp_section(paragraphs: list[str], compressed: bool = True) -> bytes:
    """HWP 5.0 BodyText/Section 스트림을 흉내 낸다 (HWPTAG_PARA_TEXT 레코드만)."""
    tag = 16 + 51
    buf = bytearray()
    for t in paragraphs:
        # 탭(9)은 8 WCHAR 인라인 컨트롤, 문단 끝(13)은 2바이트
        payload = bytearray()
        for ch in t:
            if ch == "\t":
                payload += struct.pack("<H", 9) + b"\x00" * 14
            else:
                payload += ch.encode("utf-16-le")
        payload += struct.pack("<H", 13)
        hdr = tag | (0 << 10) | (len(payload) << 20)
        buf += struct.pack("<I", hdr) + payload
    return zlib.compress(bytes(buf))[2:-4] if compressed else bytes(buf)
