# P12 搜索通道拆分与字段索引验收

## 改动

搜索不再混用全文与 OR，按输入类型分流：

| 输入 | 通道 |
| --- | --- |
| `R003` / `r004` | 规则精确匹配 |
| `syn_invoice_0013` / `invoice` | 文档号 / 规则 / 字段前缀匹配 |
| `行项目` / `91000` | reason ngram 精确短语 |

新增 `004_review_field_index.sql`：

- `(status, field_path(64), id)` 复合索引

## 实测

| 查询 | 结果 |
| --- | --- |
| `syn_invoice_0013` | 1 |
| `行项目` | 16 |
| `invoice` | 7 |
| `91000` | 2 |
| `R003` | 13 |
| `r004` | 1 |

浏览器：

```text
syn_invoice_0013 -> 筛选后 1 项，1 行
console errors 0
```

截图：`reports/ui_p12_search.png`。

## 执行计划

`status + rule_id` 命中 `idx_review_status_rule_id`。

前缀搜索仍使用 `doc_id OR rule_id OR field_path`，优化器选择主键顺序扫描 + LIMIT；
当前 44 条 pending 下代价可接受。若要让前缀搜索也走索引，需要改成 UNION 子查询或独立搜索表。

## 测试

69 个测试通过；容器 healthy，页面 200。

## 边界

- `invoice_0013` 仍不能匹配 `syn_invoice_0013` 中间段；
- 单字 ngram 不命中；
- 前缀 OR 已在 P13 改为 UNION 派生表，见 `reports/p13_union_search.md`。
