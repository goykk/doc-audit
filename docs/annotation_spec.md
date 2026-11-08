# 标注规范 v1（冻结版）

本规范在标注第 1 张样本前定稿。标注中途不得修改；确需修改必须升版本号并重标受影响样本。
评测脚本只认本规范与 `dataset_fields.yaml`，不允许在代码里临时解释字段含义。

## 1. 五条硬性规则

1. **缺失即 null**：字段在单据上确实不存在，标 `value: null`。不得填空字符串、`0`、`N/A`。
2. **缺失 ≠ 抽错**：真值为 null 而模型给了值，记为幻觉；真值非 null 而模型给 null，记为漏抽；两者分开统计。
3. **quote 必须逐字**：`quote` 是原文中连续出现的子串，不改大小写、不补空格、不做全半角转换。
4. **bbox 以渲染图为准**：坐标统一使用 `PDF_RENDER_DPI`（默认 200）渲染图的像素坐标，原点左上，`page` 从 1 开始。
5. **金额标原始展示值**：保留单据上的数值，不自行四舍五入；进入校验层后才转 Decimal 计算。

## 2. 字段路径

- 头部字段：`invoice_number`、`amount_total` 等，直接使用字段名。
- 行项目：`line_items[i].description|quantity|unit_price|amount`，`i` 从 0 开始，顺序与单据视觉顺序一致。
- 行项目数量以单据实际行数为准；模型多出的行记幻觉，缺少的行记漏抽。

## 3. 数据集差异（关键）

CORD/SROIE/FUNSD 不是中文增值税发票，**没有** `buyer_tax_id`、`amount_in_words` 等字段。
CORD-v2 的 `gt_parse` 也不包含商户名与日期，因此 `merchant_name`、`receipt_date` 不在 CORD 白名单内，
不能凭空补标。每个数据集只按 `dataset_fields.yaml` 的白名单字段计算 F1，白名单之外一律不参与评分，
避免把"该数据集根本没有这个字段"误算成模型漏抽。

| doc_type | 来源 | 参与评分内容 |
| --- | --- | --- |
| `cn_invoice` | 合成中文发票/费用单据 | 全部中文字段 + 行项目 |
| `receipt` | CORD / SROIE | 白名单内的英文收据字段 + 行项目（SROIE 无行项目则不评行项目） |
| `layout` | FUNSD | 仅关键字段定位与证据命中，不做中文专属规则校验 |

## 4. 校验规则的适用范围

- R002（大写与小写金额一致）、R004（购买方税号位数）等中文专属规则只在 `doc_type=cn_invoice` 启用。
- 金额勾稽类规则（R003/R005/R010/R011）按数据集实际存在的字段启用，字段缺失时记 `skip` 而不是 `pass`，
  防止拦截率分母被撑大。

## 5. 样本标签

每张样本必须带三个分层标签，供分层报告切片：

- `quality_tier`: `clear`（原生电子/300dpi）/ `scan`（150dpi 扫描）/ `lowres`（拍照、倾斜、低对比）
- `layout_tier`: `single_column` / `multi_column` / `merged_cells`
- `source_dataset`: `cord` / `sroie` / `funsd` / `synthetic`

合成数据必须额外注入字段扰动与近似重复样本，否则校验层拦截率无从统计。

> D3 临时口径：CORD 的 `quality_tier` 先按图像短边是否 ≥700px 分为 `scan`/`lowres`，这是分辨率代理，
> 不代表已经完成模糊/倾斜人工评级；扩大到 150~200 张前必须人工复核一遍。
