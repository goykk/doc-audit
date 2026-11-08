# P29 CSV 导出加固验收

## 改动

1. CSV 输出前加 UTF-8 BOM（`EF BB BF`），Excel 直接打开中文不再乱码。
2. `_csv_safe` 拦截公式注入：
   - 以 `=`、`+`、`@`、Tab、CR 开头的单元格前置 `'`
   - 负数 `-5` 保持原样，避免金额被误改
   - dict/list 先 `json.dumps(ensure_ascii=False)`
3. 下载文件名清理：仅保留字母数字与 `._-`，最长 80 字符，空则 `document`。

## 实测

```text
bom efbbbf
bytes 998
first_line at,pipeline,event,field_path,old_value,new_value,action,note,by,validation_status
content-disposition: attachment; filename="cord_test_0001_audit.csv"
content-type: text/csv; charset=utf-8
```

单元测试：

```text
_csv_safe("=SUM(A1:A2)") -> "'=SUM(A1:A2)"
_csv_safe("+cmd")         -> "'+cmd"
_csv_safe("@user")        -> "'@user"
_csv_safe("-5")           -> "-5"
```

## 测试

74 个测试通过；容器 healthy，页面 200。

## 边界

- 只处理公式注入常见前缀，不替代服务端输出编码策略；
- 负数不转义，属于金额可读性取舍；
- CSV 仍受 5000 条上限约束。
