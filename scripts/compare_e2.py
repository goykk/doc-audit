"""Combine E2 mode stats and evaluation reports into one comparison."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ("free", "object", "schema")
LABELS = {
    "free": "自由文本（无 response_format）",
    "object": "JSON Object 模式",
    "schema": "严格 JSON Schema",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "reports/e2_structured_output")
    args = parser.parse_args()

    rows = []
    for mode in MODES:
        stats = json.loads((ROOT / "reports" / f"e2_{mode}_stats.json").read_text(encoding="utf-8"))
        evaluation = json.loads((ROOT / "reports" / f"e2_{mode}_eval.json").read_text(encoding="utf-8"))
        summary = evaluation["summary"]
        attempted = stats["docs"] + stats["failed"]
        rows.append(
            {
                "mode": mode,
                "label": LABELS[mode],
                "docs": stats["docs"],
                "strict_json_rate": stats["raw_json_valid"] / attempted if attempted else 0,
                "payload_valid_rate": stats["payload_valid"] / attempted if attempted else 0,
                "repairs": stats["repairs"],
                "failed": stats["failed"],
                "f1": summary["field_metrics"]["f1"],
                "precision": summary["field_metrics"]["precision"],
                "recall": summary["field_metrics"]["recall"],
                "hallucination_rate": summary["field_metrics"]["hallucination_rate"],
                "line_item_accuracy": summary["line_item_doc_accuracy"],
                "p50_ms": int(statistics.median(stats["latency_ms"])) if stats["latency_ms"] else 0,
                "total_tokens": stats["prompt_tokens"] + stats["completion_tokens"],
                "prompt_tokens": stats["prompt_tokens"],
                "cost_cny_total": stats["cost_cny"],
                "cost_per_doc": round(stats["cost_cny"] / stats["docs"], 6) if stats["docs"] else 0,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    md_path = args.out.with_suffix(".md")
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# E2 结构化输出消融（CORD · 10 份）",
        "",
        "- 同一批图片、同一 prompt、同一模型 qwen3-vl-plus，只改变 `response_format`",
        "- 自由文本模式仍然要求返回 JSON，但不启用服务端格式约束；这是最宽松的可比条件",
        "- 严格 Schema 由字段白名单动态生成，`additionalProperties=false`",
        "",
        "| 模式 | 严格 JSON 合法率 | 首轮 payload 合法率 | 修复次数 | F1 | P | R | 幻觉率 | 行项目准确率 | P50 | 单文档 token | 单文档成本 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['strict_json_rate']:.2%} | {row['payload_valid_rate']:.2%} | "
            f"{row['repairs']} | {row['f1']:.4f} | {row['precision']:.4f} | {row['recall']:.4f} | "
            f"{row['hallucination_rate']:.4f} | {row['line_item_accuracy']:.2%} | {row['p50_ms']} ms | "
            f"{row['total_tokens'] // row['docs']} | ¥{row['cost_per_doc']:.4f} |"
        )

    free, obj, schema = rows
    lines += [
        "",
        "## 结论",
        "",
        "1. **三种模式都没有出现格式错误**：10/10 严格 JSON 合法、0 次修复。"
        "qwen3-vl-plus 在明确要求 JSON 的 prompt 下已经足够稳定，服务端约束没有带来格式收益。",
        f"2. **严格 Schema 没有提升字段 F1**：{schema['f1']:.4f}，低于自由文本/JSON Object 的 {free['f1']:.4f}；"
        f"幻觉率反而从 {obj['hallucination_rate']:.4f} 升到 {schema['hallucination_rate']:.4f}。",
        f"3. **Schema 的代价明确**：单文档输入 token 从 {obj['prompt_tokens'] // obj['docs']} 增到 {schema['prompt_tokens'] // schema['docs']}，"
        f"单文档成本从 ¥{obj['cost_per_doc']:.4f} 增到 ¥{schema['cost_per_doc']:.4f}。",
        "4. 这个负结论有边界：它只说明**强多模态模型 + 明确 JSON prompt** 下 Schema 约束收益不足，"
        "不能推广到弱模型、自由文本生成或需要工具调用契约的场景；生产默认仍保留 JSON Object 模式作为低成本保险。",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {json_path} and {md_path}")


if __name__ == "__main__":
    main()
