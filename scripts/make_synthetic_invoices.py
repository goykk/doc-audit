"""Generate synthetic Chinese invoices with known validation faults.

10 clean + 10 single-fault + 2 duplicate invoices. Every document is synthetic and
carries a visible disclaimer; no real invoice data is used.

Outputs:
  data/raw/synthetic/{doc_id}.png
  data/ground_truth/synthetic/{doc_id}.json
  data/ground_truth/synthetic_labels.jsonl
  data/ground_truth/manifest.jsonl  (synthetic rows merged, CORD rows preserved)
"""
from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.extraction_result import ExtractionResult, FieldValue, LineItem  # noqa: E402
from app.validation.cn_amount import cn_upper_amount  # noqa: E402

FONT = "C:/Windows/Fonts/simhei.ttf"
TODAY = date(2026, 11, 6)
DPI = 200

SELLERS = [
    ("上海云杉科技有限公司", "91310115MA1K3A1B2C"),
    ("苏州恒远贸易有限公司", "91320594MA2N4D5E6F"),
    ("杭州青禾供应链有限公司", "91330106MA2B7C8D9E"),
]
BUYERS = [
    ("北京示例数据服务有限公司", "91110108MA01X2Y3Z4"),
    ("深圳前海示例咨询有限公司", "91440300MA5F6G7H8J"),
]
PRODUCTS = [
    ("办公用品", "A"),
    ("打印耗材", "B"),
    ("会议物料", "C"),
    ("清洁用品", "D"),
    ("电子配件", "E"),
]


@dataclass
class InvoiceSpec:
    doc_id: str
    fields: dict[str, str]
    items: list[dict[str, str]]
    fault: str
    expected_rules: list[str]
    expect_status: str


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def make_clean(index: int) -> InvoiceSpec:
    doc_id = f"syn_invoice_{index:04d}"
    subtotal = Decimal(1000 + index * 137)
    tax = (subtotal * Decimal("0.06")).quantize(Decimal("0.01"))
    total = subtotal + tax
    item1_amount = (subtotal * Decimal("0.6")).quantize(Decimal("0.01"))
    item2_amount = subtotal - item1_amount
    seller, seller_tax = SELLERS[index % len(SELLERS)]
    buyer, buyer_tax = BUYERS[index % len(BUYERS)]
    product1, suffix1 = PRODUCTS[index % len(PRODUCTS)]
    product2, suffix2 = PRODUCTS[(index + 2) % len(PRODUCTS)]
    fields = {
        "invoice_number": f"INV2026{index:04d}",
        "invoice_date": (TODAY - timedelta(days=index)).isoformat(),
        "seller_name": seller,
        "seller_tax_id": seller_tax,
        "buyer_name": buyer,
        "buyer_tax_id": buyer_tax,
        "subtotal": money(subtotal),
        "tax_total": money(tax),
        "tax_rate": "6%",
        "amount_total": money(total),
        "total_with_tax": money(total),
        "amount_in_words": cn_upper_amount(total),
    }
    items = [
        {
            "description": f"{product1}{suffix1}{index:02d}",
            "quantity": "2",
            "unit_price": money(item1_amount / 2),
            "amount": money(item1_amount),
        },
        {
            "description": f"{product2}{suffix2}{index:02d}",
            "quantity": "1",
            "unit_price": money(item2_amount),
            "amount": money(item2_amount),
        },
    ]
    return InvoiceSpec(doc_id, fields, items, "clean", [], "accepted")


def with_fault(base: InvoiceSpec, suffix: str, mutation) -> InvoiceSpec:
    spec = copy.deepcopy(base)
    spec.doc_id = f"{base.doc_id[:-4]}{suffix}"
    mutation(spec)
    return spec


