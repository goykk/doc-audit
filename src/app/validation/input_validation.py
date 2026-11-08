"""Server-side validation for human edits coming from the review UI."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.evaluation.metrics import normalize_value, number_locale_for_dataset

AMOUNT_FIELDS = {
    "subtotal",
    "tax_total",
    "discount_total",
    "amount_total",
    "total_with_tax",
    "unit_price",
    "amount",
}
QUANTITY_FIELDS = {"quantity"}
TAX_ID_FIELDS = {"buyer_tax_id", "seller_tax_id"}
DATE_FIELDS = {"invoice_date", "receipt_date"}
TAX_RATE_FIELD = "tax_rate"
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%d/%m/%Y", "%d-%m-%Y")


def _field_key(field_path: str) -> str:
    return field_path.split(".")[-1].replace("]", "").split("[")[0]


def _decimal(value: Any, field_name: str, locale: str) -> Decimal | None:
    normalized = normalize_value(value, field_name, locale if field_name != "tax_rate" else "cn")
    if normalized is None:
        return None
    try:
        return Decimal(str(normalized))
    except InvalidOperation:
        return None


def _parse_rate(value: Any) -> Decimal | None:
    text = str(value).strip()
    percent = text.endswith("%")
    text = text.rstrip("%").strip()
    try:
        rate = Decimal(text)
    except InvalidOperation:
        return None
    if percent:
        return rate / 100
    return rate / 100 if rate > 1 else rate


def validate_review_value(field_path: str, value: Any, dataset: str) -> Any:
    """Validate and normalize one human-entered value. Raises ValueError with a user message."""
    key = _field_key(field_path)
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError("值不能为空")

    locale = number_locale_for_dataset(dataset)
    if key in AMOUNT_FIELDS:
        parsed = _decimal(text, key, locale)
        if parsed is None:
            raise ValueError(f"{key} 不是合法金额")
        if parsed < 0:
            raise ValueError(f"{key} 不能为负数")
        return format(parsed, "f")

    if key in QUANTITY_FIELDS:
        parsed = _decimal(text, key, locale)
        if parsed is None:
            raise ValueError("quantity 不是合法数量")
        if parsed <= 0:
            raise ValueError("quantity 必须大于 0")
        return format(parsed, "f")

    if key == TAX_RATE_FIELD:
        rate = _parse_rate(text)
        if rate is None:
            raise ValueError("tax_rate 不是合法税率")
        if rate < 0 or rate > 1:
            raise ValueError("tax_rate 必须在 0% 到 100% 之间")
        return text

    if key in DATE_FIELDS:
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        raise ValueError("日期格式不合法，请使用 YYYY-MM-DD 或 YYYY/MM/DD")

    if key in TAX_ID_FIELDS:
        if len(text) not in {15, 18, 20} or not re.fullmatch(r"[0-9A-Za-z]+", text):
            raise ValueError("纳税人识别号必须是 15/18/20 位字母数字")
        return text

    if len(text) > 200:
        raise ValueError("文本长度不能超过 200")
    return text


__all__ = ["validate_review_value"]
