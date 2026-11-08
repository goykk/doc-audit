"""Create a synthetic, public-demo-safe receipt PDF for pipeline smoke tests."""
from __future__ import annotations

from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "raw" / "sample_receipt.pdf"

LINES = [
    ("NORTH STAR COFFEE", 20, 16),
    ("123 Demo Street, Shanghai", 42, 10),
    ("Receipt: NS-20261106-001", 66, 10),
    ("Date: 2026-11-06 15:30", 84, 10),
    ("", 0, 10),
    ("Item                 Qty     Unit Price     Amount", 120, 10),
    ("Latte                  2          18.00      36.00", 140, 10),
    ("Croissant              1          16.00      16.00", 160, 10),
    ("", 0, 10),
    ("Subtotal:                                      52.00", 200, 10),
    ("Tax (6%):                                       3.12", 220, 10),
    ("Total:                                         55.12", 240, 12),
    ("Payment: WeChat Pay", 270, 10),
    ("Synthetic document - not a real receipt", 300, 9),
]


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=420)
    for text, y, size in LINES:
        if text:
            page.insert_text((50, y), text, fontsize=size, fontname="helv")
    page.draw_rect(pymupdf.Rect(45, 108, 545, 178), color=(0, 0, 0), width=0.6)
    doc.save(TARGET)
    doc.close()
    print(TARGET)


if __name__ == "__main__":
    main()
