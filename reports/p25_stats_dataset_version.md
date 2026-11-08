# P25 数据集概览与版本化缓存验收

## 数据集统计

`GET /api/v1/stats?dataset=synthetic`：

- 文档状态/总数、待复核、今日更新、今日处理全部按 dataset 过滤
- 数据集明细只返回当前集合
- 趋势的 created/resolved 也按 dataset 过滤
- 响应带 `dataset_filter`

实测：

```text
全部:      153 文档 / 44 pending
synthetic: 50 文档 / 20 pending / accepted 38 / rejected 8 / review 4
cord:      100 文档 / 24 pending
```

## 版本化缓存

缓存从单一 TTL 改为：

```python
_STATS_CACHE[dataset] = {"version": MAX(documents.updated_at), "at": ..., "data": ...}
```

每次请求先查 `MAX(updated_at)` 作为版本：

- 版本变化 → 重建缓存，即使 TTL 未到
- 版本未变且 TTL 内 → 命中
- `invalidate_stats_cache()` 清空所有 dataset 缓存

实测模拟其他 worker 直接改文档时间（不调用失效）：

```text
version_regenerated True
t1 2026-11-08T13:42:10.186969+00:00
t2 2026-11-08T13:42:10.310200+00:00
```

浏览器：

```text
synthetic -> 50 文档 / 20 待复核
subtitle: synthetic · 更新于 21:42:13
console errors 0
```

截图：`reports/ui_p25_stats_dataset.png`。

## 测试

72 个测试通过；容器 healthy，页面 200。

## 边界

- 版本取 `MAX(updated_at)`，DATETIME 秒精度；同一秒内多次变更可能不触发版本变化，TTL 仍兜底；
- 数据集统计只跟随 dataset，不跟随 header 的 status 过滤；
- 版本查询本身是一次聚合，但走 `idx_documents_updated`，成本低。
