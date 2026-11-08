"""YAML-driven validation / audit engine.

Design notes:
- rules declare checks; Python holds the primitives (no eval of arbitrary YAML);
- a rule whose required fields are missing is SKIPPED, never counted as passed;
- arithmetic uses Decimal and a relative tolerance to avoid float noise.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

import yaml

from app.evaluation.metrics import normalize_value, number_locale_for_dataset
from app.extraction_result import ExtractionResult
from app.validation.cn_amount import cn_upper_amount, normalize_cn_upper
from app.validation.duplicates import DuplicateIndex

DEFAULT_RULES_PATH = Path(__file__).with_name("rules.yaml")


class MissingField(Exception):
    pass


@dataclass(frozen=True)
class Issue:
    rule_id: str
    rule_name: str
    level: str
    field_path: str | None
    message: str
    current_value: Any = None
    suggested_value: Any = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuleResult:
    rule_id: str
    name: str
    category: str
    level: str
    status: str  # passed / failed / skipped
    issues: list[Issue] = field(default_factory=list)
    skip_reason: str | None = None


@dataclass
class ValidationReport:
    doc_id: str
    status: str
    min_confidence: float
    issues: list[Issue]
    rules: list[RuleResult]

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "warn"]

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "status": self.status,
            "min_confidence": self.min_confidence,
            "counts": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "passed": sum(1 for r in self.rules if r.status == "passed"),
                "failed": sum(1 for r in self.rules if r.status == "failed"),
                "skipped": sum(1 for r in self.rules if r.status == "skipped"),
            },
            "issues": [issue.as_dict() for issue in self.issues],
            "rules": [
                {
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "category": rule.category,
                    "level": rule.level,
                    "status": rule.status,
                    "skip_reason": rule.skip_reason,
                    "issues": [issue.as_dict() for issue in rule.issues],
                }
                for rule in self.rules
            ],
        }


class _Context:
    def __init__(self, extraction: ExtractionResult, dataset: str, today: date):
        self.extraction = extraction
        self.dataset = dataset
        self.today = today
        self.locale = number_locale_for_dataset(dataset)

    def value(self, name: str):
        field_value = self.extraction.fields.get(name)
        return field_value.value if field_value is not None else None

    def decimal(self, name: str) -> Decimal | None:
        return _decimal(self.value(name), name, self.locale)

    def first_decimal(self, names: list[str]) -> tuple[str | None, Decimal | None]:
        for name in names:
            value = self.decimal(name)
            if value is not None:
                return name, value
        return None, None

    def first_text(self, names: list[str]) -> tuple[str | None, str | None]:
        for name in names:
            value = self.value(name)
            if value is not None and str(value).strip():
                return name, str(value).strip()
        return None, None


def _decimal(value: Any, field_name: str, locale: str) -> Decimal | None:
    normalized = normalize_value(value, field_name, locale)
    if normalized is None:
        return None
    try:
        return Decimal(str(normalized))
    except InvalidOperation:
        return None


def _number_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _eval_node(node: ast.AST, env: dict[str, Decimal]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, env)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return node.value
        if isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env or env[node.id] is None:
            raise MissingField(node.id)
        return env[node.id]
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, env)
        right = _eval_node(node.right, env)
        operators = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
        }
        handler = operators.get(type(node.op))
        if handler is None:
            raise ValueError("unsupported operator")
        return handler(left, right)
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError("unsupported unary operator")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        args = [_eval_node(arg, env) for arg in node.args]
        functions = {
            "abs": lambda *a: abs(a[0]),
            "sum": lambda *a: sum(a[0], Decimal(0)),
            "max": lambda *a: max(a),
            "min": lambda *a: min(a),
        }
        if name not in functions:
            raise ValueError(f"unsupported function {name}")
        return functions[name](*args)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, env)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, env)
            handlers = {
                ast.Lt: lambda a, b: a < b,
                ast.LtE: lambda a, b: a <= b,
                ast.Gt: lambda a, b: a > b,
                ast.GtE: lambda a, b: a >= b,
                ast.Eq: lambda a, b: a == b,
                ast.NotEq: lambda a, b: a != b,
            }
            if not handlers[type(op)](left, right):
                return False
            left = right
        return True
    raise ValueError(f"unsupported expression node {type(node).__name__}")


def evaluate_expression(expression: str, env: dict[str, Decimal]) -> bool:
    tree = ast.parse(expression, mode="eval")
    return bool(_eval_node(tree, env))


def _expression_env(
    context: _Context, defaults: dict[str, Any]
) -> dict[str, Decimal]:
    env: dict[str, Decimal] = {}
    for name in context.extraction.fields:
        value = context.decimal(name)
        if value is not None:
            env[name] = value
    for name, value in (defaults or {}).items():
        if name not in env:
            parsed = _decimal(value, name, context.locale)
            if parsed is not None:
                env[name] = parsed
    return env


# --- rule handlers ---------------------------------------------------------


def _check_expression(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    try:
        ok = evaluate_expression(rule["expr"], _expression_env(ctx, rule.get("defaults") or {}))
    except MissingField as exc:
        return [], f"字段缺失: {exc}"
    if ok:
        return [], None
    return [
        Issue(
            rule_id=rule["id"],
            rule_name=rule["name"],
            level=rule["level"],
            field_path=None,
            message=rule["message"],
        )
    ], None


def _check_cn_upper(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    amount_field, amount = ctx.first_decimal(rule["amount_fields"])
    _, words = ctx.first_text([rule["words_field"]])
    if amount is None or words is None:
        return [], "缺少金额或大写金额"
    try:
        expected = cn_upper_amount(amount)
    except ValueError:
        return [], "金额为负数，无大写形式"
    if normalize_cn_upper(words) == normalize_cn_upper(expected):
        return [], None
    return [
        Issue(
            rule_id=rule["id"],
            rule_name=rule["name"],
            level=rule["level"],
            field_path=rule["words_field"],
            message=rule["message"],
            current_value=words,
            suggested_value=expected,
        )
    ], None


def _check_sum_equals(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    items = ctx.extraction.line_items
    if not items:
        return [], "无行项目"
    amounts: list[Decimal] = []
    for item in items:
        amount = _decimal(item.amount.value, "amount", ctx.locale)
        if amount is None:
            return [], "行项目存在缺失金额"
        amounts.append(amount)
    target_field, target = ctx.first_decimal(rule["targets"])
    if target is None:
        return [], "缺少小计与总额"
    total = sum(amounts, Decimal(0))
    tolerance = Decimal(str(rule.get("tolerance", 0.05)))
    if abs(total - target) <= tolerance:
        return [], None

    message = f"{rule['message']}：行项目合计 {_number_text(total)}，{target_field}={_number_text(target)}"
    diff = total - target
    # Do not guess that the total is wrong. If the excess exactly matches one line,
    # point at that row and recommend deleting it; otherwise ask for manual review.
    if diff > tolerance:
        candidates = [
            (index, item, amount)
            for index, (item, amount) in enumerate(zip(items, amounts))
            if abs(amount - diff) <= tolerance
        ]
        if candidates:
            index, item, amount = candidates[-1]
            desc = str(item.description.value or "").strip() or "未命名行"
            message += (
                f"；多出的行项目可能是第 {index + 1} 行「{desc}」金额 {_number_text(amount)}，"
                "建议删除该行，而不是修改总额"
            )
        else:
            message += "；行项目合计大于目标，可能是重复行或总额误读，需人工核对"
    else:
        message += "；行项目合计小于目标，可能漏行或总额误读，需人工核对"

    return [
        Issue(
            rule_id=rule["id"],
            rule_name=rule["name"],
            level=rule["level"],
            field_path=target_field,
            message=message,
            current_value=_number_text(target),
            suggested_value=None,
        )
    ], None


def _parse_rate(value: Any, locale: str) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    percent = text.endswith("%")
    text = text.rstrip("%").strip()
    rate = _decimal(text, "tax_rate", locale)
    if rate is None:
        return None
    if percent:
        return rate / 100
    return rate / 100 if rate > 1 else rate


def _check_tax_rate(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    rate = _parse_rate(ctx.value(rule["rate_field"]), ctx.locale)
    _, base = ctx.first_decimal(rule["base_fields"])
    tax = ctx.decimal(rule["tax_field"])
    if rate is None or base is None or tax is None:
        return [], "缺少税率/不含税金额/税额"
    expected = base * rate
    tolerance = max(Decimal("0.02"), abs(tax) * Decimal("0.01"))
    if abs(expected - tax) <= tolerance:
        return [], None
    return [
        Issue(
            rule_id=rule["id"],
            rule_name=rule["name"],
            level=rule["level"],
            field_path=rule["tax_field"],
            message=f"{rule['message']}：应为 {_number_text(expected)}，实际 {_number_text(tax)}",
            current_value=_number_text(tax),
            suggested_value=_number_text(expected),
        )
    ], None


def _check_tax_id(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    issues = []
    checked = 0
    for name in rule["fields"]:
        value = ctx.value(name)
        if value is None or not str(value).strip():
            continue
        checked += 1
        text = str(value).strip()
        if len(text) not in set(rule["lengths"]) or not re.fullmatch(r"[0-9A-Za-z]+", text):
            issues.append(
                Issue(
                    rule_id=rule["id"],
                    rule_name=rule["name"],
                    level=rule["level"],
                    field_path=name,
                    message=f"{rule['message']}：{name}={text}（应为 15/18/20 位字母数字）",
                    current_value=text,
                )
            )
    return issues, None if checked else "无税号字段"


def _parse_date(text: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _check_date_reasonable(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    checked = 0
    issues = []
    for name in rule["fields"]:
        value = ctx.value(name)
        if value is None:
            continue
        checked += 1
        parsed = _parse_date(str(value).strip())
        if parsed is None:
            return [], f"{name} 无法解析为日期"  # R010 reports the format problem
        if parsed > ctx.today or parsed < ctx.today - timedelta(days=int(rule["max_age_days"])):
            issues.append(
                Issue(
                    rule_id=rule["id"],
                    rule_name=rule["name"],
                    level=rule["level"],
                    field_path=name,
                    message=f"{rule['message']}：{parsed.isoformat()}",
                    current_value=parsed.isoformat(),
                )
            )
    return issues, None if checked else "无日期字段"


def _check_line_price(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    issues = []
    checked = 0
    for index, item in enumerate(ctx.extraction.line_items):
        qty = _decimal(item.quantity.value, "quantity", ctx.locale)
        price = _decimal(item.unit_price.value, "unit_price", ctx.locale)
        amount = _decimal(item.amount.value, "amount", ctx.locale)
        if qty is None or price is None or amount is None:
            continue
        checked += 1
        tolerance = max(
            Decimal(str(rule.get("min_tolerance", 0.02))),
            abs(amount) * Decimal(str(rule.get("tolerance_ratio", 0.01))),
        )
        if abs(qty * price - amount) > tolerance:
            issues.append(
                Issue(
                    rule_id=rule["id"],
                    rule_name=rule["name"],
                    level=rule["level"],
                    field_path=f"line_items[{index}].amount",
                    message=f"{rule['message']}：{qty}×{price}={_number_text(qty * price)}，行金额={_number_text(amount)}",
                    current_value=_number_text(amount),
                    suggested_value=_number_text(qty * price),
                )
            )
    return issues, None if checked else "无同时包含数量/单价/金额的行"


def _check_invoice_number(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    value = ctx.value(rule["field"])
    if value is None or not str(value).strip():
        return [], "缺少发票号码"
    text = str(value).strip()
    if re.fullmatch(rule["pattern"], text):
        return [], None
    return [
        Issue(
            rule_id=rule["id"],
            rule_name=rule["name"],
            level=rule["level"],
            field_path=rule["field"],
            message=f"{rule['message']}：{text}",
            current_value=text,
        )
    ], None


def _check_date_format(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    checked = 0
    issues = []
    for name in rule["fields"]:
        value = ctx.value(name)
        if value is None:
            continue
        checked += 1
        text = str(value).strip()
        if not re.fullmatch(rule["pattern"], text):
            issues.append(
                Issue(
                    rule_id=rule["id"],
                    rule_name=rule["name"],
                    level=rule["level"],
                    field_path=name,
                    message=f"{rule['message']}：{text}",
                    current_value=text,
                )
            )
    return issues, None if checked else "无日期字段"


def _check_nonnegative(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    checked = 0
    issues = []
    for name in rule["amount_fields"]:
        value = ctx.decimal(name)
        if value is None:
            continue
        checked += 1
        if value < 0:
            issues.append(
                Issue(
                    rule_id=rule["id"],
                    rule_name=rule["name"],
                    level=rule["level"],
                    field_path=name,
                    message=f"{rule['message']}：{name}={_number_text(value)}",
                    current_value=_number_text(value),
                )
            )
    for index, item in enumerate(ctx.extraction.line_items):
        for name in rule["line_item_fields"]:
            value = _decimal(getattr(item, name).value, name, ctx.locale)
            if value is None:
                continue
            checked += 1
            if value < 0:
                issues.append(
                    Issue(
                        rule_id=rule["id"],
                        rule_name=rule["name"],
                        level=rule["level"],
                        field_path=f"line_items[{index}].{name}",
                        message=f"{rule['message']}：{name}={_number_text(value)}",
                        current_value=_number_text(value),
                    )
                )
    return issues, None if checked else "无金额/数量字段"


def _check_duplicate(rule: dict, ctx: _Context, index: DuplicateIndex | None) -> tuple[list[Issue], str | None]:
    if index is None or not index.records:
        return [], "无历史单据"
    hits = index.check(ctx.extraction, ctx.dataset)
    issues = [
        Issue(
            rule_id=rule["id"],
            rule_name=rule["name"],
            level="error" if hit.layer == "exact" else "warn",
            field_path="invoice_number" if hit.layer == "exact" else None,
            message=f"[{hit.layer}] {hit.message}（{hit.matched_doc_id}）",
            suggested_value=hit.matched_doc_id,
        )
        for hit in hits
    ]
    return issues, None


def _check_invoice_conflict(rule: dict, ctx: _Context, index: DuplicateIndex | None) -> tuple[list[Issue], str | None]:
    if index is None or not index.records:
        return [], "无历史单据"
    hits = [hit for hit in index.check(ctx.extraction, ctx.dataset) if hit.amount_mismatch]
    issues = [
        Issue(
            rule_id=rule["id"],
            rule_name=rule["name"],
            level=rule["level"],
            field_path="amount_total",
            message=f"{rule['message']}（{hit.matched_doc_id}）",
            suggested_value=hit.matched_doc_id,
        )
        for hit in hits
    ]
    return issues, None


def _check_confidence(rule: dict, ctx: _Context, _index) -> tuple[list[Issue], str | None]:
    issues = []
    checked = 0
    threshold = float(rule.get("threshold", 0.85))
    for path, field_value in ctx.extraction.iter_fields():
        if field_value.value is None:
            continue
        checked += 1
        if field_value.confidence < threshold:
            issues.append(
                Issue(
                    rule_id=rule["id"],
                    rule_name=rule["name"],
                    level=rule["level"],
                    field_path=path,
                    message=f"{rule['message']}：置信度 {field_value.confidence:.3f} < {threshold:.2f}",
                    current_value=field_value.confidence,
                )
            )
    if checked == 0:
        return [
            Issue(
                rule_id=rule["id"],
                rule_name=rule["name"],
                level="warn",
                field_path=None,
                message="未抽取到任何有效字段，无法确认可信度",
            )
        ], None
    return issues, None


HANDLERS: dict[str, Callable] = {
    "expression": _check_expression,
    "cn_upper": _check_cn_upper,
    "sum_equals": _check_sum_equals,
    "tax_rate": _check_tax_rate,
    "tax_id": _check_tax_id,
    "date_reasonable": _check_date_reasonable,
    "line_price": _check_line_price,
    "invoice_number": _check_invoice_number,
    "date_format": _check_date_format,
    "nonnegative": _check_nonnegative,
    "duplicate_document": _check_duplicate,
    "invoice_amount_conflict": _check_invoice_conflict,
    "confidence": _check_confidence,
}


def load_rules(path: Path = DEFAULT_RULES_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate(
    extraction: ExtractionResult,
    dataset: str = "synthetic",
    rules_config: dict | None = None,
    duplicate_index: DuplicateIndex | None = None,
    today: date | None = None,
) -> ValidationReport:
    config = rules_config or load_rules()
    context = _Context(extraction, dataset, today or date.today())
    results: list[RuleResult] = []
    all_issues: list[Issue] = []

    for rule in config["rules"]:
        applies_to = rule.get("applies_to")
        if applies_to and extraction.doc_type not in applies_to:
            results.append(
                RuleResult(
                    rule_id=rule["id"],
                    name=rule["name"],
                    category=rule["category"],
                    level=rule["level"],
                    status="skipped",
                    skip_reason=f"不适用于 {extraction.doc_type}",
                )
            )
            continue
        handler = HANDLERS.get(rule["check"])
        if handler is None:
            raise ValueError(f"unknown check type {rule['check']!r} in {rule['id']}")
        issues, skip_reason = handler(rule, context, duplicate_index)
        if skip_reason:
            status = "skipped"
        elif issues:
            status = "failed"
        else:
            status = "passed"
        results.append(
            RuleResult(
                rule_id=rule["id"],
                name=rule["name"],
                category=rule["category"],
                level=rule["level"],
                status=status,
                issues=issues,
                skip_reason=skip_reason,
            )
        )
        all_issues.extend(issues)

    min_confidence = min(
        (field_value.confidence for _, field_value in extraction.iter_fields() if field_value.value is not None),
        default=0.0,
    )
    if any(issue.level == "error" for issue in all_issues):
        status = "rejected"
    elif any(issue.level == "warn" for issue in all_issues):
        status = "review"
    else:
        status = "accepted"
    return ValidationReport(
        doc_id=extraction.doc_id,
        status=status,
        min_confidence=round(min_confidence, 4),
        issues=all_issues,
        rules=results,
    )


def report_to_json(report: ValidationReport) -> str:
    return json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
