# P20 updated_at 与最近更新排序验收

## 数据库

新增 `007_documents_updated_at.sql`：

```sql
ALTER TABLE documents
  ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ON UPDATE CURRENT_TIMESTAMP AFTER created_at;

UPDATE documents SET updated_at = created_at;
```

新增 `008_documents_updated_index.sql`：

```sql
ALTER TABLE documents ADD KEY idx_documents_updated (updated_at, id);
```

## 排序

文档列表：

```sql
ORDER BY d.updated_at DESC, d.id DESC
```

搜索结果：

```sql
ORDER BY
  CASE WHEN d.doc_id = :qexact THEN 0
       WHEN d.doc_id LIKE :qprefix THEN 1
       ELSE 2 END,
  d.updated_at DESC,
  d.id DESC
```

即：文档号精确命中 > 文档号前缀 > 文件名全文 > 最近更新。

## 实测

将 `cord_test_0001.updated_at` 更新为当前时间后：

```text
API 前三: cord_test_0001(2026-11-08 13:20) / cord_test_0099 / cord_test_0098
选择器第一行: cord_test_0001 · 2026-11-08 13:20 · cord · accepted
```

无搜索列表执行计划：

```text
key=idx_documents_updated
Backward index scan; Using index
```

选择器行内已显示更新时间。

截图：`reports/ui_p20_recent_order.png`。

## 测试

71 个测试通过；容器 healthy，页面 200。

## 边界

- `updated_at` 只在 `documents` 行更新时变化；非当前管线复核只改 validation，不会刷新文档时间；
- 文件名全文不参与相关性打分，只作为第 3 档；
- 搜索结果派生表较小，`updated_at` 排序仍是 filesort，大结果集需额外优化。
