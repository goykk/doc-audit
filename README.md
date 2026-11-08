# DocAudit — 多模态文档智能抽取与稽核系统

从票据到**可信**结构化数据：MinerU 解析 + LLM 结构化（路线A）与 Qwen-VL 端到端（路线B）双管线对比，
统一出口后进入规则校验稽核层，并用字段级 F1、行项目准确率、幻觉率、证据命中率与成本时延做量化评测。

## 当前进度

- [x] D1：仓库骨架、MySQL 五表、统一 ExtractionResult 契约、标注规范与数据集评分白名单
- [x] D2：MinerU 2.7.6 解析跑通（独立 Python 3.12 venv；CPU 已验收，CUDA 轮子待装）
- [x] D3：CORD 10 份真实样本入库 + 字段级评测链路（自检 F1=1.0）
- [x] D4：路线A 跑通（MinerU + LLM 双调用 + 证据回填），10 份真实预测 F1=0.5932
- [x] D5：路线B（qwen3-vl-plus 端到端）F1=0.8493，E1 对比报告已出
- [x] W2-1：14 条 YAML 校验规则 + 三层重复检测 + 状态分流
- [x] W2-2：校验结果落 MySQL、复核队列 API、复核动作回写与 audit_log
- [x] W2-3：22 张合成中文发票 + E3 校验增益（真实链路拦截 91.67%）
- [x] W2-4：E2 结构化输出消融（负结论：强模型下 Schema 无 F1 收益）
- [x] W3-1：样本扩到 150（CORD 100 + 合成中文 50）并重跑主指标
- [x] W3-2：单文件前端（文档选择、bbox 证据高亮、复核动作）
- [x] W3-3：Docker 一键启动（app + MySQL）
- [x] P0：上传 → 路线B抽取 → 校验 → 落库 → 前端打开结果
- [x] P1：双管线版本共存，前端可切换路线A/B
- [x] P2：A/B 并排对比视图（字段差异 + A 证据联动）
- [x] P3：A/B 决策台（差异行采纳 A/B，写入 merged 版本与 audit_log）
- [x] P4：决策后自动重校验，状态与复核项实时更新
- [x] P5：金额规则建议修正（R003 不再猜总额，点名多出行）
- [x] P6：人工修改服务端校验（金额/数量/税率/日期/税号）
- [x] P7：普通复核 modify/accept 后自动重校验
- [x] P8：复核队列、批量驳回、R005 人工修正保护
- [x] P9：复核队列前端分页（15/页）与全选本页
- [x] P10：服务端筛选分页 + 批量采纳建议
- [x] P11：队列索引 + ngram 全文搜索优化
- [x] P12：搜索通道拆分 + 字段复合索引
- [x] P13：前缀搜索 UNION 派生表优化
- [x] P14：文档列表 dataset/status 过滤与索引
- [x] P15：状态筛选与动态数据集 facets
- [x] P16：facets 双维联动计数
- [x] P17：文档选择器搜索与分页
- [x] P18：文件名包含搜索 + 选择器键盘导航
- [x] P19：文件名 ngram 全文 + 双通道 UNION 搜索
- [x] P20：updated_at 与最近更新/相关度排序
- [x] P21：复核/重抽取刷新 updated_at
- [x] P22：稽核概览与复核 resolved_at 索引
- [x] P23：概览 7 天趋势与 60 秒缓存
- [x] P24：复核/抽取/决策后主动失效统计缓存
- [x] P25：数据集概览与版本化缓存
- [x] P26：stats_version 持久版本 + 状态概览
- [x] P27：文档审计时间线
- [x] P28：审计筛选、分页与 CSV 导出
- [x] P29：CSV BOM 与公式注入防护
- [x] P30：手动重跑校验
- [x] P31：CI 与 API 集成测试
- [x] P32：API 令牌与角色控制

## MinerU 独立环境（Python 3.12）

MinerU 固定 **2.7.6**：4.x 已改用另一套 CLI/结果契约，而本项目需要经典 `pipeline` 后端的
`content_list.json` 与 `middle.json`。不要把它装进主服务 `.venv`。

```bash
uv venv .venv-mineru --python 3.12
uv pip install --python .venv-mineru/Scripts/python.exe -r requirements-mineru.txt
./.venv/Scripts/python scripts/make_sample_pdf.py
PYTHONPATH=src ./.venv/Scripts/python scripts/parse_pdf.py data/raw/sample_receipt.pdf sample_receipt --device cuda
# 无 CUDA 时显式使用 --device cpu；CUDA 不可用时程序会报错，不会静默改设备。
```

