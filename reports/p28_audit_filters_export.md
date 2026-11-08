# P28 审计筛选、分页与 CSV 导出验收

## 后端

`GET /api/v1/documents/{doc_id}/audit` 新增：

- `offset`
- `pipeline`
- `event`
- `date_from` / `date_to`（YYYY-MM-DD）

返回 `total / limit / offset / events`。

新增：

`GET /api/v1/documents/{doc_id}/audit.csv`

- 同样筛选参数
- CSV 列：at / pipeline / event / field_path / old_value / new_value / action / note / by / validation_status
- 最多 5000 条

## 前端

审计弹窗新增：

- 管线筛选：全部 / 路线A / 路线B / merged
- 事件筛选：人工选择来源 / 复核写入 / 复核动作 / 重新校验
- 开始/结束日期
- 10 条/页，上一页/下一页
- 导出 CSV（带当前筛选条件）

## 实测

```text
全部:            12 条 / 10 行 / 1/2 页
路线A:            9 条 / 9 行 / 1/1
路线A+复核动作:   6 条
2026-11-08:       8 条
导出: cord_test_0001_audit.csv / 721 bytes
console errors 0
```

截图：`reports/ui_p28_audit_filters.png`。

## 测试

73 个测试通过（新增审计筛选单元测试）；容器 healthy，页面 200。

## 边界

- CSV 导出上限 5000 条；
- 日期筛选按事件 `at` 的前 10 位字典序比较；
- 仅支持倒序，不提供排序切换；
- 筛选在前端触发重新请求，不在本地过滤。
