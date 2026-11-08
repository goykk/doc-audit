# P2 A/B 并排对比验收

## 接口

`GET /api/v1/documents/{doc_id}/compare` 同时返回两条管线：

- `layout_llm`：完整 extraction / validation / review_items
- `vlm_e2e`：同上
- 任一管线缺失返回 404

## 视图

入口：文档存在两条管线时，元信息行出现“A/B 并排对比”按钮；
也可直接访问 `?doc=<doc_id>&compare=1`。

布局：

- 左：原图 + 路线A 证据框（红=冲突，黄=存疑）
- 右：字段对比表，路线A / 路线B 两列逐字段对齐
- 不一致行黄底 + 橙点；缺失值显示 `—`
- 顶部显示两管线状态、模型、时延、成本、差异数、冲突/存疑数
- 点击任一行，路线A 对应 bbox 高亮并滚动到可见位置
- 底部注明“A 有 N 个证据框；B 无坐标”

## 实际验收

`cord_test_0001`：

| 指标 | 结果 |
| --- | --- |
| 对比行数 | 20 |
| 差异行 | 3（Y.BASO vs Y.BASO PROM、额外第 4 行等） |
| A 证据框 | 9 |
| A 状态 | rejected |
| B 状态 | accepted |
| 浏览器 console error | 0 |

Playwright 断言通过，截图：

- `reports/ui_ab_compare.png`
- `reports/ui_ab_compare_selected.png`（点击差异行后联动）

## 价值

这张视图直接支撑项目最核心的结论：

1. 路线B 字段更准、状态 accepted；
2. 路线A 虽然 rejected，但能定位原文证据；
3. 差异行让人工复核知道该看哪一条，而不是在 20 个字段里盲找。

## 边界

- 行项目按索引对齐，未按语义匹配；行数不同时显示缺失行，适合展示，不适合直接当评测器；
- 只有前 10 份 CORD 同时有 A/B，其他文档不显示对比入口；
- 路线A 的旧预测成本为 0（生成时未配置价格），对比表显示 ¥0.0000 是历史数据，不是免费。
