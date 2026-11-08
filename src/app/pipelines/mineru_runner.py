"""MinerU 2.x CLI adapter and output normalizer.

MinerU intentionally runs in its own Python 3.12 venv. The app talks to it only
through the CLI and files, so its torch/paddle dependency tree stays isolated.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import PROJECT_ROOT, settings
from app.pipelines.pdf_render import pages_as_dicts, render_pdf


@dataclass
class ParseManifest:
    doc_id: str
    source_pdf: str
    dpi: int
    device_requested: str
    device_used: str
    mineru_version: str
    elapsed_ms: int
    markdown: str
    content_list: str
    middle_json: str
    blocks: str
    tables: list[str]
    pages: list[dict]


def normalized_bbox_to_pixels(
    bbox: list[float], width: int, height: int
) -> list[float]:
    """MinerU content_list bboxes are normalized to 0-1000 on both axes."""
    if len(bbox) != 4:
        raise ValueError(f"bbox must have 4 values, got {bbox!r}")
    x0, y0, x1, y1 = bbox
    return [
        round(x0 / 1000 * width, 2),
        round(y0 / 1000 * height, 2),
        round(x1 / 1000 * width, 2),
        round(y1 / 1000 * height, 2),
    ]


def build_blocks(
    items: list[dict], pages: list[dict], tables: list[str]
) -> list[dict]:
    blocks: list[dict] = []
    table_index = 0
    for item in items:
        page_index = int(item.get("page_idx", 0))
        if page_index >= len(pages):
            raise ValueError(f"page_idx {page_index} out of range for {len(pages)} pages")
        page = pages[page_index]
        bbox = item.get("bbox")
        if not bbox:
            continue
        table_path = None
        if item.get("type") == "table" and table_index < len(tables):
            table_path = tables[table_index]
            table_index += 1
        blocks.append(
            {
                "page": page["page"],
                "type": item.get("type", "text"),
                "text": item.get("text") or item.get("table_body") or "",
                "bbox": normalized_bbox_to_pixels(bbox, page["width"], page["height"]),
                "table_html": table_path,
            }
        )
    return blocks


def _find_one(root: Path, filename: str) -> Path:
    matches = sorted(root.rglob(filename))
    if not matches:
        raise FileNotFoundError(f"MinerU did not produce {filename} under {root}")
    return matches[0]


def _mineru_executable() -> Path:
    configured = os.getenv("MINERU_EXECUTABLE")
    path = (
        Path(configured)
        if configured
        else PROJECT_ROOT / ".venv-mineru" / "Scripts" / "mineru.exe"
    )
    if not path.is_file():
        raise FileNotFoundError(
            f"MinerU executable not found: {path}. "
            "Install requirements-mineru.txt into .venv-mineru first."
        )
    return path


def _version(executable: Path) -> str:
    proc = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True, timeout=30
    )
    return (proc.stdout or proc.stderr).strip()


def _assert_cuda_available(mineru_executable: Path) -> None:
    python = mineru_executable.with_name("python.exe")
    proc = subprocess.run(
        [
            str(python),
            "-c",
            "import torch; print(torch.cuda.is_available()); "
            "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0 or not proc.stdout.strip().startswith("True"):
        raise RuntimeError(
            "CUDA was requested but is unavailable in the MinerU venv: "
            f"{(proc.stdout + proc.stderr).strip()}. Install a GPU torch build or use --device cpu."
        )


def parse_pdf(
    pdf_path: Path,
    doc_id: str,
    output_root: Path | None = None,
    device: str = "cuda",
    dpi: int | None = None,
    source: str = "modelscope",
    lang: str = "ch",
    timeout_seconds: int = 1200,
) -> ParseManifest:
    """Parse one PDF and normalize all artifacts under data/processed/{doc_id}."""
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    if not doc_id or any(c in doc_id for c in '/\\..'):
        raise ValueError("doc_id must be a non-empty path-safe identifier")

    dpi = dpi or settings.pdf_render_dpi
    root = output_root or PROJECT_ROOT / "data" / "processed"
    doc_dir = root / doc_id
    raw_dir = doc_dir / "mineru_raw"
    doc_dir.mkdir(parents=True, exist_ok=True)

    pages = render_pdf(pdf_path, doc_dir / "pages", dpi)
    executable = _mineru_executable()
    if device.startswith("cuda"):
        _assert_cuda_available(executable)
    command = [
        str(executable),
        "-p", str(pdf_path),
        "-o", str(raw_dir),
        "-b", "pipeline",
        "-m", "auto",
        "-l", lang,
        "-d", device,
        "-f", "false",  # receipts do not need formula recognition
        "-t", "true",
        "--source", source,
    ]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"MinerU timed out after {timeout_seconds}s") from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    (doc_dir / "mineru.stdout.log").write_text(proc.stdout or "", encoding="utf-8")
    (doc_dir / "mineru.stderr.log").write_text(proc.stderr or "", encoding="utf-8")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise RuntimeError(f"MinerU exited with {proc.returncode}:\n{tail}")

    stem = pdf_path.stem
    markdown = _find_one(raw_dir, f"{stem}.md")
    content_list = _find_one(raw_dir, f"{stem}_content_list.json")
    middle_json = _find_one(raw_dir, f"{stem}_middle.json")

    # Stable top-level copies make downstream code independent of MinerU's auto/txt dirs.
    shutil.copy2(markdown, doc_dir / "content.md")
    shutil.copy2(content_list, doc_dir / "content_list.json")
    shutil.copy2(middle_json, doc_dir / "layout.json")

    items = json.loads(content_list.read_text(encoding="utf-8"))
    page_dicts = pages_as_dicts(pages)
    tables_dir = doc_dir / "tables"
    tables_dir.mkdir(exist_ok=True)
    tables: list[str] = []
    for item in items:
        if item.get("type") == "table" and item.get("table_body"):
            target = tables_dir / f"table_{len(tables) + 1:03d}.html"
            target.write_text(item["table_body"], encoding="utf-8")
            tables.append(str(target.relative_to(doc_dir)))

    blocks = build_blocks(items, page_dicts, tables)
    (doc_dir / "blocks.json").write_text(
        json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = ParseManifest(
        doc_id=doc_id,
        source_pdf=str(pdf_path),
        dpi=dpi,
        device_requested=device,
        device_used=device,
        mineru_version=_version(executable),
        elapsed_ms=elapsed_ms,
        markdown="content.md",
        content_list="content_list.json",
        middle_json="layout.json",
        blocks="blocks.json",
        tables=tables,
        pages=page_dicts,
    )
    (doc_dir / "manifest.json").write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
