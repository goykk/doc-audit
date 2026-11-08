# 字段级评测报告

- 文档数：10
- 参与评分的字段实例：72
- 字段级 P / R / F1：0.6863 / 0.5224 / 0.5932
- 幻觉率：0.0980
- 漏抽率：0.3134
- 行项目整单准确率：0.1000
- 证据覆盖率（有值字段中带 bbox 的比例）：0.9412
- 时延 P50 / P95：41682 / 145948 ms
- Token：输入 10674 / 输出 3045
- 成本：¥0.0146，单文档 ¥0.0015

## 分层

| 维度 | 分组 | F1 | 幻觉率 | 漏抽率 |
| --- | --- | --- | --- | --- |
| quality_tier | lowres | 0.5217 | 0.0000 | 0.5625 |
| quality_tier | scan | 0.6105 | 0.1136 | 0.2353 |
| layout_tier | single_column | 0.5932 | 0.0980 | 0.3134 |
| dataset | cord | 0.5932 | 0.0980 | 0.3134 |

## 字段

| 字段 | P | R | F1 | TP | FP | FN |
| --- | --- | --- | --- | --- | --- | --- |
| amount | 0.6923 | 0.5625 | 0.6207 | 9 | 4 | 7 |
| amount_total | 1.0000 | 0.7778 | 0.8750 | 7 | 0 | 2 |
| description | 0.4286 | 0.3750 | 0.4000 | 6 | 8 | 10 |
| discount_total | 0.5000 | 0.5000 | 0.5000 | 1 | 1 | 1 |
| quantity | 1.0000 | 0.5000 | 0.6667 | 5 | 0 | 5 |
| subtotal | 0.6667 | 0.5000 | 0.5714 | 4 | 2 | 4 |
| tax_total | 0.6667 | 0.5000 | 0.5714 | 2 | 1 | 2 |
| unit_price | 1.0000 | 0.5000 | 0.6667 | 1 | 0 | 1 |

## 前 20 条错误

| 文档 | 字段 | 类型 | 真值 | 预测 |
| --- | --- | --- | --- | --- |
| cord_test_0000 | line_items[0].description | wrong | -TICKET CP | 901016 -TICKET CP |
| cord_test_0001 | line_items[2].description | wrong | Y.BASO PROM | Y.BASO |
| cord_test_0001 | line_items[pred_only:3].description | hallucination | None | PROM |
| cord_test_0001 | line_items[pred_only:3].amount | hallucination | None | 91000 |
| cord_test_0002 | subtotal | wrong | 28,000 | 24.000 |
| cord_test_0002 | tax_total | hallucination | None | 4.000 |
| cord_test_0002 | line_items[0].description | miss | JASMINE MT ( L ) | None |
| cord_test_0002 | line_items[0].quantity | miss | 1 | None |
| cord_test_0002 | line_items[0].amount | miss | 24,000 | None |
| cord_test_0004 | discount_total | wrong | 19,400 | -19,400 |
| cord_test_0004 | line_items[0].quantity | miss | 2 | None |
| cord_test_0004 | line_items[1].quantity | miss | 1 | None |
| cord_test_0004 | line_items[1].amount | wrong | 61,000 | 51,000 |
| cord_test_0004 | line_items[2].description | wrong | CHIKEN KATSU FF | CHIKEN KATSU |
| cord_test_0004 | line_items[2].quantity | miss | 1 | None |
| cord_test_0004 | line_items[2].amount | wrong | 51,000 | FF |
| cord_test_0004 | line_items[pred_only:3].description | hallucination | None | 61.,000 |
| cord_test_0005 | subtotal | miss | 28.182 | None |
| cord_test_0005 | tax_total | miss | 2.818 | None |
| cord_test_0005 | amount_total | miss | 31.000 | None |
