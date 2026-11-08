# P32 API 令牌与角色控制验收

## 实现

新增 `app/auth.py`：

- `viewer`：GET/HEAD/OPTIONS
- `reviewer`：可写
- `admin`：最高级，当前无专属接口
- `API_KEYS` 为 JSON map：`{"token":"role"}`
- `AUTH_REQUIRED=true` 开启；默认 false，保持本地演示兼容
- 支持 `Authorization: Bearer <token>` 与 `X-API-Key`
- 公共路径：`/`、`/api/health`、`/docs`、`/openapi.json`
- 缺 token → 401；角色不足 → 403
- 开启但未配置 key 时全部 API 拒绝，失败关闭

前端 `api()`：

- 自动读取 `localStorage.docaudit_token`
- 401 时弹窗输入令牌并重试一次
- 健康检查不触发弹窗

## 验证

```text
tests/test_auth.py 2 passed
全量 80 passed
/api/health 无 token 200
/api/v1/stats 无 token 401
错误 token 401
viewer GET 通过
viewer POST 403
reviewer POST 通过中间件（到参数校验 422）
```

## 配置

```env
AUTH_REQUIRED=true
API_KEYS={"viewer-key":"viewer","reviewer-key":"reviewer"}
```

## 边界

- 默认未开启，生产必须显式设置 `AUTH_REQUIRED=true`；
- 角色是粗粒度，所有写接口都要求 reviewer；
- 审计事件里的 `by` 仍是 `human`，尚未写入具体 principal 名称；
- 没有登录页、会话、刷新令牌、密钥轮换。
