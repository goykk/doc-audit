# P15 状态筛选与动态数据集验收

## 后端

新增 `GET /api/v1/documents/facets`：

```json
{
  "datasets": [
    {"value": "cord", "count": 100},
    {"value": "synthetic", "count": 50},
    {"value": "upload", "count": 3}
  ],
  "statuses": [
    {"value": "accepted", "count": 129},
    {"value": "rejected", "count": 19},
    {"value": "review", "count": 5}
  ]
}
```

`/documents` 的 dataset/status 过滤复用 P14。

## 前端

- 数据集选项改为接口动态生成，带数量
- 新增状态下拉：全部 / accepted / review / rejected
- 组合筛选：dataset + status 同时生效
- 初始化先拉 facets，再拉文档列表
- 接口失败时保留 HTML 里的静态兜底选项

## 实测

```text
datasets: 全部 (153) / cord (100) / synthetic (50) / upload (3)
statuses: accepted (129) / rejected (19) / review (5)
synthetic + rejected -> 8 份，首份 syn_invoice_0022
status chip: rejected
header overflow: false
console errors: 0
```

截图：`reports/ui_p15_status_filter.png`。

## 测试

71 个测试通过；容器 healthy，页面 200。

## 边界

- facets 计数是全局总数，不随另一个筛选条件联动；
- 状态选项来自数据库 distinct 值，出现新状态会自动出现；
- 数据集筛选切换后加载该集合的降序第一份，不保留原文档（跨集合时原文档不存在）。
