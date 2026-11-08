# P27 文档审计时间线验收

## 后端

新增 `GET /api/v1/documents/{doc_id}/audit?limit=200`：

- 拉取该文档所有管线的 `validations.audit_log`
- 展平 JSON 事件
- 附加 `pipeline`、`validation_status`
- 按 `at` 倒序
- 返回 `{doc_id, total, events}`

`apply_review_action` 新事件补充：

```json
{"old_value": ..., "new_value": ...}
```

## 前端

复核 tab 右侧新增“审计”按钮，弹窗时间线展示：

- 事件类型（人工选择来源 / 复核写入 / 复核动作 / 重新校验）
- 管线 badge（路线A/B/merged）
- 时间
- 字段、旧值 → 新值、动作、规则、备注
- 操作人、校验状态

## 实测

```text
cord_test_0001 · 12 条
第一行: 复核动作 / 路线A / 2026-11-08 13:46:44
amount_total · 动作 reject · 备注 P26 version
操作人 human · 校验状态 rejected
console errors 0
```

截图：`reports/ui_p27_audit.png`。

## 测试

72 个测试通过；容器 healthy，页面 200。

## 边界

- 只读取 `audit_log` 中已有事件，没有独立审计表；
- 旧事件没有 `old_value/new_value`，只有新写入的复核事件才有；
- 时间线最多 200 条，未做分页/按时间过滤；
- 非当前管线事件也会展示，但会标出管线。
