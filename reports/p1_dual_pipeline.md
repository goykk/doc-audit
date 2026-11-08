# P1 双管线版本验收

## 迁移

`infra/mysql/init/002_pipeline_versions.sql`：

- `extractions.is_current TINYINT(1)`，标记当前管线；
- 唯一键 `(document_id, pipeline)`，同一管线重复运行只替换自己；
- 索引 `(document_id, is_current)`。

已有库已手工应用迁移；新库由 MySQL init 目录自动按 001 → 002 执行。

## 数据结果

| 指标 | 数量 |
| --- | --- |
| documents | 153 |
| extractions | 163 |
| layout_llm | 10 |
| vlm_e2e | 153 |

CORD 100 份全部有路线B；其中前 10 份同时保留路线A（CPU 解析成本限制，只扩了这 10 份）。

## API 验收

`GET /api/v1/documents/cord_test_0001` 返回：

| 管线 | 状态 | error | warn | 证据框 |
| --- | --- | --- | --- | --- |
| layout_llm | rejected | 1 | 0 | 9 个（1 个红色冲突框） |
| vlm_e2e | accepted | 0 | 0 | 0 |

- 不带参数默认 `is_current=1`（vlm_e2e）。
- `?pipeline=layout_llm` 返回 A 的字段、校验、复核项和 bbox。
- 列表接口新增 `pipelines` 与 `current_status`。

## 浏览器验收

Playwright 打开 `?doc=cord_test_0001`：

```
B accepted boxes 0 | A rejected boxes 9 errorboxes 1
back accepted boxes 0
console_errors []
```

切换按钮、状态灯、字段清单、证据框、复核项同步变化。截图：`reports/ui_pipeline_switch.png`。

## 设计取舍

- `documents.status` 跟随 `is_current` 管线；详情接口额外返回 `selected_status`，前端按当前选择显示。
- 复核动作只回写当前管线的 document 状态，非当前管线的复核项仍可处理，但不会覆盖当前状态。
- 重复票据索引只使用 `is_current=1` 的抽取，避免同一文档 A/B 互相判重。
- 旧数据迁移时全部标记为 current；首次重跑某管线后，该管线成为 current，另一条保留为历史版本。

## 未做

- 同一文档只能有一个 current，不能按用户维度保存偏好；
- 路线A仍无法在容器内运行。

A/B 并排对比已在 P2 完成，见 `reports/p2_ab_compare.md`。
