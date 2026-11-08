import pytest

from app.validation.input_validation import validate_review_value


def test_amount_is_normalized_and_non_negative():
    assert validate_review_value("amount_total", "1,200.50", "synthetic") == "1200.5"
    assert validate_review_value("line_items[0].amount", "28.000", "cord") == "28000"
    with pytest.raises(ValueError, match="负数"):
        validate_review_value("amount_total", "-1", "synthetic")
    with pytest.raises(ValueError, match="合法金额"):
        validate_review_value("amount_total", "abc", "synthetic")


def test_quantity_must_be_positive():
    assert validate_review_value("line_items[0].quantity", "2X", "cord") == "2"
    with pytest.raises(ValueError, match="大于 0"):
        validate_review_value("line_items[0].quantity", "0", "cord")


def test_tax_rate_range():
    assert validate_review_value("tax_rate", "6%", "synthetic") == "6%"
    assert validate_review_value("tax_rate", "0.06", "synthetic") == "0.06"
    with pytest.raises(ValueError, match="0%"):
        validate_review_value("tax_rate", "150", "synthetic")


def test_date_is_normalized():
    assert validate_review_value("invoice_date", "2026/11/08", "synthetic") == "2026-11-08"
    with pytest.raises(ValueError, match="日期格式"):
        validate_review_value("invoice_date", "11/31/2026", "synthetic")


def test_tax_id_length_and_charset():
    assert validate_review_value("buyer_tax_id", "91310000MA1K35Q123", "synthetic") == "91310000MA1K35Q123"
    with pytest.raises(ValueError, match="15/18/20"):
        validate_review_value("buyer_tax_id", "123", "synthetic")


def test_blank_text_is_rejected():
    with pytest.raises(ValueError, match="不能为空"):
        validate_review_value("invoice_number", "  ", "synthetic")
