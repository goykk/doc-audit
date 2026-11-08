"""E3: validation-layer gain on the synthetic Chinese invoice set.

Two modes:
- oracle: ground truth is fed as the prediction, isolating rule correctness;
- pipeline: real predictions from a route directory, measuring the deployed system.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.evaluation.runner import load_manifest  # noqa: E402
from app.extraction_result import ExtractionResult  # noqa: E402
from app.validation.duplicates import DuplicateIndex  # noqa: E402
from app.validation.engine import load_rules, validate  # noqa: E402


def load_labels(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["doc_id"]: row for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-dir", type=Path, default=None, help="omit for oracle mode")
    parser.add_argument("--dataset", default="synthetic")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rules = load_rules()
    labels = load_labels(ROOT / "data/ground_truth/synthetic_labels.jsonl")
    rows = [r for r in load_manifest(ROOT / "data/ground_truth/manifest.jsonl") if r["source_dataset"] == args.dataset]
    mode = "oracle" if args.pred_dir is None else "pipeline"

    predictions: list[tuple[dict, ExtractionResult]] = []
    for row in rows:
        path = (args.pred_dir / f"{row['doc_id']}.json") if args.pred_dir else (ROOT / row["annotation"])
        if not path.is_file():
            raise FileNotFoundError(path)
        predictions.append((row, ExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))))

    index = DuplicateIndex(threshold=float(rules["engine"]["duplicate_vector_threshold"]))
    for _, result in predictions:
        index.add(result, args.dataset)

    reports = {
        result.doc_id: validate(
            result, dataset=args.dataset, rules_config=rules, duplicate_index=index
        )
        for _, result in predictions
    }

    # A duplicate pair flags both sides; the legitimate original is not a false alarm,
    # so exclude docs whose true invoice number participates in a duplicate group.
    invoice_counts = Counter()
    truth_invoice: dict[str, str | None] = {}
    for row, _ in predictions:
        truth = ExtractionResult.model_validate_json((ROOT / row["annotation"]).read_text(encoding="utf-8"))
        number = truth.fields.get("invoice_number")
        value = str(number.value) if number and number.value is not None else None
        truth_invoice[row["doc_id"]] = value
        if value:
            invoice_counts[value] += 1

    bad_docs = [doc_id for doc_id, label in labels.items() if label["expected_rules"]]
    clean_docs = [doc_id for doc_id, label in labels.items() if not label["expected_rules"]]
    clean_evaluable = [
        doc_id for doc_id in clean_docs if not (truth_invoice.get(doc_id) and invoice_counts[truth_invoice[doc_id]] > 1)
    ]

    bad_detected = 0
    expected_rule_hits = 0
    details = []
    for doc_id in bad_docs:
        report = reports[doc_id]
        label = labels[doc_id]
        actual_rules = {issue.rule_id for issue in report.issues}
        expected = set(label["expected_rules"])
        hit = expected <= actual_rules
        detected = report.status != "accepted"
        bad_detected += int(detected)
        expected_rule_hits += int(hit)
        details.append(
            {
                "doc_id": doc_id,
                "fault": label["fault"],
                "expected_rules": sorted(expected),
                "actual_rules": sorted(actual_rules),
                "expected_status": label["expect_status"],
                "status": report.status,
                "detected": detected,
                "expected_rule_hit": hit,
            }
        )

    false_alarms = [doc_id for doc_id in clean_evaluable if reports[doc_id].status != "accepted"]
    status_counts = Counter(report.status for report in reports.values())

    result = {
        "mode": mode,
        "dataset": args.dataset,
        "docs": len(rows),
        "bad_docs": len(bad_docs),
        "clean_docs_evaluable": len(clean_evaluable),
        "baseline_intercepted": 0,
        "validation_intercepted": bad_detected,
        "interception_rate": round(bad_detected / len(bad_docs), 4) if bad_docs else 0.0,
        "expected_rule_hit_rate": round(expected_rule_hits / len(bad_docs), 4) if bad_docs else 0.0,
        "false_alarms": len(false_alarms),
        "false_alarm_rate": round(len(false_alarms) / len(clean_evaluable), 4) if clean_evaluable else 0.0,
        "status_counts": dict(status_counts),
        "auto_accept_rate": round(status_counts.get("accepted", 0) / len(rows), 4),
        "review_workload_rate": round(1 - status_counts.get("accepted", 0) / len(rows), 4),
        "details": details,
        "false_alarm_doc_ids": false_alarms,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    md_path = args.out.with_suffix(".md")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# E3 校验层增益（{mode} 模式 · {args.dataset} · {len(rows)} 份）",
        "",
        f"- 有故障文档：{len(bad_docs)}",
        f"- 可评估干净文档：{len(clean_evaluable)}（排除重复票组中的原件）",
        f"- 无校验基线拦截：0 / {len(bad_docs)}（0%）",
        f"- 有校验拦截：**{bad_detected} / {len(bad_docs)}（{result['interception_rate']:.2%}）**",
        f"- 期望规则命中：**{expected_rule_hits} / {len(bad_docs)}（{result['expected_rule_hit_rate']:.2%}）**",
        f"- 干净文档误报：{len(false_alarms)} / {len(clean_evaluable)}（{result['false_alarm_rate']:.2%}）",
        f"- 自动通过率：{result['auto_accept_rate']:.2%}，人工复核工作量：{result['review_workload_rate']:.2%}",
        f"- 状态分布：{dict(status_counts)}",
        "",
        "## 明细",
        "",
        "| 文档 | 故障 | 期望规则 | 实际命中 | 状态 | 拦截 | 规则命中 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in details:
        lines.append(
            f"| {item['doc_id']} | {item['fault']} | {','.join(item['expected_rules'])} | "
            f"{','.join(item['actual_rules']) or '-'} | {item['status']} | "
            f"{'✓' if item['detected'] else '✗'} | {'✓' if item['expected_rule_hit'] else '✗'} |"
        )
    if false_alarms:
        lines += ["", f"误报文档：{', '.join(false_alarms)}"]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"mode={mode} intercepted={bad_detected}/{len(bad_docs)} "
        f"expected_hit={expected_rule_hits}/{len(bad_docs)} false_alarm={len(false_alarms)}/{len(clean_evaluable)}"
    )
    print(f"wrote {json_path} and {md_path}")


if __name__ == "__main__":
    main()