产物统一落在 `data/processed/{doc_id}/`：`content.md`、`content_list.json`、`layout.json`、
`blocks.json`、`tables/*.html`、`pages/page_001.png`、`manifest.json` 和 MinerU 日志。

**坐标契约**：MinerU `content_list.json` 的 bbox 是 **0–1000 归一化坐标**，`blocks.json` 已转换为
渲染图像素坐标（默认 200dpi），可直接用于前端高亮与证据 IoU 计算。`layout.json` 保留 PDF
point 坐标，不要与 `blocks.json` 混用。

## 数据与评测

```bash
# CORD-v2 测试集 parquet -> data/raw/cord + data/ground_truth/cord + manifest.jsonl
./.venv/Scripts/python scripts/prepare_cord.py --limit 10

# 预测文件按 {doc_id}.json 放入 pred-dir，再跑字段级评测
PYTHONPATH=src ./.venv/Scripts/python scripts/evaluate.py \
  --pred-dir data/predictions/route_a --dataset cord --out reports/eval_cord_route_a
```

评测口径：只算 `dataset_fields.yaml` 白名单；真缺失（双方 null）不计入 TP/FP/FN；真值为空而预测有值记幻觉，
反之为漏抽；金额与数量按 Decimal 归一（去千分位/货币符号），文本按空白与大小写归一。
CORD 使用印尼数字格式（`28.000` = 28000），评测按数据集 locale 归一，不与中文小数点混淆。
行项目按描述相似度 + 金额 + 数量做一对一对齐，顺序不同不再连锁判错；多出的行记幻觉，缺失的行记漏抽。

## 路线A：MinerU + LLM

```bash
# 图片 -> 单页 PDF -> MinerU 解析 -> 头部/行项目两次 LLM 调用 -> quote 回填 bbox
PYTHONPATH=src ./.venv/Scripts/python scripts/run_route_a.py --dataset cord --device cpu
PYTHONPATH=src ./.venv/Scripts/python scripts/evaluate.py \
  --pred-dir data/predictions/route_a --dataset cord --out reports/eval_cord_route_a
```

头部字段与行项目分两次调用，避免行项目被头部抽取挤掉；每次调用都有一次 JSON 修复重试。
预测文件、原始模型输出（`debug/`）和 `run_log.jsonl` 都落在 `data/predictions/route_a/`。
成本按 `LLM_INPUT_PRICE_PER_1K` / `LLM_OUTPUT_PRICE_PER_1K` 计算（默认取 qwen-plus 参考价，
账号折扣不同请自行改 `.env`）。

## 路线B：Qwen-VL 端到端

```bash
PYTHONPATH=src ./.venv/Scripts/python scripts/run_route_b.py --dataset cord
PYTHONPATH=src ./.venv/Scripts/python scripts/evaluate.py \
  --pred-dir data/predictions/route_b --dataset cord --out reports/eval_cord_route_b
./.venv/Scripts/python scripts/compare_routes.py      # 生成 E1 对比报告
```

图片按长边 1600px 压缩后以 data URL 输入；单次调用返回头部字段与行项目，不返回证据坐标。

## 稽核校验

```bash
PYTHONPATH=src ./.venv/Scripts/python scripts/run_validation.py \
  --pred-dir data/predictions/route_b --dataset cord --out reports/validation_route_b
```

14 条规则与三层重复检测的说明见 `docs/validation_rules.md`。规则缺失字段记 `skipped`，
空抽取强制进复核，不允许自动通过。

## 落库与复核队列

```bash
PYTHONPATH=src ./.venv/Scripts/python scripts/persist_run.py \
  --pred-dir data/predictions/route_a --dataset cord
uvicorn app.api.main:app --app-dir src --reload
```

| 接口 | 说明 |
| --- | --- |
| `POST /api/v1/documents` | 上传 PDF/PNG/JPG（≤15MB），返回 doc_id（PDF 自动取第一页预览） |
| `POST /api/v1/extract` | 对上传文档执行路线B抽取 + 校验 + 落库 |
| `GET /api/v1/review/queue?status=pending` | 待复核队列，支持 `rule_id/q/limit/offset`，返回 total/rules |
| `POST /api/v1/review/{item_id}` | 复核动作 `accept/modify/reject`，可带 `value` 与 `note` |
| `POST /api/v1/review/batch` | 批量驳回/采纳建议（自动去重，返回 processed/failed） |
| `GET /api/v1/documents` | 文档列表与最新抽取状态 |
| `GET /api/v1/documents/{doc_id}` | 抽取结果、校验结果、复核项、audit_log、可选 `?pipeline=layout_llm\|vlm_e2e` |
| `GET /api/v1/documents/{doc_id}/compare` | 同时返回 A/B 两条管线的完整结果 |
| `POST /api/v1/documents/{doc_id}/select` | A/B 决策：采纳某管线字段/整行，写入 merged 版本 |
| `GET /api/v1/documents/{doc_id}/image` | 原图/PDF 首页预览（限制在 data/ 目录） |

