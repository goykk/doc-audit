# P14 文档列表过滤与索引验收

## 后端

`GET /api/v1/documents` 新增：

- `dataset`：按 `source_dataset` 过滤
- `status`：按文档状态过滤
- 返回 `total / limit / offset / dataset / status`

新增 `005_documents_filters.sql`：

- `(source_dataset, status, id)`
- `(source_dataset, id)`

## 前端

文档选择器前增加数据集筛选：

- 全部数据集
- cord
- synthetic
- upload

切换后重新拉取文档列表并加载该数据集首份文档。

## 实测

```text
全部 153 份
synthetic 50 份 -> syn_invoice_0050
cord 100 份 -> cord_test_0000
console errors 0
```

API：

```text
dataset=cord,status=rejected -> 11
dataset=synthetic,status=review -> 4
```

执行计划：

```text
type=ref, key=idx_documents_dataset_status
Backward index scan; Using index
```

截图：`reports/ui_p14_dataset_filter.png`。

## 测试

71 个测试通过（新增文档过滤条件测试、前端筛选入口测试）；容器 healthy，页面 200。

## 边界

- status 过滤只开了 API，前端暂未加状态下拉；
- 数据集列表写死 cord/synthetic/upload，新增数据集需要同步前端；
- 153 份数据量下索引收益有限，主要防止后续全量扫描。
