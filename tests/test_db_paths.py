import pytest

from app.db.repository import set_field_value


def test_set_header_value_marks_reviewer():
    result = {"fields": {"amount_total": {"value": "100", "confidence": 0.9, "source": "llm"}}}
    set_field_value(result, "amount_total", "110")
    assert result["fields"]["amount_total"]["value"] == "110"
    assert result["fields"]["amount_total"]["source"] == "reviewer"
    assert result["fields"]["amount_total"]["confidence"] == 1.0


def test_set_missing_header_creates_field():
    result = {"fields": {}}
    set_field_value(result, "new_field", "x")
    assert result["fields"]["new_field"]["value"] == "x"


def test_set_line_item_value():
    result = {"line_items": [{"amount": {"value": "10", "confidence": 0.8}}]}
    set_field_value(result, "line_items[0].amount", "12")
    assert result["line_items"][0]["amount"]["value"] == "12"
    assert result["line_items"][0]["amount"]["source"] == "reviewer"


def test_invalid_line_item_paths_are_rejected():
    with pytest.raises(ValueError):
        set_field_value({"line_items": []}, "line_items[pred_only:0].amount", "1")


def test_missing_line_item_is_created_when_adopting_extra_row():
    result = {"line_items": []}
    set_field_value(result, "line_items[1].amount", "12")
    assert len(result["line_items"]) == 2
    assert result["line_items"][0]["amount"]["value"] is None
    assert result["line_items"][1]["amount"]["value"] == "12"


def test_review_queue_filter_sql():
    from app.db.repository import _review_where

    where, params = _review_where("pending", "R003", "syn")
    assert "r.rule_id = :rule_id" in where
    assert "LIKE :prefix" in where
    assert "MATCH" not in where
    assert params == {"status": "pending", "rule_id": "R003", "prefix": "syn%"}

    where, params = _review_where("pending", None, "行项目")
    assert "MATCH(r.reason)" in where
    assert params == {"status": "pending", "ft_q": '"行项目"'}

    where, params = _review_where("pending", None, "r004")
    assert "r.rule_id = :rule_exact" in where
    assert params == {"status": "pending", "rule_exact": "R004"}


def test_prefix_search_uses_union_and_classifies_modes():
    from app.db.repository import _prefix_id_sql, _search_mode

    assert _search_mode("R003") == ("rule", "R003")
    assert _search_mode("syn_invoice_0013") == ("prefix", "syn_invoice_0013")
    assert _search_mode("行项目") == ("fulltext", "行项目")

    sql, params = _prefix_id_sql("pending", None, "syn")
    assert sql.count("UNION") == 2
    assert params == {"status": "pending", "prefix": "syn%"}


def test_document_filters_sql():
    from app.db.repository import _document_filters

    where, params = _document_filters("cord", "accepted")
    assert "d.source_dataset = :dataset" in where
    assert "d.status = :status" in where
    assert params == {"dataset": "cord", "status": "accepted"}
    where, params = _document_filters(None, None, "syn")
    assert "LIKE :qprefix" in where
    assert "MATCH(d.filename)" in where
    assert params == {"qprefix": "syn%", "ft_q": '"syn"'}
    assert _document_filters() == ("", {})

    from app.db.repository import _document_search_ids_sql

    sql, params = _document_search_ids_sql("cord", "accepted", "invoice")
    assert sql.count("UNION") == 1
    assert "d.status = :status" in sql
    assert params == {
        "dataset": "cord",
        "status": "accepted",
        "qprefix": "invoice%",
        "ft_q": '"invoice"',
    }


def test_stats_cache_invalidation():
    import time

    from app.db import repository

    repository._STATS_CACHE[""] = {
        "at": time.monotonic(),
        "version": "v1",
        "data": {"cached": True},
    }
    repository.invalidate_stats_cache()
    assert repository._STATS_CACHE == {}


def test_audit_event_filters():
    from app.db.repository import filter_audit_events

    events = [
        {"pipeline": "layout_llm", "event": "reviewed", "at": "2026-11-08T10:00:00"},
        {"pipeline": "vlm_e2e", "event": "reviewed", "at": "2026-11-07T10:00:00"},
        {"pipeline": "layout_llm", "event": "revalidated", "at": "2026-11-06T10:00:00"},
    ]
    assert len(filter_audit_events(events, pipeline="layout_llm")) == 2
    assert len(filter_audit_events(events, event="reviewed")) == 2
    assert len(filter_audit_events(events, date_from="2026-11-07", date_to="2026-11-08")) == 2
    assert len(filter_audit_events(events, pipeline="layout_llm", event="reviewed")) == 1


def test_csv_safe_blocks_formula_injection():
    from app.api.main import _csv_safe

    assert _csv_safe("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert _csv_safe("+cmd") == "'+cmd"
    assert _csv_safe("@user") == "'@user"
    assert _csv_safe("-5") == "-5"
    assert _csv_safe({"a": 1}) == '{"a": 1}'
    assert _csv_safe(None) == ""
