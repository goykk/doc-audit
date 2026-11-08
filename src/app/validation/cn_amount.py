"""Chinese financial uppercase amount conversion (人民币大写)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

DIGITS = "零壹贰叁肆伍陆柒捌玖"
SMALL_UNITS = ("", "拾", "佰", "仟")
BIG_UNITS = ("", "万", "亿", "万亿")


def _four_digits(number: int) -> str:
    text = ""
    pending_zero = False
    for position in (3, 2, 1, 0):
        digit = (number // 10**position) % 10
        if digit == 0:
            if text:
                pending_zero = True
            continue
        if pending_zero:
            text += "零"
            pending_zero = False
        text += DIGITS[digit] + SMALL_UNITS[position]
    return text


def _integer_part(number: int) -> str:
    if number == 0:
        return "零"
    groups: list[int] = []
    while number:
        groups.append(number % 10000)
        number //= 10000

    text = ""
    skipped_group = False
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if group == 0:
            skipped_group = bool(text)
            continue
        if text and (skipped_group or group < 1000):
            if not text.endswith("零"):
                text += "零"
        text += _four_digits(group) + BIG_UNITS[index]
        skipped_group = False
    return text


def cn_upper_amount(amount: Decimal | str | float | int) -> str:
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value < 0:
        raise ValueError("negative amount has no financial uppercase form")
    integer = int(value)
    fraction = int((value - integer) * 100)
    jiao, fen = divmod(fraction, 10)

    text = _integer_part(integer) + "元"
    if jiao == 0 and fen == 0:
        return text + "整"
    if jiao:
        text += DIGITS[jiao] + "角"
    if fen:
        if jiao == 0:
            text += "零"
        text += DIGITS[fen] + "分"
    else:
        text += "整"
    return text


def normalize_cn_upper(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = str(text).strip().replace(" ", "").replace("人民币", "")
    cleaned = cleaned.replace("圆", "元").replace("正", "整")
    return cleaned.rstrip("整")
