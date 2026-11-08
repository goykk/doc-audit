import pytest

from app.validation.cn_amount import cn_upper_amount, normalize_cn_upper


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "零元整"),
        ("100", "壹佰元整"),
        ("1001", "壹仟零壹元整"),
        ("1010", "壹仟零壹拾元整"),
        ("5200", "伍仟贰佰元整"),
        ("100000", "壹拾万元整"),
        ("100000000", "壹亿元整"),
        ("100010000", "壹亿零壹万元整"),
        ("100000001", "壹亿零壹元整"),
        ("123456789.12", "壹亿贰仟叁佰肆拾伍万陆仟柒佰捌拾玖元壹角贰分"),
        ("100.50", "壹佰元伍角整"),
        ("100.05", "壹佰元零伍分"),
        ("105.06", "壹佰零伍元零陆分"),
    ],
)
def test_cn_upper_amount(value, expected):
    assert cn_upper_amount(value) == expected


def test_negative_amount_rejected():
    with pytest.raises(ValueError):
        cn_upper_amount("-1")


def test_normalize_cn_upper_handles_currency_aliases():
    assert normalize_cn_upper("人民币壹佰元整") == "壹佰元"
    assert normalize_cn_upper("壹佰圆正") == "壹佰元"
