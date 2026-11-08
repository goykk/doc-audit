# P18 文件名包含搜索与键盘导航验收

## 文件搜索

`/api/v1/documents?q=` 现在：

- `doc_id` 前缀匹配（保持索引可用）
- `filename` 包含匹配（支持路径中段）

实测：

```text
syn_invoice_001 -> 10
invoice_001     -> 10（命中文件名中段）
0019.png        -> 2（cord_test_0019 / syn_invoice_0019）
```

## 键盘导航

文档选择弹窗支持：

- `ArrowDown` / `ArrowUp` 移动高亮
- `Enter` 选中当前高亮项并关闭
- `Esc` 关闭
- 鼠标悬停同步高亮
- 翻页/搜索后高亮重置到第 1 行
- 高亮项自动 `scrollIntoView`

## 浏览器验证

```text
搜索 invoice_001 -> 10 份 / 10 行
ArrowDown ×2 -> keyboard_index 2
Enter -> 关闭弹窗，按钮更新为 syn_invoice_0017 · synthetic · review
console errors 0
```

截图：`reports/ui_p18_doc_picker_keyboard.png`。

## 测试

71 个测试通过；容器 healthy，页面 200。

## 边界

- 文件名包含搜索使用 `%q%`，未建全文索引，十万级文档需要 ngram/fulltext；
- 方向键会阻止搜索框光标移动，这是弹窗内的有意行为；
- 键盘高亮仅在弹窗打开时生效。