def build_specs() -> list[InvoiceSpec]:
    clean = [make_clean(i) for i in range(1, 11)]
    specs = list(clean)

    def r001(spec: InvoiceSpec) -> None:
        total = Decimal(spec.fields["amount_total"].replace(",", "")) + Decimal("60")
        spec.fields["amount_total"] = money(total)
        spec.fields["total_with_tax"] = money(total)
        spec.fields["amount_in_words"] = cn_upper_amount(total)
        spec.fault = "R001 价税合计不等于不含税+税额"
        spec.expected_rules = ["R001"]
        spec.expect_status = "rejected"

    def r002(spec: InvoiceSpec) -> None:
        spec.fields["amount_in_words"] = "壹仟元整"
        spec.fault = "R002 大写金额与小写不一致"
        spec.expected_rules = ["R002"]
        spec.expect_status = "rejected"

    def r003(spec: InvoiceSpec) -> None:
        item = spec.items[1]
        new_amount = Decimal(item["amount"].replace(",", "")) + Decimal("10")
        item["amount"] = money(new_amount)
        item["unit_price"] = money(new_amount)
        spec.fault = "R003 行项目合计大于小计"
        spec.expected_rules = ["R003"]
        spec.expect_status = "rejected"

    def r004(spec: InvoiceSpec) -> None:
        spec.fields["tax_rate"] = "13%"
        spec.fault = "R004 税率13%与6%税额不匹配"
        spec.expected_rules = ["R004"]
        spec.expect_status = "review"

    def r005(spec: InvoiceSpec) -> None:
        spec.fields["buyer_tax_id"] = "12345"
        spec.fault = "R005 购方税号长度非法"
        spec.expected_rules = ["R005"]
        spec.expect_status = "review"

    def r006(spec: InvoiceSpec) -> None:
        spec.fields["invoice_date"] = (TODAY + timedelta(days=30)).isoformat()
        spec.fault = "R006 开票日期晚于今天"
        spec.expected_rules = ["R006"]
        spec.expect_status = "review"

    def r007(spec: InvoiceSpec) -> None:
        item = spec.items[0]
        unit = Decimal(item["unit_price"].replace(",", "")) * Decimal("0.8")
        item["unit_price"] = money(unit.quantize(Decimal("0.01")))
        spec.fault = "R007 数量×单价不等于行金额"
        spec.expected_rules = ["R007"]
        spec.expect_status = "review"

    def r008(spec: InvoiceSpec) -> None:
        total_with_tax = Decimal(spec.fields["amount_total"].replace(",", "")) + Decimal("20")
        spec.fields["total_with_tax"] = money(total_with_tax)
        spec.fields["amount_in_words"] = cn_upper_amount(total_with_tax)
        spec.fault = "R008 价税合计与实付合计不一致"
        spec.expected_rules = ["R008"]
        spec.expect_status = "rejected"

    def r009(spec: InvoiceSpec) -> None:
        spec.fields["invoice_number"] = "A12"
        spec.fault = "R009 发票号码位数非法"
        spec.expected_rules = ["R009"]
        spec.expect_status = "review"

    def r011(spec: InvoiceSpec) -> None:
        item = spec.items[0]
        item["quantity"] = "-2"
        item["unit_price"] = "-" + item["unit_price"]
        spec.fault = "R011 行项目数量/单价为负"
        spec.expected_rules = ["R011"]
        spec.expect_status = "rejected"

    faults = [r001, r002, r003, r004, r005, r006, r007, r008, r009, r011]
    for offset, mutation in enumerate(faults, start=1):
        # Each fault gets its own base invoice so it cannot accidentally duplicate another sample.
        bad = with_fault(make_clean(100 + offset), f"10{offset}", mutation)
        bad.doc_id = f"syn_invoice_{10 + offset:04d}"
        specs.append(bad)

    # 0021: exact duplicate of 0001 (same invoice number, same amount)
    duplicate = copy.deepcopy(clean[0])
    duplicate.doc_id = "syn_invoice_0021"
    duplicate.fault = "R012 与 0001 票号完全相同"
    duplicate.expected_rules = ["R012"]
    duplicate.expect_status = "rejected"
    specs.append(duplicate)

    # 0022: same invoice number as 0001 but different amount -> R012 + R013
    conflict = copy.deepcopy(clean[0])
    conflict.doc_id = "syn_invoice_0022"
    subtotal = Decimal("943.40")
    tax = Decimal("56.60")
    total = subtotal + tax
    item1 = Decimal("566.04")
    item2 = subtotal - item1
    conflict.fields.update(
        {
            "subtotal": money(subtotal),
            "tax_total": money(tax),
            "amount_total": money(total),
            "total_with_tax": money(total),
            "amount_in_words": cn_upper_amount(total),
        }
    )
    conflict.items = [
        {"description": "办公用品A01", "quantity": "2", "unit_price": money(item1 / 2), "amount": money(item1)},
        {"description": "会议物料C01", "quantity": "1", "unit_price": money(item2), "amount": money(item2)},
    ]
    conflict.fault = "R013 与 0001 同票号但金额不同"
    conflict.expected_rules = ["R012", "R013"]
    conflict.expect_status = "rejected"
    specs.append(conflict)

    # Extra clean invoices to reach the 50-sample synthetic target.
    for index in range(23, 51):
        specs.append(make_clean(index))
    return specs


