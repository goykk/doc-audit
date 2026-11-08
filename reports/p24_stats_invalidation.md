# P24 统计缓存主动失效验收

## 问题

P23 的 60 秒缓存会导致复核后概览仍显示旧 pending，用户容易误判。

## 实现

新增 `invalidate_stats_cache()`，清空 `_STATS_CACHE`。

接入点：

1. `_persist_one` 完成抽取/校验落库后
2. `apply_review_action` 完成 accept/modify/reject 后
3. `apply_pipeline_selection` 重建 merged 后

批量驳回/采纳复用 `apply_review_action`，因此同样失效。

## 实测

```text
复核前 stats.pending = 44
reject item 9 -> HTTP 200
复核后 stats.pending = 43
generated_at 已变化（缓存确实重建）
```

恢复 item 9 为 pending 并重启 app 后：

```text
stats.pending = 44
```

## 测试

72 个测试通过（新增缓存失效单元测试）；容器 healthy，页面 200。

## 边界

- 当前是单进程内存缓存；多 worker 部署时其他进程仍可能持有旧值，需 Redis pub/sub 或统一缓存层；
- 失效在数据库事务提交前调用，若事务随后回滚，缓存已清空但无数据错误，只是下次多查一次；
- TTL 60 秒仍作为兜底。
