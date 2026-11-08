# P23 概览 7 天趋势与缓存验收

## 趋势数据

`/api/v1/stats` 新增 `trend`：最近 7 天（含今天）

```json
[
  {"date":"2026-11-02","label":"11-02","created":0,"resolved":0},
  ...
  {"date":"2026-11-06","label":"11-06","created":153,"resolved":1},
  ...
]
```

- `created`：documents.created_at 当日新增
- `resolved`：review_items.resolved_at 当日处理
- 缺失日期补 0

## 缓存

`stats_overview` 增加 60 秒进程内缓存：

```python
_STATS_CACHE = {"at": monotonic, "data": ...}
```

实测连续两次请求：

```text
cache_hit True
generated_at 2026-11-08T13:36:01.909327+00:00
```

## 前端

概览弹窗新增“近 7 天”：

- 每行日期 + 紫色新增条 + 数量 + 绿色已处理条 + 数量
- 两条按 7 天最大值归一化
- 弹窗高度可滚动

浏览器：

```text
trend_rows 7
11-02 0 0 / 11-03 0 0 ...
console errors 0
```

截图：`reports/ui_p23_stats_trend.png`。

## 测试

71 个测试通过；容器 healthy，页面 200。

## 边界

- 缓存 TTL 60 秒，复核后概览可能短暂滞后；
- 趋势按数据库时区 CURDATE()，非浏览器时区；
- 新增/已处理两条独立归一化，视觉上不能直接比较绝对量级（数值仍显示）。
