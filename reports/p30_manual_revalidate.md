# P30 手动重跑校验验收

## 后端

新增 `POST /api/v1/documents/{doc_id}/revalidate?pipeline=`：

- 未指定 pipeline：重跑当前 extraction
- 指定 pipeline：重跑对应路线（可为非当前）
- 调用现有 `_revalidate_extraction`
- 写入审计事件：
  - `manual_revalidate`（人工触发）
  - `revalidated`（系统校验结果）
- 当前管线：同步更新文档状态
- 非当前管线：只刷新 `updated_at`，不改主状态
- 递增 `stats_version` 并失效统计缓存

实测：

```text
layout_llm -> 200 accepted errors 0 warnings 0 is_current false
vlm_e2e    -> 200 accepted errors 0 warnings 0 is_current true
merged     -> 404 extraction not found（该文档无 merged extraction）
无 pipeline -> 200，自动选当前 vlm_e2e
```

## 前端

文档工具栏 `刷新` 旁新增“重跑校验”：

- 禁用按钮 → 请求 → toast 结果
- 重新加载文档与队列 badge
- 审计弹窗新增“手动重跑校验”事件类型与筛选项

浏览器：

```text
header overflow: false
toast: 校验完成：accepted · 错误 0 / 警告 0
status: accepted
审计筛选 manual_revalidate: 4 条
console errors 0
```

截图：`reports/ui_p30_revalidate.png`。

## 测试

74 个测试通过；容器 healthy，页面 200。

## 边界

- 重跑只更新 validation，不重建 `review_items`；旧复核项可能仍留在队列；
- `merged` extraction 不存在时返回 404；
- 非当前管线重跑不会改变文档状态；
- 重跑没有并发锁，同一文档同时点击可能重复写审计。
