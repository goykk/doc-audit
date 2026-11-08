"""Wrap a single receipt image into a one-page PDF so MinerU can parse it."""
from __future__ import annotations

from pathlib import Path

import pymupdf


def image_to_pdf(image_path: Path, pdf_path: Path, render_dpi: int = 200) -> Path:
    if render_dpi < 72:
        raise ValueError("render_dpi must be >= 72")
    pixmap = pymupdf.Pixmap(str(image_path))
    if pixmap.width <= 1 or pixmap.height <= 1:
        raise ValueError(f"invalid image size: {pixmap.width}x{pixmap.height}")
    width_pt = pixmap.width * 72 / render_dpi
    height_pt = pixmap.height * 72 / render_dpi

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=width_pt, height=height_pt)
    page.insert_image(page.rect, filename=str(image_path))
    doc.save(pdf_path)
    doc.close()
    return pdf_path
