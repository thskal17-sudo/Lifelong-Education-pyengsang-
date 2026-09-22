"""첨부파일 텍스트 추출: PDF, HWPX, DOCX, HWP(5.0), TXT (docs/DESIGN.md 5.3)."""
from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from xml.etree import ElementTree as ET

SUPPORTED_EXTENSIONS = (".hwp", ".hwpx", ".pdf", ".docx", ".txt")
_HWP_TAG_PARA_TEXT = 16 + 51  # HWPTAG_BEGIN + 51
_HWP_INLINE_OR_EXTENDED = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
_WS_RE = re.compile(r"[ \t ]+")
_NL_RE = re.compile(r"\n{3,}")


@dataclass
class ExtractResult:
    text: str
    ok: bool
    error: str | None = None


_WEB_PAGE_EXTENSIONS = {".do", ".php", ".jsp", ".asp", ".aspx", ".html", ".htm", ".cgi", ".action"}


def file_extension(name: str) -> str:
    """파일명 또는 URL의 확장자. 웹 페이지 확장자(.do 등)와 확장자 없음은 ''."""
    last = (name or "").lower().split("?")[0].split("#")[0].rsplit("/", 1)[-1]
    if "." not in last:
        return ""
    ext = "." + last.rsplit(".", 1)[-1]
    if ext in _WEB_PAGE_EXTENSIONS or not ext[1:].isalnum() or len(ext) > 6:
        return ""
    return ext


def extract_text(data: bytes, filename: str, max_chars: int = 20000) -> ExtractResult:
    from ..normalize import strip_surrogates  # 순환 import 방지
    ext = file_extension(filename)
    try:
        if ext == ".pdf":
            text = _pdf(data)
        elif ext == ".hwpx":
            text = _hwpx(data)
        elif ext == ".docx":
            text = _docx(data)
        elif ext == ".hwp":
            text = _hwp(data)
        elif ext == ".txt":
            text = data.decode("utf-8", errors="replace")
        else:
            return ExtractResult("", False, f"지원하지 않는 형식: {ext or '확장자 없음'}")
    except Exception as e:  # noqa: BLE001 - 파일 하나의 실패가 수집을 막지 않도록
        return ExtractResult("", False, f"{type(e).__name__}: {e}"[:200])
    text = _clean(strip_surrogates(text))[:max_chars]
    if not text.strip():
        return ExtractResult("", False, "빈 텍스트 (스캔 이미지 또는 암호화 가능성)")
    return ExtractResult(text, True)


def _clean(text: str) -> str:
    text = _WS_RE.sub(" ", text.replace("\r", ""))
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _NL_RE.sub("\n\n", text).strip()


# ---- PDF ----------------------------------------------------------------
def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"암호화된 PDF: {e}") from e
    return "\n".join((page.extract_text() or "") for page in reader.pages[:30])


# ---- HWPX / DOCX (zip + xml) -------------------------------------------
def _hwpx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted(n for n in z.namelist() if n.startswith("Contents/section") and n.endswith(".xml"))
        return "\n".join(_xml_paragraphs(z.read(n), "p") for n in names)


def _docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return _xml_paragraphs(z.read("word/document.xml"), "p")


def _xml_paragraphs(xml: bytes, para_local_name: str) -> str:
    root = ET.fromstring(xml)
    lines: list[str] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == para_local_name:
            lines.append("".join(el.itertext()))
    return "\n".join(lines) if lines else "".join(root.itertext())


# ---- HWP 5.0 (OLE compound) -------------------------------------------
def _hwp(data: bytes) -> str:
    import olefile

    if not olefile.isOleFile(io.BytesIO(data)):
        raise ValueError("HWP 5.0 형식이 아님 (HWP 3.0 또는 손상)")
    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 0x2:
            raise ValueError("암호화된 HWP")
        compressed = bool(flags & 0x1)
        sections = sorted(
            (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
            key=lambda e: int(e[1][7:] or 0),
        )
        streams = [ole.openstream(e).read() for e in sections]
    finally:
        ole.close()
    return hwp_text_from_streams(streams, compressed)


def hwp_text_from_streams(streams: list[bytes], compressed: bool) -> str:
    out: list[str] = []
    for raw in streams:
        buf = zlib.decompress(raw, -15) if compressed else raw
        out.append(_hwp_records_text(buf))
    return "\n".join(out)


def _hwp_records_text(buf: bytes) -> str:
    pos = 0
    paras: list[str] = []
    while pos + 4 <= len(buf):
        hdr = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        tag = hdr & 0x3FF
        size = (hdr >> 20) & 0xFFF
        if size == 0xFFF:
            size = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
        payload = buf[pos:pos + size]
        pos += size
        if tag == _HWP_TAG_PARA_TEXT:
            paras.append(_hwp_para_text(payload))
    return "\n".join(paras)


def _hwp_para_text(payload: bytes) -> str:
    chars: list[str] = []
    n = len(payload) // 2
    i = 0
    while i < n:
        c = struct.unpack_from("<H", payload, 2 * i)[0]
        if c in _HWP_INLINE_OR_EXTENDED:
            i += 8  # 인라인/확장 컨트롤은 8 WCHAR
            if c == 9:
                chars.append("\t")
            continue
        if c in (10, 13):
            chars.append("\n")
        elif c >= 32:
            chars.append(chr(c))
        i += 1
    return "".join(chars)
