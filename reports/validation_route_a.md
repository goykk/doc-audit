# 稽核报告（cord · 10 份）

- 自动通过 accepted：3
- 待复核 review：5
- 驳回 rejected：2
- 问题条数：8

## 规则执行情况

| 规则 | 名称 | 类别 | 级别 | 通过 | 失败 | 跳过 | 问题数 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R001 | 价税合计一致 | arithmetic | error | 0 | 0 | 10 | 0 |
| R002 | 中文大写金额与小写一致 | cross_field | error | 0 | 0 | 10 | 0 |
| R003 | 行项目合计等于小计/总额 | arithmetic | error | 3 | 2 | 5 | 2 |
| R004 | 税率与税额匹配 | cross_field | warn | 0 | 0 | 10 | 0 |
| R005 | 纳税人识别号格式 | format | warn | 0 | 0 | 10 | 0 |
| R006 | 开票日期合理性 | business | warn | 0 | 0 | 10 | 0 |
| R007 | 数量乘单价等于行金额 | arithmetic | warn | 1 | 0 | 9 | 0 |
| R008 | 含税合计字段互证 | cross_field | error | 0 | 0 | 10 | 0 |
| R009 | 发票号码格式 | format | warn | 0 | 0 | 10 | 0 |
| R010 | 日期格式 | format | warn | 0 | 0 | 10 | 0 |
| R011 | 金额与数量非负 | business | error | 7 | 0 | 3 | 0 |
| R012 | 重复票据检测 | cross_document | error | 10 | 0 | 0 | 0 |
| R013 | 同票号金额冲突 | cross_document | error | 10 | 0 | 0 | 0 |
| R014 | 字段置信度阈值 | confidence | warn | 5 | 5 | 0 | 6 |

## 文档状态

| 文档 | 状态 | 最低置信度 | error | warn | 命中规则 |
| --- | --- | --- | --- | --- | --- |
| cord_test_0000 | accepted | 0.900 | 0 | 0 | - |
| cord_test_0001 | rejected | 0.900 | 1 | 0 | R003 |
| cord_test_0002 | accepted | 0.900 | 0 | 0 | - |
| cord_test_0003 | accepted | 0.850 | 0 | 0 | - |
| cord_test_0004 | review | 0.600 | 0 | 2 | R014 |
| cord_test_0005 | review | 0.000 | 0 | 1 | R014 |
| cord_test_0006 | rejected | 0.850 | 1 | 0 | R003 |
| cord_test_0007 | review | 0.000 | 0 | 1 | R014 |
| cord_test_0008 | review | 0.600 | 0 | 1 | R014 |
| cord_test_0009 | review | 0.000 | 0 | 1 | R014 |

## 问题清单（前 30 条）

| 文档 | 规则 | 级别 | 字段 | 信息 | 建议值 |
| --- | --- | --- | --- | --- | --- |
| cord_test_0001 | R003 | error | amount_total | 行项目金额合计与小计或总额不符：行项目合计 182000，amount_total=91000 | 182000 |
| cord_test_0004 | R014 | warn | line_items[1].amount | 字段置信度低于阈值，需人工复核：置信度 0.700 < 0.85 | - |
| cord_test_0004 | R014 | warn | line_items[3].description | 字段置信度低于阈值，需人工复核：置信度 0.600 < 0.85 | - |
| cord_test_0005 | R014 | warn | - | 未抽取到任何有效字段，无法确认可信度 | - |
| cord_test_0006 | R003 | error | subtotal | 行项目金额合计与小计或总额不符：行项目合计 46060，subtotal=46000 | 46060 |
| cord_test_0007 | R014 | warn | - | 未抽取到任何有效字段，无法确认可信度 | - |
| cord_test_0008 | R014 | warn | line_items[0].quantity | 字段置信度低于阈值，需人工复核：置信度 0.600 < 0.85 | - |
| cord_test_0009 | R014 | warn | - | 未抽取到任何有效字段，无法确认可信度 | - |
