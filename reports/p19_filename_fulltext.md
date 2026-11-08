# P19 文件名 ngram 全文与双通道搜索验收

## 索引

新增 `006_documents_filename_ft.sql`：

```sql
ALTER TABLE documents
  ADD FULLTEXT KEY ft_documents_filename (filename) WITH PARSER ngram;
```

## 查询

文档搜索拆成两个通道，再 UNION 派生表：

```sql
SELECT id FROM documents WHERE doc_id LIKE :qprefix
UNION
SELECT id FROM documents WHERE MATCH(filename) AGAINST (:ft_q IN BOOLEAN MODE)
```

- `doc_id`：前缀，走 `doc_id` 索引
- `filename`：ngram 精确短语，走全文索引
- dataset/status 过滤同时应用到两个分支

执行计划：

```text
DERIVED doc_id range key=doc_id
UNION  fulltext key=ft_documents_filename
DERIVED rows=4
```

## 实测

| 查询 | 结果 |
| --- | --- |
| `syn_invoice_001` | 10 |
| `invoice_001` | 10（文件名中段） |
| `0019.png` | 2 |
| `cord_test_00` | 100 |
| `nonexistent` | 0 |

浏览器：

```text
invoice_001 -> 10 份 / 10 行
ArrowDown + Enter -> syn_invoice_0018，弹窗关闭
console errors 0
```

截图沿用：`reports/ui_p18_doc_picker_keyboard.png`。

## 测试

71 个测试通过；容器 healthy，页面 200。

## 边界

- ngram 默认 token 2，单字搜索不命中；
- 全文为精确短语，不支持分词 OR；
- 文件名全文不做相关性排序，结果仍按 id 倒序；
- 文档号仍只支持前缀，不支持中段。
