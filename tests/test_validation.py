from datetime import date

import pytest

from app.extraction_result import ExtractionResult, FieldValue, LineItem
from app.validation.engine import load_rules, validate
from app.validation.duplicates import DuplicateIndex

TODAY = date(2026, 11, 6)
RULES = load_rules()
assert len(RULES["rules"]) == 14


def item(desc="服务费", qty="1", unit="1000", amount="1000", confidence=0.99):
    return LineItem(
        description=FieldValue(value=desc, confidence=confidence),
        quantity=FieldValue(value=qty, confidence=confidence),
        unit_price=FieldValue(value=unit, confidence=confidence),
        amount=FieldValue(value=amount, confidence=confidence),
    )


def invoice(doc_id="inv1", **overrides):
    line_items = overrides.pop("line_items", [item()])
    fields = {
        "invoice_number": "12345678",
        "invoice_date": TODAY.isoformat(),
        "seller_name": "示例科技有限公司",
        "seller_tax_id": "91310000MA1K3XYZ1A",
        "buyer_tax_id": "91310000MA1K3XYZ2B",
        "subtotal": "1000",
        "tax_total": "60",
        "tax_rate": "6%",
        "amount_total": "1060",
        "total_with_tax": "1060",
        "amount_in_words": "壹仟零陆拾元整",
    }
    fields.update(overrides)
    return ExtractionResult(
        doc_id=doc_id,
        doc_type="cn_invoice",
        pipeline="layout_llm",
        fields={k: FieldValue(value=v, confidence=0.99) for k, v in fields.items()},
        line_items=line_items,
    )


def receipt(doc_id="r1", **overrides):
    line_items = overrides.pop("line_items", [item(desc="Latte", qty="1", unit="100", amount="100")])
    fields = {"subtotal": "100", "amount_total": "100"}
    fields.update(overrides)
    return ExtractionResult(
        doc_id=doc_id,
        doc_type="receipt",
        pipeline="vlm_e2e",
        fields={k: FieldValue(value=v, confidence=0.99) for k, v in fields.items()},
        line_items=line_items,
    )


def test_rules_yaml_has_14_rules():
    assert len({rule["id"] for rule in RULES["rules"]}) == 14
    assert {rule["category"] for rule in RULES["rules"]} == {
        "arithmetic",
        "cross_field",
        "format",
        "business",
        "cross_document",
        "confidence",
    }


def test_valid_invoice_is_accepted():
    report = validate(invoice(), dataset="synthetic", rules_config=RULES, today=TODAY)
    assert report.status == "accepted"
    assert not report.issues


def test_broken_invoice_is_rejected_with_actionable_issues():
    broken = invoice(
        subtotal="5000",
        tax_total="300",
        tax_rate="6%",
        amount_total="5200",
        total_with_tax="5200",
        amount_in_words="伍仟元整",
        buyer_tax_id="123",
        invoice_date="2099/01/01",
        invoice_number="12",
        line_items=[item(qty="2", unit="2500", amount="5100")],
    )
    broken.fields["buyer_tax_id"].confidence = 0.5
    report = validate(broken, dataset="synthetic", rules_config=RULES, today=TODAY)

    assert report.status == "rejected"
    rule_ids = {issue.rule_id for issue in report.issues}
    assert {"R001", "R002", "R003", "R005", "R006", "R007", "R009", "R010", "R014"} <= rule_ids
    r001 = next(issue for issue in report.issues if issue.rule_id == "R001")
    assert r001.suggested_value is None
    r003 = next(issue for issue in report.issues if issue.rule_id == "R003")
    assert r003.suggested_value is None
    assert "人工核对" in r003.message


def test_missing_fields_are_skipped_not_passed():
    sparse = invoice(amount_in_words=None, tax_rate=None, buyer_tax_id=None, seller_tax_id=None)
    report = validate(sparse, dataset="synthetic", rules_config=RULES, today=TODAY)
    by_id = {rule.rule_id: rule for rule in report.rules}
    assert by_id["R002"].status == "skipped"
    assert by_id["R004"].status == "skipped"
    assert by_id["R005"].status == "skipped"
    assert "缺少" in by_id["R002"].skip_reason


def test_negative_amount_and_quantity_are_business_errors():
    bad = receipt(line_items=[item(desc="Latte", qty="-1", unit="100", amount="-100")])
    report = validate(bad, dataset="cord", rules_config=RULES, today=TODAY)
    assert report.status == "rejected"
    fields = {issue.field_path for issue in report.issues if issue.rule_id == "R011"}
    assert {"line_items[0].quantity", "line_items[0].amount"} == fields


