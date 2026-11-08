from pathlib import Path

import pymupdf
import pytest

from app.pipelines.pdf_render import render_pdf


def _pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=100)
    page.insert_text((10, 30), "synthetic")
    doc.save(path)
    doc.close()
    return path


def test_render_uses_requested_dpi_and_one_based_pages(tmp_path: Path):
    pages = render_pdf(_pdf(tmp_path / "a.pdf"), tmp_path / "pages", dpi=144)
    assert len(pages) == 1
    assert pages[0].page == 1
    assert (pages[0].width, pages[0].height) == (400, 200)
    assert Path(pages[0].image_path).is_file()


def test_render_rejects_missing_pdf_and_low_dpi(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        render_pdf(tmp_path / "missing.pdf", tmp_path / "pages")
    with pytest.raises(ValueError):
        render_pdf(_pdf(tmp_path / "a.pdf"), tmp_path / "pages", dpi=36)
