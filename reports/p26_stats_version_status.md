# P26 持久化统计版本与状态概览验收

## 持久化版本

新增 `010_stats_version.sql`：

```sql
CREATE TABLE stats_version (
  id TINYINT PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1,
  updated_at DATETIME ...
);
INSERT ... (1,1);
```

- 统计缓存键：`dataset|status`
- 缓存值：`{version, at, data}`
- 每个写路径事务内 `UPDATE stats_version SET version=version+1`
  - `_persist_one`
  - `apply_review_action`
  - `apply_pipeline_selection`
- 读取时先取版本，版本变化立即重建；TTL 仍兜底

实测：

```text
version 3 -> 4
pending 44 -> 43
```

## 状态过滤

`/api/v1/stats` 新增 `status`：

- 文档总数/状态
- 复核 pending/状态
- 今日更新/已处理
- 趋势 created/resolved
- 时延/成本

全部按文档状态过滤。

实测：

```text
全部:                  153 文档 / 44 pending
status=accepted:       129 文档 / 6 pending
status=rejected:       19 文档 / 33 pending
synthetic+rejected:    8 文档 / 16 pending
```

浏览器概览跟随顶部 dataset + status：

```text
8 文档 / 16 待复核
subtitle: synthetic · rejected · 更新于 21:46:48
console errors 0
```

截图：`reports/ui_p26_stats_status.png`。

## 测试

72 个测试通过；容器 healthy，页面 200。

## 边界

- 版本只在应用写路径自增，直接改库不会触发；
- 版本表固定单行 id=1；
- status 过滤统计的是“文档状态”，不是复核项状态；
- 缓存仍为进程内，但版本表让多 worker 能各自发现变更。
