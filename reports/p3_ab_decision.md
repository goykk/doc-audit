# P3 A/B 决策台验收

## 功能

在 A/B 并排对比视图的差异行上直接做决策：

- 点击路线A/B 单元格中的“采纳”
- 被采纳的值写入独立的 **merged 合并版本**
- A/B 两条原始抽取永不修改，决策可随时反悔
- 对比表第四列“当前/合并”实时显示决策结果
- 每次决策写入 `validations.audit_log`

## 接口

`POST /api/v1/documents/{doc_id}/select`

```json
{
  "field_path": "line_items[2].description",
  "source_pipeline": "layout_llm",
  "note": "A/B对比采纳"
}
```

行为：

- 头部字段：采纳单个字段值
- 行项目：采纳整行（description / quantity / unit_price / amount）
- source 行不存在：删除 merged 中对应的多余行
- 首次决策时自动创建 merged 版本，并复制当前校验状态
- merged 成为 `is_current`，A/B 保留为历史版本

## 数据不变性验证

`cord_test_0001 / line_items[2].description`：

| 步骤 | 路线A | 路线B | merged |
| --- | --- | --- | --- |
| 初始 | Y.BASO | Y.BASO PROM | Y.BASO PROM |
| 采纳A | Y.BASO | Y.BASO PROM | **Y.BASO** |
| 再采纳B | Y.BASO | Y.BASO PROM | **Y.BASO PROM** |

A/B 在两次决策后均未变化。

## 浏览器验证

Playwright DOM 断言：

```
path: line_items[2].description
before: A=Y.BASO · B=Y.BASO PROM · 当前=Y.BASO PROM
after:  A=Y.BASO · B=Y.BASO PROM · 当前=Y.BASO
diff_rows=3 · A boxes=9 · console errors=0
```

截图：`reports/ui_ab_decision.png`（截图后已将演示值恢复为路线B）。

## audit_log

merged 版本记录：

1. `merged_created`（from_pipeline=vlm_e2e）
2. `pipeline_selection`（source=layout_llm，changed=true）
3. `pipeline_selection`（source=vlm_e2e，changed=true）

包含 old_value / new_value / note / 时间 / 操作者。

## 已知边界

- merged 决策后的自动重校验已在 P4 完成并验收，见 `reports/p4_revalidation.md`；
- 决策粒度是“字段或整行”，不支持一次采纳整张票据；
- 只有同时存在 A/B 的文档才能进入决策台。
