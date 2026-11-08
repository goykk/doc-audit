# P10 服务端队列筛选分页与批量采纳验收

## 服务端筛选/分页

`GET /api/v1/review/queue` 新增：

- `rule_id`：按规则过滤
- `q`：文档号 / 规则 / 字段 / 原因模糊搜索
- `limit` / `offset`：真实分页
- 返回 `total`（筛选后总数）与 `rules`（全部待复核规则）

前端改为每次翻页/筛选都请求服务端，不再一次拉 200 条后本地切片。

实测：

```text
总数 44，第 1 页 15 条，第 2 页 15 条
R003 筛选后 13 条，1 页
搜索 syn_invoice_0013 -> 1 条
```

## 批量采纳建议

`POST /api/v1/review/batch` 的 `action` 支持 `accept`。

- 队列增加“批量采纳建议”按钮
- 只处理选中的项
- R003/R005 无条件禁止 accept，防止绕过人工修正：
  - 历史 R003 复核项中残留的旧建议值已统一清空
  - 批量采纳 R003 返回 `processed=0, failed=1`

实测：

```json
POST /api/v1/review/batch {"item_ids":[9],"action":"accept"}
{"processed":0,"failed":1,"errors":[{"item_id":9,"error":"该问题必须人工修正字段，不能直接采纳"}]}
```

## 浏览器验收

```text
all 44 项待复核, rows 15, page 1/3
page2 2/3, rows 15
R003 筛选后 13 项, rows 13, page 1/1
搜索 1 项
选中 1 项, 批量采纳按钮 enabled
console errors 0
```

截图：`reports/ui_p10_server_queue.png`。

## 测试

69 个测试通过（新增队列筛选 SQL 测试、批量采纳按钮入口测试）。

## 边界

- `total` 与 `rules` 每次请求额外两条 SQL，量大时可缓存；
- 搜索索引与 ngram 全文已在 P11 补齐，见 `reports/p11_search_indexes.md`；
- 批量采纳对无建议值项会失败并回报，不会静默跳过。
