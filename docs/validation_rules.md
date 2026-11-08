# 稽核规则库 v1

规则定义在 `src/app/validation/rules.yaml`，引擎在 `src/app/validation/engine.py`。
判定口径：**字段缺失一律记 skipped，不记 passed**，避免“没数据 = 没问题”。

## 14 条规则

| ID | 规则 | 类别 | 级别 | 适用 | 关键字段 |
| --- | --- | --- | --- | --- | --- |
| R001 | 价税合计一致 | 算术一致 | error | 中文发票 | subtotal / tax_total / discount_total / amount_total |
| R002 | 中文大写金额与小写一致 | 字段互证 | error | 中文发票 | amount_in_words、total_with_tax |
| R003 | 行项目合计等于小计/总额 | 算术一致 | error | 全部 | line_items.amount、subtotal、amount_total |
| R004 | 税率与税额匹配 | 字段互证 | warn | 中文发票 | tax_rate、subtotal、tax_total |
| R005 | 纳税人识别号格式 | 格式合法 | warn | 中文发票 | buyer_tax_id / seller_tax_id |
| R006 | 开票日期合理性 | 业务合理 | warn | 中文发票 | invoice_date（≤今天，≥今天-365d） |
| R007 | 数量×单价=行金额 | 算术一致 | warn | 全部 | 行项目 quantity / unit_price / amount |
| R008 | 含税合计字段互证 | 字段互证 | error | 中文发票 | total_with_tax / amount_total |
| R009 | 发票号码格式 | 格式合法 | warn | 中文发票 | invoice_number（8~20 位字母数字） |
| R010 | 日期格式 | 格式合法 | warn | 中文发票 | invoice_date（YYYY-MM-DD） |
| R011 | 金额与数量非负 | 业务合理 | error | 全部 | 头部金额、行项目数量/单价/金额 |
| R012 | 重复票据检测 | 跨文档 | error | 全部 | 三层重复检测 |
| R013 | 同票号金额冲突 | 跨文档 | error | 全部 | invoice_number + amount_total |
| R014 | 字段置信度阈值 | 置信度 | warn | 全部 | 所有非空字段，阈值 0.85 |

类别计数：算术 3、字段互证 3、格式 3、业务 2、跨文档 2、置信度 1 = 14。

## 重复票据三层

1. **精确层**：票号归一化后相同 → error。
2. **指纹层**：`seller + amount + date + line_items` 哈希相同 → warn。
3. **去日期指纹**：`seller + amount + line_items` 相同但日期不同 → warn，专门抓“改日期重复报销”。
4. **近似层**：行项目描述字符 3-gram 向量余弦 ≥ 0.92 → warn。

指纹要求至少存在卖方或日期；只有金额相同、没有身份字段的收据不做指纹判断，避免把不同日期的相同订单误判。
近似层要求至少 2 条行项目描述，单条行项目区分度不足。向量层是本地词面向量，可替换为语义 embedding。

## 状态分流

- 任何 error → `rejected`
- 否则任何 warn → `review`
- 全部通过且存在有效字段 → `accepted`
- **空抽取（0 个有效字段）→ `review`**，不允许自动通过
