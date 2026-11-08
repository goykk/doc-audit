# P31 CI 与 API 集成测试验收

## 新增

- `pytest.ini`：`pythonpath=src`、`testpaths=tests`
- `.github/workflows/ci.yml`：GitHub Actions + MySQL 8.0.36 service
- `tests/test_api_integration.py`：真实 MySQL 集成测试

## 集成测试覆盖

1. `/api/v1/stats?dataset=...` 数据集统计与 pending 数
2. `/api/v1/documents/{id}/audit?event=...` 事件过滤与 old/new
3. `/api/v1/documents/{id}/audit.csv` BOM、表头、内容
4. `POST /api/v1/documents/{id}/revalidate` 状态返回与审计事件

测试使用 `ci_smoke_doc` 临时数据，fixture 结束自动删除并失效统计缓存。

## CI 流程

```text
checkout
setup-python 3.11
pip install -r requirements.txt
apt-get install mysql-client
for file in infra/mysql/init/*.sql: mysql docaudit < file
pytest -q
```

`REQUIRE_DB_TESTS=1` 确保 CI 中数据库不可用时直接失败，不静默 skip。

## 验证

本地全量：

```text
78 passed, 1 warning in 1.99s
```

空库迁移链模拟：

```text
drop/create docaudit_ci_test
apply 001..010.sql
pytest tests/test_api_integration.py
4 passed
```

工作流 YAML 解析：

```text
workflow steps 6
```

## 边界

- GitHub Actions 未在本机实际触发，验证依据是 YAML 解析 + 本地空库等价执行；
- 集成测试只覆盖四条关键 API，不含浏览器 E2E；
- CI 未跑 MinerU 独立环境，路线A解析仍依赖本地环境；
- 未加依赖缓存审计、SAST、镜像构建。
