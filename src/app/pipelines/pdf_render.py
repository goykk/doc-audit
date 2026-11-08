"""PDF page rendering. All bbox coordinates in the project use these images."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True)
class RenderedPage:
    page: int
    image_path: str
    width: int
    height: int


def render_pdf(pdf_path: Path, output_dir: Path, dpi: int = 200) -> list[RenderedPage]:
    if dpi < 72:
        raise ValueError("dpi must be >= 72")
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[RenderedPage] = []
    with pymupdf.open(pdf_path) as doc:
        if doc.page_count == 0:
            raise ValueError(f"PDF has no pages: {pdf_path}")
        scale = dpi / 72.0
        matrix = pymupdf.Matrix(scale, scale)
        for index, page in enumerate(doc):
            target = output_dir / f"page_{index + 1:03d}.png"
            page.get_pixmap(matrix=matrix, alpha=False).save(target)
            pixmap = pymupdf.Pixmap(target)
            rendered.append(
                RenderedPage(index + 1, str(target), pixmap.width, pixmap.height)
            )
    return rendered


def pages_as_dicts(pages: list[RenderedPage]) -> list[dict]:
    return [asdict(page) for page in pages]