def render(spec: InvoiceSpec, path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=520)
    page.insert_font(fontname="cjk", fontfile=FONT)

    def text(x: float, y: float, value: str, size: float = 10) -> None:
        page.insert_text((x, y), value, fontsize=size, fontname="cjk")

    text(170, 40, "增值税普通发票（合成测试）", 16)
    text(40, 70, f"发票代码：011002600111   发票号码：{spec.fields['invoice_number']}", 10)
    text(40, 88, f"开票日期：{spec.fields['invoice_date']}", 10)
    text(40, 112, f"购买方：{spec.fields['buyer_name']}", 9)
    text(330, 112, f"税号：{spec.fields['buyer_tax_id']}", 9)
    text(40, 130, f"销售方：{spec.fields['seller_name']}", 9)
    text(330, 130, f"税号：{spec.fields['seller_tax_id']}", 9)

    page.draw_rect(pymupdf.Rect(35, 150, 560, 260), color=(0, 0, 0), width=0.8)
    text(45, 168, "货物或服务名称", 9)
    text(300, 168, "数量", 9)
    text(355, 168, "单价", 9)
    text(455, 168, "金额", 9)
    page.draw_line(pymupdf.Point(35, 175), pymupdf.Point(560, 175), width=0.5)
    y = 195
    for item in spec.items:
        text(45, y, item["description"], 9)
        text(305, y, item["quantity"], 9)
        text(355, y, item["unit_price"], 9)
        text(455, y, item["amount"], 9)
        y += 24

    text(45, 290, f"合计金额（不含税）：{spec.fields['subtotal']}", 9)
    text(330, 290, f"税率：{spec.fields['tax_rate']}", 9)
    text(455, 290, f"税额：{spec.fields['tax_total']}", 9)
    text(45, 315, f"价税合计（小写）：{spec.fields['total_with_tax']}", 10)
    text(45, 340, f"价税合计（大写）：{spec.fields['amount_in_words']}", 9)
    text(45, 365, f"实付合计：{spec.fields['amount_total']}", 10)
    text(45, 400, "备注：合成测试数据，不具备法律效力", 8)

    pixmap = page.get_pixmap(dpi=DPI)
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(path)
    doc.close()


def to_extraction(spec: InvoiceSpec) -> ExtractionResult:
    fields = {name: FieldValue(value=value, source="parser") for name, value in spec.fields.items()}
    items = [
        LineItem(
            description=FieldValue(value=item["description"], source="parser"),
            quantity=FieldValue(value=item["quantity"], source="parser"),
            unit_price=FieldValue(value=item["unit_price"], source="parser"),
            amount=FieldValue(value=item["amount"], source="parser"),
        )
        for item in spec.items
    ]
    return ExtractionResult(
        doc_id=spec.doc_id,
        doc_type="cn_invoice",
        pipeline="layout_llm",
        model="synthetic_ground_truth",
        fields=fields,
        line_items=items,
    )


def main() -> None:
    specs = build_specs()
    image_dir = ROOT / "data" / "raw" / "synthetic"
    gt_dir = ROOT / "data" / "ground_truth" / "synthetic"
    for directory in (image_dir, gt_dir):
        directory.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    labels = []
    for spec in specs:
        image_path = image_dir / f"{spec.doc_id}.png"
        render(spec, image_path)
        extraction = to_extraction(spec)
        (gt_dir / f"{spec.doc_id}.json").write_text(
            extraction.model_dump_json(indent=2), encoding="utf-8"
        )
        manifest_rows.append(
            {
                "doc_id": spec.doc_id,
                "filename": image_path.relative_to(ROOT).as_posix(),
                "doc_type": "cn_invoice",
                "source_dataset": "synthetic",
                "quality_tier": "clear",
                "layout_tier": "single_column",
                "page_count": 1,
                "annotation": f"data/ground_truth/synthetic/{spec.doc_id}.json",
                "split": "test",
            }
        )
        labels.append(
            {
                "doc_id": spec.doc_id,
                "fault": spec.fault,
                "expected_rules": spec.expected_rules,
                "expect_status": spec.expect_status,
            }
        )

    labels_path = ROOT / "data" / "ground_truth" / "synthetic_labels.jsonl"
    labels_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in labels) + "\n",
        encoding="utf-8",
    )

    manifest_path = ROOT / "data" / "ground_truth" / "manifest.jsonl"
    existing = []
    if manifest_path.is_file():
        existing = [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("source_dataset") != "synthetic"
        ]
    manifest_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in existing + manifest_rows) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(specs)} synthetic invoices -> {image_dir}")
    print(f"labels -> {labels_path}")


if __name__ == "__main__":
    main()
