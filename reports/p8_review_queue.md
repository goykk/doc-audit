# P8 复核队列与批量驳回验收

## R005 人工修正保护

- R005 文案补充可执行标准：`（应为 15/18/20 位字母数字）`
- R005 进入人工修正集合，复核卡片显示禁用的“需人工修正”
- 后端 `apply_review_action` 禁止 R003/R005 无建议值直接 accept

## 批量驳回

新增 `POST /api/v1/review/batch`：

```json
{"item_ids":[9,9],"action":"reject","note":"批量驳回"}
```

- 自动去重 item_ids
- 单项失败不影响其他项
- 返回 `processed / failed / errors`
- 路由放在 `/review/{item_id}` 之前，避免被动态路由吞掉

实测：

```json
{"processed":1,"failed":0,"errors":[]}
```

重复 id 只处理一次；测试项随后已恢复 pending。

## 复核队列 UI

- 顶部“复核队列”按钮 + 待复核数量 badge
- 弹窗展示 pending 项：文档、管线、规则、字段、建议值、原因
- 支持按规则筛选、关键字搜索、全选当前筛选结果
- “打开”跳转到对应文档的复核 tab
- “批量驳回”调用 batch 接口
- 修复了全选框被 CSS 宽度规则拉成 220px 的问题

Playwright：

```
badge 45
R003 rows 14
selected 已选 1 项
batch disabled false
console errors 0
```

最终状态：44 项待复核，R003 筛出 13 项。截图：`reports/ui_p8_queue.png`。

## 测试

68 个测试通过（新增 R005 文案测试、批量接口空列表 422、前端队列标记）。

## 边界

- 批量操作目前只开放“驳回”，不提供批量 accept/modify；
- 队列最多拉取 200 项，分页未做；
- 批量驳回逐项提交，不是单事务；部分成功会如实返回 failed。
