"""Render a cited textbook page as a greyscale PNG, using only zlib and struct (no Pillow).

A citation chip opens the real page, so students and judges can check the answer themselves.
Rendered pages are cached on disk; the cache is removed with the book.
"""

import struct
import threading
import zlib
from pathlib import Path

import pypdfium2 as pdfium

from .config import settings

# pdfium is not thread-safe: one call at a time in this process (uploads.py shares it).
PDFIUM_LOCK = threading.Lock()


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def encode_grey_png(width: int, height: int, rows: bytes) -> bytes:
    """8-bit greyscale PNG; each scanline gets filter byte 0 (none)."""
    raw = b"".join(b"\x00" + rows[y * width : (y + 1) * width] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


def render_page(pdf_path: Path, pdf_page: int, dpi: int) -> bytes:
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(pdf_path)
        try:
            bitmap = pdf[pdf_page - 1].render(scale=dpi / 72, grayscale=True)
            width, height, stride = bitmap.width, bitmap.height, bitmap.stride
            buffer = bytes(bitmap.buffer)
        finally:
            pdf.close()
    rows = b"".join(buffer[y * stride : y * stride + width] for y in range(height))
    return encode_grey_png(width, height, rows)


def page_png(doc_id: int, pdf_path: Path, pdf_page: int) -> Path:
    """Path of the cached PNG, rendering it first if needed (write-then-rename: never half)."""
    target = settings.page_cache_dir / str(doc_id) / f"{pdf_page}.png"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".tmp")
        partial.write_bytes(render_page(pdf_path, pdf_page, settings.page_image_dpi))
        partial.replace(target)
    return target
