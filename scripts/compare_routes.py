"""Build the E1 route A vs route B comparison report from two evaluation JSONs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _row(name: str, a: float, b: float, fmt: str = "{:.4f}") -> str:
    diff = b - a
    return f"| {name} | {fmt.format(a)} | {fmt.format(b)} | {diff:+.4f} |"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", type=Path, default=ROOT / "reports/eval_cord_route_a.json")
    parser.add_argument("--b", type=Path, default=ROOT / "reports/eval_cord_route_b.json")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/e1_route_comparison")
    parser.add_argument("--label-a", default="路线A（MinerU + qwen-plus）")
    parser.add_argument("--label-b", default="路线B（qwen3-vl-plus 端到端）")
    args = parser.parse_args()

    a, b = load(args.a), load(args.b)
    sa, sb = a["summary"], b["summary"]
    ma, mb = sa["field_metrics"], sb["field_metrics"]

    lines = [
        "# E1 双管线对比（CORD-v2 · 10 份）",
        "",
        f"- 路线A：{args.label_a}",
        f"- 路线B：{args.label_b}",
        "- 两条路线使用同一套字段白名单、同一套标注、同一套打分代码",
        "- 证据覆盖率仅对路线A有意义；路线B不返回坐标，不参与该指标比较",
        "",
        "## 总览",
        "",
        "| 指标 | 路线A | 路线B | B − A |",
        "| --- | --- | --- | --- |",
        _row("字段级 P", ma["precision"], mb["precision"]),
        _row("字段级 R", ma["recall"], mb["recall"]),
        _row("**字段级 F1**", ma["f1"], mb["f1"]),
        _row("幻觉率", ma["hallucination_rate"], mb["hallucination_rate"]),
        _row("漏抽率", ma["miss_rate"], mb["miss_rate"]),
        _row("行项目整单准确率", sa["line_item_doc_accuracy"], sb["line_item_doc_accuracy"]),
        _row("证据覆盖率", sa["evidence_coverage"], sb["evidence_coverage"]),
        f"| 时延 P50 (ms) | {sa['latency_ms']['p50']} | {sb['latency_ms']['p50']} | {sb['latency_ms']['p50'] - sa['latency_ms']['p50']:+d} |",
        f"| 时延 P95 (ms) | {sa['latency_ms']['p95']} | {sb['latency_ms']['p95']} | {sb['latency_ms']['p95'] - sa['latency_ms']['p95']:+d} |",
        f"| 单文档成本 (¥) | {sa['usage']['cost_cny_per_doc']:.4f} | {sb['usage']['cost_cny_per_doc']:.4f} | {sb['usage']['cost_cny_per_doc'] - sa['usage']['cost_cny_per_doc']:+.4f} |",
        "",
        "## 分字段 F1",
        "",
        "| 字段 | 路线A | 路线B |",
        "| --- | --- | --- |",
    ]
    for name in sorted(set(a["by_field"]) | set(b["by_field"])):
        fa = a["by_field"].get(name, {}).get("f1", 0.0)
        fb = b["by_field"].get(name, {}).get("f1", 0.0)
        lines.append(f"| {name} | {fa:.4f} | {fb:.4f} |")

    lines += [
        "",
        "## 结论要点",
        "",
        f"1. 路线B 字段级 F1 领先 {mb['f1'] - ma['f1']:+.4f}，召回提升 {mb['recall'] - ma['recall']:+.4f}，"
        f"主要来自行项目与低清样本。",
        f"2. 路线A 精确率更高（幻觉率 {ma['hallucination_rate']:.4f} vs {mb['hallucination_rate']:.4f}），"
        f"路线B 多召回的代价是多出零价赠品行/臆造金额。",
        f"3. 路线B 时延 P50 仅 {sb['latency_ms']['p50']} ms，是路线A 的 "
        f"{sa['latency_ms']['p50'] / max(sb['latency_ms']['p50'], 1):.1f} 倍加速；成本却是路线A 的 "
        f"{sb['usage']['cost_cny_per_doc'] / max(sa['usage']['cost_cny_per_doc'], 1e-9):.1f} 倍。",
        "4. 路线B 无字段级证据坐标，不能直接用于『可点击定位』；若产品要求证据定位，需保留路线A 或补 OCR 对齐。",
        "5. 10 份样本只够验证管线方向，不足以定论；150~200 份时需重跑本报告并给出置信区间。",
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    md_path = args.out.with_suffix(".md")
    json_path = args.out.with_suffix(".json")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps({"route_a": sa, "route_b": sb}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {md_path} and {json_path}")


if __name__ == "__main__":
    main()