def test_line_item_sum_mismatch_does_not_guess_total():
    bad = receipt(subtotal="120", amount_total="120")
    report = validate(bad, dataset="cord", rules_config=RULES, today=TODAY)
    issue = next(issue for issue in report.issues if issue.rule_id == "R003")
    assert issue.current_value == "120"
    assert issue.suggested_value is None
    assert "小于目标" in issue.message


def test_line_item_sum_mismatch_names_extra_row():
    bad = receipt(
        subtotal="80",
        amount_total="80",
        line_items=[item(desc="Coffee", qty="1", unit="80", amount="80"), item(desc="TOTAL", qty="1", unit="20", amount="20")],
    )
    report = validate(bad, dataset="cord", rules_config=RULES, today=TODAY)
    issue = next(issue for issue in report.issues if issue.rule_id == "R003")
    assert issue.suggested_value is None
    assert "第 2 行" in issue.message
    assert "删除该行" in issue.message


def test_duplicate_exact_invoice_and_amount_conflict():
    index = DuplicateIndex()
    index.add(invoice("inv1"), "synthetic")
    candidate = invoice("inv2", amount_total="1200", total_with_tax="1200")
    hits = index.check(candidate, "synthetic")
    assert hits and hits[0].layer == "exact" and hits[0].amount_mismatch

    report = validate(candidate, dataset="synthetic", rules_config=RULES, duplicate_index=index, today=TODAY)
    rule_ids = {issue.rule_id for issue in report.issues}
    assert "R012" in rule_ids and "R013" in rule_ids


def test_duplicate_fingerprint_catches_changed_invoice_number():
    index = DuplicateIndex()
    original = invoice("inv1")
    index.add(original, "synthetic")
    candidate = invoice("inv2")  # same seller/date/amount/items, different invoice number
    candidate.fields["invoice_number"].value = "87654321"
    hits = index.check(candidate, "synthetic")
    assert hits[0].layer == "fingerprint"


def test_duplicate_loose_fingerprint_catches_edited_date():
    index = DuplicateIndex()
    index.add(invoice("inv1"), "synthetic")
    candidate = invoice("inv2", invoice_date="2026-11-05", invoice_number="87654321")
    hits = index.check(candidate, "synthetic")
    assert hits and hits[0].layer == "fingerprint_date"
    assert "日期" in hits[0].message


def test_duplicate_vector_layer_catches_reworded_amounts():
    index = DuplicateIndex(threshold=0.9)
    original = invoice("inv1")
    original.line_items = [item(desc="咖啡豆", amount="500"), item(desc="鲜牛奶", amount="500")]
    index.add(original, "synthetic")
    candidate = invoice("inv2", amount_total="2060", total_with_tax="2060", invoice_number="87654321")
    candidate.line_items = [item(desc="咖啡豆", amount="600"), item(desc="鲜牛奶", amount="600")]
    hits = index.check(candidate, "synthetic")
    assert any(hit.layer == "vector" for hit in hits)


def test_duplicate_index_skips_identity_poor_receipts():
    index = DuplicateIndex()
    index.add(receipt("r1"), "cord")
    candidate = receipt("r2")
    hits = index.check(candidate, "cord")
    assert hits == []  # no seller/date/invoice -> fingerprint disabled, one item -> no vector


def test_empty_extraction_is_never_auto_accepted():
    empty = ExtractionResult(
        doc_id="empty",
        doc_type="receipt",
        pipeline="vlm_e2e",
        fields={"amount_total": FieldValue(value=None, confidence=0.0)},
        line_items=[],
    )
    report = validate(empty, dataset="cord", rules_config=RULES, today=TODAY)
    assert report.status == "review"
    assert any(issue.rule_id == "R014" for issue in report.issues)
    assert "未抽取到任何有效字段" in report.issues[0].message


def test_confidence_below_threshold_goes_to_review():
    doc = receipt()
    doc.fields["amount_total"].confidence = 0.7
    report = validate(doc, dataset="cord", rules_config=RULES, today=TODAY)
    assert report.status == "review"
    assert report.min_confidence == 0.7
    assert any(issue.rule_id == "R014" for issue in report.issues)


def test_tax_id_issue_is_actionable():
    bad = invoice(buyer_tax_id="123")
    report = validate(bad, dataset="synthetic", rules_config=RULES, today=TODAY)
    issue = next(issue for issue in report.issues if issue.rule_id == "R005")
    assert "15/18/20" in issue.message
    assert issue.suggested_value is None
