# P16 Facets 联动计数验收

## 语义

`GET /api/v1/documents/facets?dataset=&status=`

- 数据集计数：受当前 `status` 约束，忽略 `dataset`
- 状态计数：受当前 `dataset` 约束，忽略 `status`
- 选中两个条件时，各自显示“切换另一维后”的可选数量，而不是交集数量

## 实测

| 请求 | datasets | statuses |
| --- | --- | --- |
| 无参数 | cord 100 / synthetic 50 / upload 3 | accepted 129 / rejected 19 / review 5 |
| dataset=synthetic | 全局 153 | accepted 38 / rejected 8 / review 4 |
| status=rejected | cord 11 / synthetic 8 | 全局 19 |
| dataset=synthetic&status=rejected | cord 11 / synthetic 8 | 38 / 8 / 4 |

浏览器：

```text
初始 statuses: 129 / 19 / 5
选 synthetic: 38 / 8 / 4
再选 rejected: datasets 全部 19 / cord 11 / synthetic 8
文档下拉: 8 份，首份 syn_invoice_0022
header overflow: false
console errors: 0
```

截图：`reports/ui_p16_facets_linked.png`。

## 边界处理

- 切换 dataset 后若当前 status 在新 facets 中不存在，前端自动清空 status；
- 切换 status 后若当前 dataset 不存在，自动清空 dataset；
- 清空后重新按剩余条件加载文档。

## 测试

71 个测试通过；容器 healthy，页面 200。

## 边界

- facets 只做两维联动，不支持三条件；
- 计数查询为两条 GROUP BY，数据量大时需缓存；
- 选项文本带数量，窄屏可能压缩，但 1440 下无溢出。
