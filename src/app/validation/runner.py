"""Run the validation engine over a prediction directory."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.evaluation.runner import load_manifest
from app.extraction_result import ExtractionResult
from app.validation.duplicates import DuplicateIndex
from app.validation.engine import ValidationReport, load_rules, validate


def run_validation(
    pred_dir: Path,
    dataset: str,
    project_root: Path,
    manifest_path: Path,
    rules_config: dict | None = None,
) -> dict:
    config = rules_config or load_rules()
    rows = [
        row
        for row in load_manifest(manifest_path)
        if row.get("source_dataset") == dataset
    ]
    if not rows:
        raise ValueError(f"no manifest rows for dataset {dataset}")

    predictions: list[tuple[dict, ExtractionResult]] = []
    for row in rows:
        path = pred_dir / f"{row['doc_id']}.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        predictions.append((row, ExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))))

    index = DuplicateIndex(threshold=float(config["engine"].get("duplicate_vector_threshold", 0.92)))
    for _, result in predictions:
        index.add(result, dataset)

    reports: list[ValidationReport] = [
        validate(result, dataset=dataset, rules_config=config, duplicate_index=index)
        for _, result in predictions
    ]

    status_counts = Counter(report.status for report in reports)
    rule_stats: dict[str, dict] = {}
    for report in reports:
        for rule in report.rules:
            stat = rule_stats.setdefault(
                rule.rule_id,
                {
                    "name": rule.name,
                    "category": rule.category,
                    "level": rule.level,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "issue_count": 0,
                },
            )
            stat[rule.status] += 1
            stat["issue_count"] += len(rule.issues)

    issues = [
        {**issue.as_dict(), "doc_id": report.doc_id}
        for report in reports
        for issue in report.issues
    ]
    return {
        "dataset": dataset,
        "docs": len(reports),
        "status_counts": {
            "accepted": status_counts.get("accepted", 0),
            "review": status_counts.get("review", 0),
            "rejected": status_counts.get("rejected", 0),
        },
        "issue_count": len(issues),
        "rules": rule_stats,
        "documents": [
            {
                "doc_id": report.doc_id,
                "status": report.status,
                "min_confidence": report.min_confidence,
                **report.as_dict()["counts"],
                "issue_rule_ids": sorted({issue.rule_id for issue in report.issues}),
            }
            for report in reports
        ],
        "issues": issues,
    }


def render_markdown(report: dict) -> str:
    counts = report["status_counts"]
    lines = [
        f"# 稽核报告（{report['dataset']} · {report['docs']} 份）",
        "",
        f"- 自动通过 accepted：{counts['accepted']}",
        f"- 待复核 review：{counts['review']}",
        f"- 驳回 rejected：{counts['rejected']}",
        f"- 问题条数：{report['issue_count']}",
        "",
        "## 规则执行情况",
        "",
        "| 规则 | 名称 | 类别 | 级别 | 通过 | 失败 | 跳过 | 问题数 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rule_id, stat in report["rules"].items():
        lines.append(
            f"| {rule_id} | {stat['name']} | {stat['category']} | {stat['level']} | "
            f"{stat['passed']} | {stat['failed']} | {stat['skipped']} | {stat['issue_count']} |"
        )
    lines += [
        "",
        "## 文档状态",
        "",
        "| 文档 | 状态 | 最低置信度 | error | warn | 命中规则 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for doc in report["documents"]:
        lines.append(
            f"| {doc['doc_id']} | {doc['status']} | {doc['min_confidence']:.3f} | "
            f"{doc['errors']} | {doc['warnings']} | {', '.join(doc['issue_rule_ids']) or '-'} |"
        )
    if report["issues"]:
        lines += [
            "",
            "## 问题清单（前 30 条）",
            "",
            "| 文档 | 规则 | 级别 | 字段 | 信息 | 建议值 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for issue in report["issues"][:30]:
            lines.append(
                f"| {issue.get('doc_id', '')} | {issue['rule_id']} | {issue['level']} | "
                f"{issue['field_path'] or '-'} | {issue['message']} | {issue['suggested_value'] or '-'} |"
            )
    return "\n".join(lines) + "\n"
