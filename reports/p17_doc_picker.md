# P17 文档选择器搜索与分页验收

## 后端

`GET /api/v1/documents` 增加 `q`：

- `doc_id LIKE 'q%' OR filename LIKE 'q%'`
- 继续支持 dataset/status/limit/offset/total

实测：

```text
q=syn_invoice_001 -> total 10
q=cord_test_00   -> total 100
```

## 前端

原生 select 隐藏，改为“当前文档”按钮 + 选择弹窗：

- 20 条/页，服务端分页
- 搜索框 250ms 防抖，按文档号/文件名前缀搜索
- 行内显示文档号、文件名、数据集、状态
- 当前文档高亮
- 点击行加载文档并关闭弹窗
- 支持上一页/下一页、Esc 关闭
- 选择弹窗沿用 dataset/status 过滤条件

## 浏览器验证

```text
当前文档按钮: cord_test_0000 · cord · accepted
全部 153 份 / 20 行 / 第 1/8 页
下一页 -> 2/8，20 行
搜索 syn_invoice_001 -> 10 份 / 10 行 / 1/1
点击 syn_invoice_0019 -> 弹窗关闭，按钮更新为 syn_invoice_0019
console errors 0
```

截图：`reports/ui_p17_doc_picker.png`。

## 测试

71 个测试通过；容器 healthy，页面 200。

## 边界

- 搜索是前缀匹配，不能搜中间段；
- 文件名和文档号共用同一前缀参数；
- 原生 select 仍保留为状态源，视觉隐藏，不影响现有加载逻辑。
