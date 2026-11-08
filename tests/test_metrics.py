import pytest

from app.evaluation.metrics import (
    FieldSpec,
    Sample,
    compare,
    evaluate,
    line_item_correct,
    normalize_value,
)
from app.extraction_result import ExtractionResult, FieldValue, LineItem

SPEC = FieldSpec(
    fields=["subtotal", "tax_total", "amount_total"],
    line_items=["description", "quantity", "unit_price", "amount"],
)


def _result(doc_id: str, fields: dict, items: list[dict] | None = None, latency=0):
    return ExtractionResult(
        doc_id=doc_id,
        pipeline="layout_llm",
        fields={k: FieldValue(value=v) for k, v in fields.items()},
        line_items=[
            LineItem(**{k: FieldValue(value=v) for k, v in item.items()})
            for item in (items or [])
        ],
        latency_ms=latency,
    )


def test_amount_and_text_normalization():
    assert normalize_value("1,000.00", "amount_total") == "1000"
    assert normalize_value("¥ 55.10", "amount_total") == "55.1"
    assert normalize_value("(12.50)", "amount_total") == "-12.5"
    assert normalize_value("  ", "amount_total") is None
    assert normalize_value(" Latte  ", "description") == "latte"
    assert normalize_value("1X", "quantity") == "1"
    assert normalize_value("@11000", "unit_price") == "11000"
    # CORD/Indonesian receipts use dot as the thousands separator.
    assert normalize_value("28.000", "amount_total", "id") == "28000"
    assert normalize_value("28,000", "amount_total", "id") == "28000"
    assert normalize_value("1.234.567", "amount_total", "id") == "1234567"


def test_compare_keeps_missing_and_error_distinct():
    assert compare(None, None, "tax_total") == "both_null"
    assert compare(None, "5.00", "tax_total") == "hallucination"
    assert compare("5.00", None, "tax_total") == "miss"
    assert compare("5.00", "6.00", "tax_total") == "wrong"
    assert compare("1,000.00", "1000", "amount_total") == "correct"


def test_identical_prediction_scores_perfect_and_line_items_count():
    truth = _result(
        "d1",
        {"subtotal": "100.00", "tax_total": None, "amount_total": "110.00"},
        [{"description": "Latte", "quantity": "2", "unit_price": "50", "amount": "100"}],
    )
    pred = truth.model_copy(update={"latency_ms": 120})
    sample = Sample("d1", "cord", truth, pred, "clear", "single_column")
    report = evaluate([sample], SPEC)
    assert report["summary"]["field_metrics"]["f1"] == 1.0
    assert report["summary"]["line_item_doc_accuracy"] == 1.0
    assert report["summary"]["field_metrics"]["both_null"] == 1
    assert report["summary"]["latency_ms"]["p50"] == 120


def test_wrong_miss_and_hallucination_are_counted_separately():
    truth = _result("d1", {"subtotal": "100", "tax_total": None, "amount_total": "110"})
    pred = _result("d1", {"subtotal": "100", "tax_total": "5", "amount_total": "120"})
    report = evaluate([Sample("d1", "cord", truth, pred)], SPEC)
    m = report["summary"]["field_metrics"]
    assert (m["tp"], m["fp"], m["fn"]) == (1, 2, 1)
    assert m["hallucination_rate"] == 0.3333
    assert m["miss_rate"] == 0.0
    kinds = {e["field_path"]: e["kind"] for e in report["errors"]}
    assert kinds == {"tax_total": "hallucination", "amount_total": "wrong"}


def test_extra_line_item_is_hallucination_and_breaks_doc_accuracy():
    truth = _result("d1", {"subtotal": None, "tax_total": None, "amount_total": "10"})
    pred = _result(
        "d1",
        {"subtotal": None, "tax_total": None, "amount_total": "10"},
        [{"description": "Ghost", "quantity": "1", "unit_price": "10", "amount": "10"}],
    )
    report = evaluate([Sample("d1", "cord", truth, pred)], SPEC)
    assert report["summary"]["field_metrics"]["hallucination_rate"] == 0.8
    assert report["summary"]["line_item_doc_accuracy"] == 0.0
    assert not line_item_correct(truth, pred, SPEC)


def test_line_item_order_swap_is_aligned_not_penalized():
    truth = _result(
        "d1",
        {"subtotal": None, "tax_total": None, "amount_total": "30"},
        [
            {"description": "Tea", "quantity": "1", "unit_price": None, "amount": "10"},
            {"description": "Cake", "quantity": "1", "unit_price": None, "amount": "20"},
        ],
    )
    pred = truth.model_copy(deep=True)
    pred.line_items = [pred.line_items[1], pred.line_items[0]]
    report = evaluate([Sample("d1", "cord", truth, pred)], SPEC)
    assert report["summary"]["field_metrics"]["f1"] == 1.0
    assert report["summary"]["line_item_doc_accuracy"] == 1.0
    assert line_item_correct(truth, pred, SPEC)


def test_line_item_with_correct_amount_aligns_even_if_description_missing():
    truth = _result(
        "d1",
        {"subtotal": None, "tax_total": None, "amount_total": "10"},
        [{"description": "Tea", "quantity": None, "unit_price": None, "amount": "10"}],
    )
    pred = _result(
        "d1",
        {"subtotal": None, "tax_total": None, "amount_total": "10"},
        [{"description": None, "quantity": None, "unit_price": None, "amount": "10"}],
    )
    report = evaluate([Sample("d1", "cord", truth, pred)], SPEC)
    kinds = {e["field_path"]: e["kind"] for e in report["errors"]}
    assert kinds == {"line_items[0].description": "miss"}
    assert not line_item_correct(truth, pred, SPEC)


def test_line_item_accuracy_accepts_matching_nulls():
    truth = _result(
        "d1",
        {"subtotal": None, "tax_total": None, "amount_total": "18"},
        [{"description": "Tea", "quantity": "1", "unit_price": None, "amount": "18"}],
    )
    assert line_item_correct(truth, truth.model_copy(deep=True), SPEC)


def test_empty_sample_set_is_rejected():
    with pytest.raises(ValueError):
        evaluate([], SPEC)
