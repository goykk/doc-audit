# 字段级评测报告

- 文档数：100
- 参与评分的字段实例：1114
- 字段级 P / R / F1：0.8222 / 0.9102 / 0.8640
- 幻觉率：0.1121
- 漏抽率：0.0172
- 行项目整单准确率：0.4800
- 证据覆盖率（有值字段中带 bbox 的比例）：0.0000
- 时延 P50 / P95：9054 / 24827 ms
- Token：输入 149419 / 输出 50487
- 成本：¥0.7852，单文档 ¥0.0079

## 分层

| 维度 | 分组 | F1 | 幻觉率 | 漏抽率 |
| --- | --- | --- | --- | --- |
| quality_tier | lowres | 0.8369 | 0.1033 | 0.0280 |
| quality_tier | scan | 0.8730 | 0.1150 | 0.0135 |
| layout_tier | single_column | 0.8640 | 0.1121 | 0.0172 |
| dataset | cord | 0.8640 | 0.1121 | 0.0172 |

## 字段

| 字段 | P | R | F1 | TP | FP | FN |
| --- | --- | --- | --- | --- | --- | --- |
| amount | 0.8782 | 0.9675 | 0.9207 | 238 | 33 | 8 |
| amount_total | 0.8900 | 0.9368 | 0.9128 | 89 | 11 | 6 |
| description | 0.7399 | 0.8048 | 0.7710 | 202 | 71 | 49 |
| discount_total | 0.3000 | 1.0000 | 0.4615 | 6 | 14 | 0 |
| quantity | 0.8861 | 0.9545 | 0.9190 | 210 | 27 | 10 |
| subtotal | 0.6966 | 0.9538 | 0.8052 | 62 | 27 | 3 |
| tax_total | 0.7955 | 0.8537 | 0.8235 | 35 | 9 | 6 |
| unit_price | 0.9524 | 0.8955 | 0.9231 | 60 | 3 | 7 |

## 前 20 条错误

| 文档 | 字段 | 类型 | 真值 | 预测 |
| --- | --- | --- | --- | --- |
| cord_test_0002 | line_items[pred_only:1].description | hallucination | None | COCONUT JELLY ( L ) |
| cord_test_0002 | line_items[pred_only:1].amount | hallucination | None | 4.000 |
| cord_test_0004 | line_items[0].description | wrong | ICE BLACKCOFFE | ICE BLACKCOFFEE |
| cord_test_0005 | line_items[0].quantity | hallucination | None | 1.00 |
| cord_test_0006 | subtotal | hallucination | None | 46,000 |
| cord_test_0006 | line_items[1].description | wrong | CHOCO CUS ARD PASTRY | CHOCO CUS'ARD PASTRY |
| cord_test_0007 | discount_total | hallucination | None | -100,000 |
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
| cord_test_0009 | line_items[0].unit_price | miss | 36000 | None |