复核动作会同步更新 `review_items`、`field_values`、`extractions.result_json` 和
`validations.audit_log`；当一份文档的所有复核项都处理完后，文档状态按人工决定重算。
重复提交已处理的复核项返回 409。

## 合成中文发票与 E3

```bash
./.venv/Scripts/python scripts/make_synthetic_invoices.py
PYTHONPATH=src ./.venv/Scripts/python scripts/run_route_b.py --dataset synthetic
PYTHONPATH=src ./.venv/Scripts/python scripts/evaluate.py \
  --pred-dir data/predictions/route_b --dataset synthetic --out reports/eval_synthetic_route_b
PYTHONPATH=src ./.venv/Scripts/python scripts/evaluate_validation.py \
  --pred-dir data/predictions/route_b --dataset synthetic --out reports/e3_pipeline_synthetic
```

50 份合成票（38 干净 + 10 故障 + 2 重复）覆盖 R001~R013，数据集设计与结果见
`docs/synthetic_dataset.md`。

## E2 结构化输出消融

```bash
for m in free object schema; do
  PYTHONPATH=src ./.venv/Scripts/python scripts/run_e2_experiment.py --mode $m --dataset cord --limit 10
  PYTHONPATH=src ./.venv/Scripts/python scripts/evaluate.py \
    --pred-dir data/predictions/e2_$m --dataset cord --out reports/e2_${m}_eval
done
./.venv/Scripts/python scripts/compare_e2.py
```

同一批图、同一 prompt，只改 `response_format`。当前强模型下三种模式格式错误率都是 0，
严格 Schema 的 F1 反而略低且 token 增加 58%；负结论与边界写在 `reports/e2_structured_output.md`。

## 评估总览（150 份）

| 数据集 | 路线 | 规模 | 字段 F1 | 行项目整单 | 幻觉率 | 漏抽率 |
| --- | --- | --- | --- | --- | --- | --- |
| CORD-v2 | 路线B qwen3-vl-plus | 100 | **0.8640** | 48% | 11.21% | 1.72% |
| 合成中文发票 | 路线B qwen3-vl-plus | 50 | 0.9980 | 100% | 0% | 0% |
| CORD-v2 子集 | 路线A MinerU + qwen-plus | 10 | 0.5932 | 10% | 9.80% | 31.34% |

- CORD 100 份：P 0.8222 / R 0.9102，P50 9.1s，P95 24.8s。
- E1 只做 10 份同口径对比（路线A 的 CPU 解析成本太高）；路线B 的 100 份是主指标。
- E3：Oracle 12/12 拦截；真实 pipeline 拦截 11/12，0/37 干净误报；详见 `docs/synthetic_dataset.md`。

## 前端与部署

```bash
docker compose up -d --build
# http://localhost:8000
```

单文件 `src/frontend/index.html`：上传票据（PDF/PNG/JPG）→ 路线B抽取 → 校验 → 自动打开结果；
左原文右字段、琥珀色证据框（冲突红 / 存疑黄）、待复核项采纳/修改/驳回。
同一文档存在 A/B 两条抽取时，顶部出现路线切换，字段、bbox、校验状态、复核项同步切换。
“A/B 并排对比”打开全屏决策台：左原文 + A 证据框，右四列（字段 / 路线A / 路线B / 当前合并），
差异行黄底；点击“采纳”把 A 或 B 的值写入独立的 merged 版本，A/B 原件不变，
决策进入 audit_log，并立即重跑 14 条规则、重建复核项、更新状态；支持 `?doc=&compare=1` 直达。

上传走 `POST /api/v1/documents` + `POST /api/v1/extract`，单张约 10~20 秒。

![上传后视图](reports/ui_upload_flow.png)

![双管线切换](reports/ui_pipeline_switch.png)

![A/B 并排对比](reports/ui_ab_compare.png)

![A/B 决策台](reports/ui_ab_decision.png)

![R003 人工修正](reports/ui_p5_r003_review.png)

![数据集筛选](reports/ui_p14_dataset_filter.png)

![状态筛选](reports/ui_p15_status_filter.png)

![Facets 联动](reports/ui_p16_facets_linked.png)

![文档选择器](reports/ui_p17_doc_picker.png)

