# W2-2 落库与复核队列验收记录

- 数据库：MySQL 8.0.36（Docker，宿主机 3308）
- 数据集：CORD 10 份，路线A 预测
- 执行命令：`scripts/persist_run.py --pred-dir data/predictions/route_a --dataset cord`

## 落库结果

| 表 | 行数 |
| --- | --- |
| documents | 10 |
| extractions | 10 |
| field_values | 100 |
| validations | 10 |
| review_items | 8 |

文档状态：accepted 3 / review 5 / rejected 2。

## 接口验收

| 接口 | 结果 |
| --- | --- |
| `GET /api/health` | 200，status=ok |
| `GET /api/v1/review/queue` | 200，初始 8 条 pending |
| `GET /api/v1/documents` | 200，10 条 |
| `GET /api/v1/documents/cord_test_0006` | 200，含 extraction / validation / review_items |
| `POST /api/v1/review/{id}` | 200，修改 subtotal=46000 |
| 重复提交同一复核项 | 409，review item already corrected |
| `POST` modify 不带 value | 400 |
| 不存在的文档/复核项 | 404 |

## 复核闭环验证（cord_test_0006）

- 处理前：document=rejected，1 条 R003 pending，小计 46,000 vs 行项目合计 46,060。
- 动作：`modify`，value=46000，note=人工核对后修正。
- 动作后：
  - `review_items.status=corrected`
  - `field_values.subtotal` 更新为 `46000`，source=reviewer
  - `extractions.result_json.fields.subtotal.value=46000`
  - `validations.audit_log` 追加 `reviewed` 事件
  - 所有复核项清零 → document 与 validation 状态重算为 accepted
  - 全局 pending 8 → 7

## 说明

- 落库是幂等重灌：同一 doc 重新写入会删除旧 extraction 并级联清理字段、校验与复核项。
- 当前数据库只保留一条抽取路线；`documents` 唯一键是 doc_id。双管线同时入库需要增加 pipeline 维度的当前版本策略。
- 该记录来自真实执行，不是构造样例。
