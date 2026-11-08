# P13 前缀搜索 UNION 化验收

## 问题

上一版前缀搜索仍用：

```sql
d.doc_id LIKE ? OR r.rule_id LIKE ? OR r.field_path LIKE ?
```

优化器选择主键顺序扫描。直接改成 `IN (UNION)` 又被当成 DEPENDENT SUBQUERY，反而逐行执行。

## 实现

前缀搜索改为派生表：

```sql
FROM (
  SELECT id ... doc_id LIKE :prefix
  UNION
  SELECT id ... rule_id LIKE :prefix
  UNION
  SELECT id ... field_path LIKE :prefix
) ids
JOIN review_items r ON r.id = ids.id
JOIN documents d ...
ORDER BY r.id LIMIT/OFFSET
```

UNION 自动去重，派生表只物化一次；计数使用 `COUNT(*) FROM (UNION) matched`。

## 执行计划

- 派生表 `Using temporary; Using filesort`，只物化匹配 ID；
- `rule_id LIKE` 分支命中 `idx_review_status_rule_id`（range）；
- `field_path LIKE` 分支命中 `idx_review_status_field`（range）；
- `doc_id LIKE` 分支仍需从 pending 子集里过滤，当前 45 行，可接受。

## 功能回归

| 查询 | 结果 |
| --- | --- |
| `syn_invoice_0013` | 1 |
| `行项目` | 16 |
| `invoice` | 7 |
| `91000` | 2 |
| `R003` | 13 |

浏览器：

```text
syn_invoice_0013 -> 1 项 / 1 行
行项目 -> 16 项 / 当前页 15 行
console errors 0
```

## 测试

70 个测试通过（新增搜索模式分类 + UNION 结构测试）；容器 healthy，页面 200。

## 边界

- 文档号前缀分支仍无法走覆盖索引，因为匹配列在 `documents`、过滤列在 `review_items`；
- 派生表会物化全部匹配 ID，超大结果集需要限制搜索范围或独立搜索表；
- 文档列表复合索引未加：当前 `/documents` 没有 dataset/status 过滤，加了也不会被使用。
