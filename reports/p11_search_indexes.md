# P11 队列索引与搜索优化验收

## 索引

新增迁移 `infra/mysql/init/003_review_indexes.sql`：

- `(status, rule_id, id)`：按规则筛选 + 稳定分页
- `(status, id)`：无规则筛选的待复核分页
- `field_path(64)`：字段前缀搜索
- `FULLTEXT(reason) WITH PARSER ngram`：中文原因搜索

当前库已应用；新库 init 会按 001→002→003 自动执行。

## 搜索策略

原来 `%q%` 全表扫描，现改为：

- `doc_id / rule_id / field_path` 前缀匹配（可走索引）
- `reason` 使用 ngram 全文 + BOOLEAN 精确短语
- 结果仍然只取 `status=pending`，按 id 分页

## 实测

搜索收敛：

| 查询 | 修改前 | 修改后 |
| --- | --- | --- |
| `syn_invoice_0013` | 28 | **1** |
| `行项目` | 16 | 16 |
| `91000` | 27 | **2** |
| `R003` | 13 | 13 |

浏览器：

```text
全部 44 项 / 第 1 页 15 条 / 3 页
syn_invoice_0013 -> 1 条
行项目 -> 16 条（当前页 15）
R003 -> 13 条
console errors 0
```

执行计划：

- `status + rule_id` 查询命中 `idx_review_status_rule_id`，不再扫主键。
- 搜索仍包含 OR 条件，会先在 `status=pending` 子集上过滤；数据量再大时应拆分为独立搜索通道。

## 测试

69 个测试通过；容器 healthy，页面 200。

## 边界

- 前缀搜索的通道拆分已在 P12 完成，见 `reports/p12_search_channels.md`；
- 前缀搜索意味着 `invoice_0013` 不能匹配 `syn_invoice_0013` 的中间段；
- 单字搜索无法命中 ngram（ngram token 默认 2）；
- 全文索引需要 MySQL ngram parser，其他数据库需替换方案；
- `total`/`rules` 每次仍额外两条查询。
