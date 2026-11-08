"""Field-level evaluation with explicit null semantics.

Rules:
- only whitelisted field paths are scored;
- truth=null & pred=null  -> both_null, excluded from P/R/F1;
- truth=null & pred!=null -> hallucination (FP);
- truth!=null & pred=null -> miss (FN);
- both present but unequal -> wrong (both FP and FN).
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, Iterable

from app.extraction_result import ExtractionResult

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

_CURRENCY = re.compile(r"[¥￥$€£,\s]")
_EMPTY = {"", "-", "--", "n/a", "na", "null", "none"}
_ID_THOUSANDS = re.compile(r"^\d{1,3}(?:\.\d{3})+$")


def _number_locale(dataset: str) -> str:
    # CORD receipts are Indonesian: dot is the thousands separator (28.000 = 28000),
    # while the published annotations use a comma (28,000).
    return "id" if dataset == "cord" else "cn"


def number_locale_for_dataset(dataset: str) -> str:
    return _number_locale(dataset)


def normalize_value(value: Any, field_name: str, number_locale: str = "cn") -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        text = str(value)
    else:
        text = str(value).strip()
    if text.casefold() in _EMPTY:
        return None
    if field_name in AMOUNT_FIELDS or field_name in QUANTITY_FIELDS:
        cleaned = _CURRENCY.sub("", text).lstrip("@")
        negative = cleaned.startswith("(") and cleaned.endswith(")")
        cleaned = cleaned.strip("()")
        if field_name in QUANTITY_FIELDS:
            cleaned = re.sub(r"[xX×]$", "", cleaned)
        if number_locale == "id":
            if "." in cleaned and "," in cleaned:
                cleaned = cleaned.replace(".", "").replace(",", ".")
            elif _ID_THOUSANDS.match(cleaned):
                cleaned = cleaned.replace(".", "")
            else:
                cleaned = cleaned.replace(",", "")
        try:
            number = Decimal(cleaned)
        except InvalidOperation:
            return text.casefold()
        if negative:
            number = -number
        return format(number.normalize(), "f")
    return " ".join(text.split()).casefold()


def compare(truth: Any, pred: Any, field_name: str, number_locale: str = "cn") -> str:
    t = normalize_value(truth, field_name, number_locale)
    p = normalize_value(pred, field_name, number_locale)
    if t is None and p is None:
        return "both_null"
    if t is None:
        return "hallucination"
    if p is None:
        return "miss"
    return "correct" if t == p else "wrong"


def _field_name(path: str) -> str:
    return path.rsplit(".", 1)[-1]


@dataclass
class Counts:
    correct: int = 0
    wrong: int = 0
    hallucination: int = 0
    miss: int = 0
    both_null: int = 0

    def add(self, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)

    def merge(self, other: "Counts") -> None:
        for name in ("correct", "wrong", "hallucination", "miss", "both_null"):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def summary(self) -> dict[str, Any]:
        tp = self.correct
        fp = self.wrong + self.hallucination
        fn = self.wrong + self.miss
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        predicted_present = tp + fp
        truth_present = tp + fn
        return {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "both_null": self.both_null,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "hallucination_rate": round(self.hallucination / predicted_present, 4)
            if predicted_present
            else 0.0,
            "miss_rate": round(self.miss / truth_present, 4) if truth_present else 0.0,
        }


@dataclass
class Sample:
    doc_id: str
    dataset: str
    truth: ExtractionResult
    pred: ExtractionResult
    quality_tier: str = "unknown"
    layout_tier: str = "unknown"


@dataclass
class FieldSpec:
    fields: list[str]
    line_items: list[str]

    def paths(self, item_count: int) -> list[str]:
        paths = list(self.fields)
        for index in range(item_count):
            paths.extend(f"line_items[{index}].{name}" for name in self.line_items)
        return paths


def _values_for(result: ExtractionResult) -> dict[str, Any]:
    return result.flat_values()


def _item_similarity(truth_item, pred_item, number_locale: str) -> float:
    t_desc = normalize_value(truth_item.description.value, "description") or ""
    p_desc = normalize_value(pred_item.description.value, "description") or ""
    desc_ratio = SequenceMatcher(None, t_desc, p_desc).ratio() if t_desc and p_desc else 0.0
    amount_match = (
        compare(truth_item.amount.value, pred_item.amount.value, "amount", number_locale)
        == "correct"
    )
    quantity_match = (
        compare(truth_item.quantity.value, pred_item.quantity.value, "quantity", number_locale)
        == "correct"
    )
    return 0.6 * desc_ratio + 0.3 * amount_match + 0.1 * quantity_match


def align_line_items(
    truth: ExtractionResult, pred: ExtractionResult, number_locale: str = "cn"
) -> tuple[dict[int, int], list[int]]:
    """Greedy one-to-one alignment so row order alone does not cause a total mismatch."""
    candidates = []
    for ti, truth_item in enumerate(truth.line_items):
        for pi, pred_item in enumerate(pred.line_items):
            score = _item_similarity(truth_item, pred_item, number_locale)
            if score >= 0.3:
                candidates.append((score, ti, pi))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

    matched: dict[int, int] = {}
    used_pred: set[int] = set()
    for _, ti, pi in candidates:
        if ti in matched or pi in used_pred:
            continue
        matched[ti] = pi
        used_pred.add(pi)
    extras = [pi for pi in range(len(pred.line_items)) if pi not in used_pred]
    return matched, extras


def score_sample(sample: Sample, spec: FieldSpec) -> tuple[dict[str, str], list[dict]]:
    truth = _values_for(sample.truth)
    pred = _values_for(sample.pred)
    number_locale = _number_locale(sample.dataset)
    outcomes: dict[str, str] = {}
    errors: list[dict] = []
    for path in spec.fields:
        field_name = _field_name(path)
        outcome = compare(truth.get(path), pred.get(path), field_name, number_locale)
        outcomes[path] = outcome
        if outcome in {"wrong", "hallucination", "miss"}:
            errors.append(
                {
                    "doc_id": sample.doc_id,
                    "field_path": path,
                    "kind": outcome,
                    "truth": truth.get(path),
                    "pred": pred.get(path),
                }
            )

    matched, extras = align_line_items(sample.truth, sample.pred, number_locale)
    for ti in range(len(sample.truth.line_items)):
        pi = matched.get(ti)
        for name in spec.line_items:
            path = f"line_items[{ti}].{name}"
            t_val = getattr(sample.truth.line_items[ti], name).value
            p_val = getattr(sample.pred.line_items[pi], name).value if pi is not None else None
            outcome = compare(t_val, p_val, name, number_locale)
            outcomes[path] = outcome
            if outcome in {"wrong", "hallucination", "miss"}:
                errors.append(
                    {
                        "doc_id": sample.doc_id,
                        "field_path": path,
                        "kind": outcome,
                        "truth": t_val,
                        "pred": p_val,
                    }
                )
    for pi in extras:
        for name in spec.line_items:
            path = f"line_items[pred_only:{pi}].{name}"
            p_val = getattr(sample.pred.line_items[pi], name).value
            outcomes[path] = compare(None, p_val, name, number_locale)
            if outcomes[path] in {"hallucination"}:
                errors.append(
                    {
                        "doc_id": sample.doc_id,
                        "field_path": path,
                        "kind": "hallucination",
                        "truth": None,
                        "pred": p_val,
                    }
                )
    return outcomes, errors


def line_item_correct(
    truth: ExtractionResult,
    pred: ExtractionResult,
    spec: FieldSpec,
    number_locale: str = "cn",
) -> bool:
    if len(truth.line_items) != len(pred.line_items):
        return False
    matched, extras = align_line_items(truth, pred, number_locale)
    if extras or len(matched) != len(truth.line_items):
        return False
    for ti, pi in matched.items():
        for name in spec.line_items:
            t_val = getattr(truth.line_items[ti], name)
            p_val = getattr(pred.line_items[pi], name)
            if compare(t_val.value, p_val.value, name, number_locale) not in {"correct", "both_null"}:
                return False
    return True


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def evaluate(samples: Iterable[Sample], spec: FieldSpec, include_errors: int = 200) -> dict:
    samples = list(samples)
    if not samples:
        raise ValueError("no samples to evaluate")

    overall = Counts()
    by_field: dict[str, Counts] = {}
    by_path: dict[str, Counts] = {}
    strata: dict[str, dict[str, Counts]] = {"quality_tier": {}, "layout_tier": {}, "dataset": {}}
    all_errors: list[dict] = []
    line_ok = 0
    latencies: list[int] = []
    cost_total = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    predicted_values = 0
    evidence_values = 0

    for sample in samples:
        outcomes, errors = score_sample(sample, spec)
        sample_counts = Counts()
        for path, outcome in outcomes.items():
            sample_counts.add(outcome)
            by_path.setdefault(path, Counts()).add(outcome)
            by_field.setdefault(_field_name(path), Counts()).add(outcome)
        overall.merge(sample_counts)

        for dimension, value in (
            ("quality_tier", sample.quality_tier),
            ("layout_tier", sample.layout_tier),
            ("dataset", sample.dataset),
        ):
            strata[dimension].setdefault(value, Counts()).merge(sample_counts)

        if line_item_correct(
            sample.truth, sample.pred, spec, _number_locale(sample.dataset)
        ):
            line_ok += 1
        for _, field_value in sample.pred.iter_fields():
            if field_value.value is not None:
                predicted_values += 1
                if field_value.bbox is not None:
                    evidence_values += 1
        latencies.append(sample.pred.latency_ms)
        cost_total += sample.pred.cost_cny
        prompt_tokens += sample.pred.prompt_tokens
        completion_tokens += sample.pred.completion_tokens
        all_errors.extend(errors)

    report = {
        "summary": {
            "docs": len(samples),
            "scored_fields": overall.correct + overall.wrong + overall.hallucination + overall.miss,
            "field_metrics": overall.summary(),
            "line_item_doc_accuracy": round(line_ok / len(samples), 4),
            "evidence_coverage": round(evidence_values / predicted_values, 4)
            if predicted_values
            else 0.0,
            "latency_ms": {
                "p50": int(statistics.median(latencies)) if latencies else 0,
                "p95": _p95(latencies),
                "mean": round(statistics.fmean(latencies), 1) if latencies else 0.0,
            },
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "cost_cny_total": round(cost_total, 6),
                "cost_cny_per_doc": round(cost_total / len(samples), 6),
            },
        },
        "by_field": {name: counts.summary() for name, counts in sorted(by_field.items())},
        "by_field_path": {path: counts.summary() for path, counts in sorted(by_path.items())},
        "strata": {
            dimension: {value: counts.summary() for value, counts in groups.items()}
            for dimension, groups in strata.items()
        },
        "errors": all_errors[:include_errors],
        "error_count": len(all_errors),
    }
    return report


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    metrics = summary["field_metrics"]
    lines = [
        "# 字段级评测报告",
        "",
        f"- 文档数：{summary['docs']}",
        f"- 参与评分的字段实例：{summary['scored_fields']}",
        f"- 字段级 P / R / F1：{metrics['precision']:.4f} / {metrics['recall']:.4f} / {metrics['f1']:.4f}",
        f"- 幻觉率：{metrics['hallucination_rate']:.4f}",
        f"- 漏抽率：{metrics['miss_rate']:.4f}",
        f"- 行项目整单准确率：{summary['line_item_doc_accuracy']:.4f}",
        f"- 证据覆盖率（有值字段中带 bbox 的比例）：{summary['evidence_coverage']:.4f}",
        f"- 时延 P50 / P95：{summary['latency_ms']['p50']} / {summary['latency_ms']['p95']} ms",
        f"- Token：输入 {summary['usage']['prompt_tokens']} / 输出 {summary['usage']['completion_tokens']}",
        f"- 成本：¥{summary['usage']['cost_cny_total']:.4f}，单文档 ¥{summary['usage']['cost_cny_per_doc']:.4f}",
        "",
        "## 分层",
        "",
        "| 维度 | 分组 | F1 | 幻觉率 | 漏抽率 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for dimension, groups in report["strata"].items():
        for value, m in groups.items():
            lines.append(
                f"| {dimension} | {value} | {m['f1']:.4f} | {m['hallucination_rate']:.4f} | {m['miss_rate']:.4f} |"
            )
    lines += ["", "## 字段", "", "| 字段 | P | R | F1 | TP | FP | FN |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, m in report["by_field"].items():
        lines.append(
            f"| {name} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['tp']} | {m['fp']} | {m['fn']} |"
        )
    if report["errors"]:
        lines += ["", "## 前 20 条错误", "", "| 文档 | 字段 | 类型 | 真值 | 预测 |", "| --- | --- | --- | --- | --- |"]
        for error in report["errors"][:20]:
            lines.append(
                f"| {error['doc_id']} | {error['field_path']} | {error['kind']} | "
                f"{error['truth']} | {error['pred']} |"
            )
    return "\n".join(lines) + "\n"
