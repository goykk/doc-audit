# P22 稽核概览与审计索引验收

## 索引

新增 `009_review_resolved_index.sql`：

- `(resolved_at)`
- `(status, resolved_at)`

支撑“今日已处理”和后续按时间审计。

## 统计接口

`GET /api/v1/stats`：

```json
{
  "documents": {
    "total": 153,
    "by_status": {"accepted": 129, "rejected": 19, "review": 5},
    "updated_today": 1
  },
  "review": {
    "pending": 44,
    "by_status": {"corrected": 1, "pending": 44},
    "resolved_today": 0
  },
  "datasets": [
    {"value": "cord", "count": 100},
    {"value": "synthetic", "count": 50},
    {"value": "upload", "count": 3}
  ],
  "pipelines": {"avg_latency_ms": 12510.6, "total_cost_cny": 1.4541}
}
```

## 前端

顶部新增“概览”按钮，弹窗展示：

- 文档总数 / 待复核 / 今日已处理 / 今日更新
- 文档状态、复核状态、数据集三列明细
- 当前管线平均时延与总成本
- Esc / 关闭按钮退出

## 浏览器验证

```text
header overflow: false
文档总数 153 / 待复核 44 / 今日已处理 0 / 今日更新 1
平均时延 12.51s · 总成本 ¥1.45
console errors 0
```

截图：`reports/ui_p22_stats.png`。

## 测试

71 个测试通过；容器 healthy，页面 200。

## 边界

- 统计为实时聚合，未缓存；
- “今日”按数据库 CURDATE()，非浏览器时区；
- 时延/成本取当前管线 extractions，不含历史重跑。
