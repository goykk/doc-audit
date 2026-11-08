# P21 复核/重抽取刷新 updated_at 验收

## 问题

`updated_at` 原来只在 `documents` 行更新时触发。非当前管线（路线 A/B 中未选中的那条）复核只写 `validations/review_items`，文档时间不会刷新，“最近处理”排序滞后。

## 修改

1. `apply_review_action` 结束时显式：

```sql
UPDATE documents SET updated_at=NOW() WHERE id=:document_id
```

覆盖 accept / modify / reject，覆盖 A/B/merged 任意管线。

2. `_persist_one` 完成抽取/校验落库后同样 touch 文档。

## 实测

将 `cord_test_0001.updated_at` 置为 `2020-01-01`，对路线 A 的 R003 复核项（非当前管线）执行 reject：

```text
review HTTP 200 / item.status=rejected
document.status=accepted（未被非当前管线影响）
updated_at=2026-11-08T13:22:33（已刷新）
```

测试项随后恢复 pending。

## 测试

71 个测试通过；容器 healthy，页面 200。

## 边界

- 非当前管线复核刷新时间，但不会改文档状态；
- 重新抽取路径已加 touch，未单独做端到端替换验证，避免破坏现有 A/B 数据；
- 批量操作复用 `apply_review_action`，因此同样刷新时间。
