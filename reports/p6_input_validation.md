# P6 人工修改输入校验验收

## 目标

防止复核时把字段改成新的非法值，避免“修完更错”。

## 实现

新增 `src/app/validation/input_validation.py`，在 `apply_review_action` 写库前统一校验并归一化：

| 字段 | 规则 |
| --- | --- |
| 金额（subtotal/tax_total/amount_total/unit_price/amount 等） | 必须可解析、不能为负、按 locale 归一 |
| 数量 quantity | 必须可解析、必须大于 0 |
| 税率 tax_rate | 支持 `6%` / `0.06`，必须在 0%~100% |
| 日期 invoice_date/receipt_date | 支持 `YYYY-MM-DD`、`YYYY/MM/DD` 等，统一为 ISO |
| 税号 buyer/seller_tax_id | 15/18/20 位字母数字 |
| 文本字段 | 不能为空，最长 200 |

## 实测（R003 复核项）

```text
modify "-1"  -> 400 amount_total 不能为负数
modify "abc" -> 400 amount_total 不是合法金额
```

## 测试

新增 7 个输入校验测试；全量 **66 个测试通过**。

## 重要缺口

当前 `modify` 成功后不会自动重跑 14 条规则：

- 合法但业务错误的值仍可能被写入；
- 复核项会被标记 corrected，文档状态可能被错误地推向 accepted。

本次验证中 `amount_total=0` 属于合法非负金额，成功写入后暴露了这个问题；已清理测试 merged 并恢复 B 为 current。
该缺口已在 P7 修复，见 `reports/p7_review_revalidation.md`。

## 边界

- 金额允许 0（当前业务未禁止零元票据）；
- 文本长度限制 200，未按字段类型细分；
- 未做前端即时校验，错误以后端返回为准。