![键盘导航](reports/ui_p18_doc_picker_keyboard.png)

![最近更新排序](reports/ui_p20_recent_order.png)

![稽核概览](reports/ui_p22_stats.png)

![7天趋势](reports/ui_p23_stats_trend.png)

![数据集概览](reports/ui_p25_stats_dataset.png)

![状态概览](reports/ui_p26_stats_status.png)

![审计时间线](reports/ui_p27_audit.png)

![审计筛选](reports/ui_p28_audit_filters.png)

![重跑校验审计](reports/ui_p30_revalidate.png)

![复核队列](reports/ui_p8_queue.png)

![队列分页](reports/ui_p9_queue_pagination.png)

![服务端队列](reports/ui_p10_server_queue.png)

![搜索定位](reports/ui_p12_search.png)

当前数据库 153 份：CORD 100（前 10 份同时有 A/B，其余 B）、合成中文 50、上传样例 3；
`GET /api/v1/documents/{id}` 默认返回 `is_current` 管线，也可用 `?pipeline=` 指定。

## 快速开始

```bash
cp .env.example .env        # 填入 DASHSCOPE_API_KEY，密钥不入库
docker compose up -d --build   # app + MySQL，首次启动自动建表
# 已有旧库升级到双管线：
# docker exec -i docaudit-mysql mysql -uroot -proot_pwd -D docaudit < infra/mysql/init/002_pipeline_versions.sql
# docker exec -i docaudit-mysql mysql -uroot -proot_pwd -D docaudit < infra/mysql/init/003_review_indexes.sql
# docker exec -i docaudit-mysql mysql -uroot -proot_pwd -D docaudit < infra/mysql/init/004_review_field_index.sql
# docker exec -i docaudit-mysql mysql -uroot -proot_pwd -D docaudit < infra/mysql/init/005_documents_filters.sql
# docker exec -i docaudit-mysql mysql -uroot -proot_pwd -D docaudit < infra/mysql/init/006_documents_filename_ft.sql
# docker exec -i docaudit-mysql mysql -uroot -proot_pwd -D docaudit < infra/mysql/init/007_documents_updated_at.sql
# docker exec -i docaudit-mysql mysql -uroot -proot_pwd -D docaudit < infra/mysql/init/008_documents_updated_index.sql
# docker exec -i docaudit-mysql mysql -uroot -proot_pwd -D docaudit < infra/mysql/init/009_review_resolved_index.sql
# docker exec -i docaudit-mysql mysql -uroot -proot_pwd -D docaudit < infra/mysql/init/010_stats_version.sql
# 打开 http://localhost:8000
```

本地开发：

```bash
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.api.main:app --app-dir src --reload     # GET /api/health
```

## 目录

```
src/app/
  extraction_result.py   # 双管线唯一出口契约（Pydantic）
  config.py              # 环境变量配置
  pipelines/             # 解析预处理、路由
  extractors/            # 路线A / 路线B
  validation/            # YAML 规则、重复检测、状态分流
  evaluation/            # 字段级评测、分层报告
  api/                   # FastAPI
src/frontend/            # 单文件演示页（左原文右字段，bbox 高亮）
data/ground_truth/       # 标注 + manifest + 评分白名单
infra/mysql/init/        # 五张表 DDL
docs/annotation_spec.md  # 标注规范（冻结版）
reports/                 # 评测报告输出
```

## 两条不可破坏的约定

1. 两条管线只能返回 `ExtractionResult`，字段路径规范见 `docs/annotation_spec.md`。
2. 评分只算 `data/ground_truth/dataset_fields.yaml` 白名单内的字段；`null` 表示真缺失，与抽错分开统计。


## 测试与 CI

```bash
# 本地全量（需要 compose 中 MySQL）
REQUIRE_DB_TESTS=1 ./.venv/Scripts/python -m pytest -q

# 可选：空库迁移验证
# 1) 新建临时库 2) 依次执行 infra/mysql/init/*.sql 3) MYSQL_DATABASE=<临时库> pytest
```

GitHub Actions 在 `.github/workflows/ci.yml`：MySQL 8.0.36 service、Python 3.11、
执行 001–010 迁移后运行全量测试；`REQUIRE_DB_TESTS=1` 防止数据库不可用时静默跳过。


## API 认证

默认关闭，保持本地演示可用。生产环境：

```env
AUTH_REQUIRED=true
API_KEYS={"viewer-key":"viewer","reviewer-key":"reviewer"}
```

- `Authorization: Bearer <token>` 或 `X-API-Key`
- viewer 只读，reviewer 可复核/上传/重跑
- 未配置 key 且开启认证时，API 默认全部拒绝
