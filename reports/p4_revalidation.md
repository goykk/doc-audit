# P4 决策后自动重校验验收

## 行为

`POST /api/v1/documents/{doc_id}/select` 更新 merged 后：

1. 重建重复票据索引（排除当前文档）
2. 对 merged 结果重新执行 14 条规则
3. 更新 `validations` 的 `rule_hits / status / passed / error_count / warn_count`
4. 删除并重建 merged 的 `review_items`
5. 同步 `documents.status`
6. audit_log 追加 `revalidated`（before_status / after_status / rules）

A/B 原件不变；merged 始终为 current。

## 实测数据（cord_test_0001）

采纳 A 多出的第 4 行（`line_items[3].amount`）：

| 步骤 | 状态 | 行项目数 | error | 复核项 | 命中规则 |
| --- | --- | --- | --- | --- | --- |
| 初始（B 合并值） | accepted | 3 | 0 | 0 | — |
| 采纳 A 额外行 | **rejected** | **4** | **1** | **1** | **R003** |
| 再采纳 B 删除该行 | **accepted** | **3** | 0 | 0 | — |

audit_log：

```
pipeline_selection
revalidated: accepted -> rejected, rules=[R003]
pipeline_selection
revalidated: rejected -> accepted, rules=[]
```

## 浏览器验收

Playwright：

```
compare head: 当前 · 合并 rejected
main status: rejected
document select: cord_test_0001 · cord · rejected
pending review: 1
console errors: 0
```

同时修掉一个 UI 不一致：决策后主区已 rejected，但顶部文档下拉仍显示 accepted。
现在决策后会单独刷新文档选项，不再重载整个视图。

截图：

- `reports/ui_p4_revalidated_compare.png`
- `reports/ui_p4_revalidated_review.png`

截图后已把 merged 恢复为 B 的正确值（accepted / 3 行）。

## 测试

59 个测试通过，容器 healthy，页面 200。

## 边界

- 重新校验会重建 merged 的复核项，之前对 merged 的复核动作不会保留；
- 决策粒度仍是字段或整行，不支持整票采纳；
- R003 的建议值方向已在 P5 修正，见 `reports/p5_rule_suggestion.md`。
