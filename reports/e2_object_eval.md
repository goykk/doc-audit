# 字段级评测报告

- 文档数：10
- 参与评分的字段实例：81
- 字段级 P / R / F1：0.7692 / 0.8955 / 0.8276
- 幻觉率：0.1795
- 漏抽率：0.0448
- 行项目整单准确率：0.3000
- 证据覆盖率（有值字段中带 bbox 的比例）：0.0000
- 时延 P50 / P95：8074 / 11935 ms
- Token：输入 14232 / 输出 3933
- 成本：¥0.0643，单文档 ¥0.0064

## 分层

| 维度 | 分组 | F1 | 幻觉率 | 漏抽率 |
| --- | --- | --- | --- | --- |
| quality_tier | lowres | 0.7059 | 0.2778 | 0.1875 |
| quality_tier | scan | 0.8649 | 0.1500 | 0.0000 |
| layout_tier | single_column | 0.8276 | 0.1795 | 0.0448 |
| dataset | cord | 0.8276 | 0.1795 | 0.0448 |

## 字段

| 字段 | P | R | F1 | TP | FP | FN |
| --- | --- | --- | --- | --- | --- | --- |
| amount | 0.7895 | 0.9375 | 0.8571 | 15 | 4 | 1 |
| amount_total | 0.8000 | 0.8889 | 0.8421 | 8 | 2 | 1 |
| description | 0.6842 | 0.8125 | 0.7429 | 13 | 6 | 3 |
| discount_total | 0.2500 | 0.5000 | 0.3333 | 1 | 3 | 1 |
| quantity | 0.7692 | 1.0000 | 0.8696 | 10 | 3 | 0 |
| subtotal | 1.0000 | 1.0000 | 1.0000 | 8 | 0 | 0 |
| tax_total | 1.0000 | 1.0000 | 1.0000 | 4 | 0 | 0 |
| unit_price | 1.0000 | 0.5000 | 0.6667 | 1 | 0 | 1 |

## 前 20 条错误

| 文档 | 字段 | 类型 | 真值 | 预测 |
| --- | --- | --- | --- | --- |
| cord_test_0002 | line_items[pred_only:1].description | hallucination | None | COCONUT JELLY ( L ) |
| cord_test_0002 | line_items[pred_only:1].amount | hallucination | None | 4.000 |
| cord_test_0004 | discount_total | wrong | 19,400 | -19,400 |
| cord_test_0004 | line_items[0].description | wrong | ICE BLACKCOFFE | ICE BLACKCOFFEE |
| cord_test_0005 | line_items[0].quantity | hallucination | None | 1.00 |
| cord_test_0006 | line_items[1].description | wrong | CHOCO CUS ARD PASTRY | CHOCO CUS'ARD PASTRY |
| cord_test_0007 | discount_total | hallucination | None | -100,000 |
| cord_test_0007 | amount_total | wrong | 111,000 | 11,000 |
| cord_test_0007 | line_items[0].description | miss | Kupon 15 | None |
| cord_test_0007 | line_items[0].amount | miss | 100,000 | None |
| cord_test_0007 | line_items[pred_only:0].description | hallucination | None | ADD CHICKEN BOX |
| cord_test_0007 | line_items[pred_only:0].amount | hallucination | None | 909 |
| cord_test_0008 | line_items[pred_only:1].description | hallucination | None | COOKIE DOH SAUCES |
| cord_test_0008 | line_items[pred_only:1].quantity | hallucination | None | 1 |
| cord_test_0008 | line_items[pred_only:1].amount | hallucination | None | 0 |
| cord_test_0008 | line_items[pred_only:2].description | hallucination | None | NATA DE COCO |
| cord_test_0008 | line_items[pred_only:2].quantity | hallucination | None | 1 |
| cord_test_0008 | line_items[pred_only:2].amount | hallucination | None | 0 |
| cord_test_0009 | discount_total | hallucination | None | 0 |
| cord_test_0009 | amount_total | hallucination | None | 14000 |
