"""Three-layer duplicate receipt detection.

1. exact: same invoice number
2. fingerprint: hash(seller + total + date + normalized line items)
3. vector: character n-gram cosine similarity of line-item text, threshold 0.92

The vector layer is a local lexical embedding so the check runs offline and deterministically.
It is intentionally labelled as a fallback that can be swapped for a semantic embedding model.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass

from app.evaluation.metrics import number_locale_for_dataset, normalize_value
from app.extraction_result import ExtractionResult


@dataclass(frozen=True)
class DuplicateRecord:
    doc_id: str
    invoice_number: str | None
    amount_total: str | None
    seller: str | None
    date: str | None
    fingerprint: str
    loose_fingerprint: str
    vector: Counter


@dataclass(frozen=True)
class DuplicateHit:
    layer: str
    matched_doc_id: str
    score: float
    amount_mismatch: bool
    message: str


def _canonical(value: object, field_name: str, dataset: str) -> str | None:
    normalized = normalize_value(value, field_name, number_locale_for_dataset(dataset))
    return str(normalized) if normalized is not None else None


def _value(extraction: ExtractionResult, *names: str):
    for name in names:
        field_value = extraction.fields.get(name)
        if field_value is not None and field_value.value is not None:
            return field_value.value
    return None


def _item_lines(extraction: ExtractionResult, dataset: str) -> list[str]:
    lines = []
    for item in extraction.line_items:
        parts = [
            _canonical(item.description.value, "description", dataset) or "",
            _canonical(item.amount.value, "amount", dataset) or "",
        ]
        line = " ".join(part for part in parts if part)
        if line:
            lines.append(line)
    return lines


def _item_descriptions(extraction: ExtractionResult, dataset: str) -> list[str]:
    descriptions = []
    for item in extraction.line_items:
        text = _canonical(item.description.value, "description", dataset)
        if text:
            descriptions.append(text)
    return descriptions


def _fold(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text).casefold()


def _ngrams(text: str, size: int = 3) -> Counter:
    folded = _fold(text)
    if len(folded) < size:
        return Counter({folded: 1}) if folded else Counter()
    return Counter(folded[i : i + size] for i in range(len(folded) - size + 1))


def _cosine(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    dot = sum(left[gram] * right[gram] for gram in common)
    norm_left = sum(value * value for value in left.values()) ** 0.5
    norm_right = sum(value * value for value in right.values()) ** 0.5
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


def build_record(extraction: ExtractionResult, dataset: str) -> DuplicateRecord:
    invoice_number = _canonical(_value(extraction, "invoice_number"), "invoice_number", dataset)
    amount_total = _canonical(_value(extraction, "amount_total"), "amount_total", dataset)
    seller = _canonical(_value(extraction, "seller_name", "merchant_name"), "seller_name", dataset)
    date = _canonical(_value(extraction, "invoice_date", "receipt_date"), "invoice_date", dataset)
    lines = _item_lines(extraction, dataset)
    descriptions = _item_descriptions(extraction, dataset)

    # Identity-poor receipts (no seller and no date) do not get a fingerprint:
    # two identical orders from different days are not duplicates.
    identity = "|".join([seller or "", date or ""])
    fingerprint = ""
    loose_fingerprint = ""
    if identity.strip("|"):
        payload = identity + "|" + (amount_total or "") + "|" + "|".join(sorted(lines))
        fingerprint = hashlib.md5(payload.encode("utf-8")).hexdigest()
    if seller:
        # Ignore the date so an edited-date duplicate still collides.
        loose_payload = seller + "|" + (amount_total or "") + "|" + "|".join(sorted(lines))
        loose_fingerprint = hashlib.md5(loose_payload.encode("utf-8")).hexdigest()

    # The vector layer needs several item descriptions; a single line is too weak to
    # distinguish a repeated purchase from the same product bought twice.
    vector = _ngrams(" ".join(descriptions)) if len(descriptions) >= 2 else Counter()
    return DuplicateRecord(
        doc_id=extraction.doc_id,
        invoice_number=invoice_number,
        amount_total=amount_total,
        seller=seller,
        date=date,
        fingerprint=fingerprint,
        loose_fingerprint=loose_fingerprint,
        vector=vector,
    )


class DuplicateIndex:
    def __init__(self, threshold: float = 0.92) -> None:
        self.threshold = threshold
        self.records: list[DuplicateRecord] = []

    def add(self, extraction: ExtractionResult, dataset: str) -> None:
        record = build_record(extraction, dataset)
        if any(existing.doc_id == record.doc_id for existing in self.records):
            return
        self.records.append(record)

    def check(self, extraction: ExtractionResult, dataset: str) -> list[DuplicateHit]:
        candidate = build_record(extraction, dataset)
        hits: dict[str, DuplicateHit] = {}

        for record in self.records:
            if record.doc_id == candidate.doc_id:
                continue
            if candidate.invoice_number and record.invoice_number == candidate.invoice_number:
                mismatch = bool(
                    candidate.amount_total
                    and record.amount_total
                    and candidate.amount_total != record.amount_total
                )
                hits[record.doc_id] = DuplicateHit(
                    layer="exact",
                    matched_doc_id=record.doc_id,
                    score=1.0,
                    amount_mismatch=mismatch,
                    message=f"票号 {candidate.invoice_number} 已存在"
                    + ("，且金额不一致" if mismatch else ""),
                )
                continue
            if candidate.fingerprint and record.fingerprint == candidate.fingerprint:
                hits.setdefault(
                    record.doc_id,
                    DuplicateHit(
                        layer="fingerprint",
                        matched_doc_id=record.doc_id,
                        score=1.0,
                        amount_mismatch=False,
                        message="卖方+金额+日期+行项目指纹与已有单据一致",
                    ),
                )
                continue
            if (
                candidate.loose_fingerprint
                and record.loose_fingerprint == candidate.loose_fingerprint
                and candidate.date != record.date
            ):
                hits.setdefault(
                    record.doc_id,
                    DuplicateHit(
                        layer="fingerprint_date",
                        matched_doc_id=record.doc_id,
                        score=0.98,
                        amount_mismatch=False,
                        message="卖方+金额+行项目一致但日期不同，疑似篡改日期重复报销",
                    ),
                )
                continue
            score = _cosine(candidate.vector, record.vector)
            if score >= self.threshold:
                hits.setdefault(
                    record.doc_id,
                    DuplicateHit(
                        layer="vector",
                        matched_doc_id=record.doc_id,
                        score=round(score, 4),
                        amount_mismatch=False,
                        message=f"行项目文本向量相似度 {score:.4f} ≥ {self.threshold}",
                    ),
                )
        return sorted(hits.values(), key=lambda hit: (-hit.score, hit.matched_doc_id))
