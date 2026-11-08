# P7 普通复核动作重校验验收

## 问题

P6 只校验输入格式，不校验业务结果。`amount_total=0` 格式合法，会被写入并把复核项标记完成，文档可能被错误推向 accepted。

## 修改

- 抽出公共函数 `_revalidate_extraction`：重建重复索引、执行 14 条规则、更新 validations、追加 audit。
- merged 决策（P4）改为复用该函数。
- `modify / accept` 且实际写入字段后：
  - 重跑规则；
  - 保留已处理项的历史；
  - 对仍未通过的规则重建 pending 复核项（同 rule_id + field_path 不重复）；
  - 按“有 rejected 项 / 规则 rejected / 仍有 pending / 规则 accepted”重算文档状态；
  - 仅当前管线回写 `documents.status`。
- `reject` 不重跑规则，保持人工驳回语义。

## 实测（cord_test_0001）

1. 采纳 A 多出的第 4 行 → merged rejected / R003 / 1 条 pending；
2. 对 R003 执行 `modify amount_total=0`（格式合法但业务错误）：
   - HTTP 200
   - 文档仍 **rejected**
   - R003 **重新生成 pending**
   - audit 记录 `review_action` → `revalidated` → `reviewed`，`revalidated=true`
3. 清理 merged，恢复路线B current / accepted。

## 测试

66 个测试通过；容器 healthy，页面 200。

## 边界

- 修改后若问题仍存在，会生成新的 pending 项，原处理项保留为 corrected/accepted 历史；
- 非当前管线（如路线A）复核只更新自身 validation，不改文档状态；
- 规则建议值仍可能不完整，人工修改需要业务判断。
