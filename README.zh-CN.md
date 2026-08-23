# fisproxy

[FisProxy](https://fisproxy.org) 用户会话接口的官方 Python SDK。

在已登录的用户中心 **API** 页创建令牌，明文仅显示一次。本客户端不提供账号登录。

默认接入点：`https://api.fisproxy.org`。请求签名由 SDK 自动完成。

英文说明见 [README.md](README.md)。

## 安装

```bash
pip install git+https://github.com/nyaproxy/fisproxy-python-sdk.git
```

需要 Python 3.9 或更高版本，无第三方运行时依赖。

```python
from fisproxy import Client

client = Client.from_env()  # 读取环境变量 FISPROXY_API_TOKEN
```

也可直接传入令牌：

```python
client = Client("fp_...")
```

| 环境变量 | 说明 |
|---|---|
| `FISPROXY_API_TOKEN` | 必填。用户中心 API 页签发的 Bearer 令牌 |
| `FISPROXY_API_BASE` | 可选。默认 `https://api.fisproxy.org` |
| `FISPROXY_CLIENT_ID` | 可选。进程内稳定的客户端标识，须匹配 `[A-Za-z0-9._~:-]{1,96}` |

`service_point`、`nfa_coin` 以及停止计费时的 `deduction` 均为十进制字符串，请勿转换为浮点数。

完整示例见 [`examples/session.py`](examples/session.py)。

---

## `me()` — 查询当前账户

对应 `GET /api/v1/me`。

```python
profile = client.me()
```

### 返回 `UserProfile`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 用户 ID |
| `username` | `str \| None` | 用户名 |
| `balances.service_point` | `str` | 服务点数余额，十进制字符串 |
| `balances.nfa_coin` | `str` | NFA Coin 余额，十进制字符串 |
| `balances.subscription_pass` | `str` | 订阅通行余额，十进制字符串 |
| `session` | `dict \| None` | 当前会话摘要；无会话时为 `None` |
| `raw` | `dict` | 完整 JSON 响应 |

`raw` 还包含：

```json
{
  "ok": true,
  "user": {
    "id": "…",
    "legacyAid": 12345,
    "username": "example",
    "email": "…",
    "status": "normal",
    "autoNfa": true,
    "createdAt": "2026-01-01T00:00:00.000Z",
    "balances": {
      "service_point": "12.50",
      "nfa_coin": "3",
      "subscription_pass": "0"
    },
    "currentSession": null
  },
  "bindings": [],
  "nfa": {
    "stock": { "total": 0, "available": 0, "hypixelAvailable": 0 },
    "trialAvailable": false
  }
}
```

会话存在时，`user.currentSession` / `profile.session` 的主要字段：

| 字段 | 说明 |
|---|---|
| `id` | 内部会话 ID |
| `sessionId` | 对外会话号（连接地址前缀） |
| `serviceId` | 服务 ID |
| `state` | 会话状态，例如 `starting`、`running` |
| `target` | 上游目标 |
| `startedAt` | 创建时间（ISO 8601） |
| `billingStartedAt` | 开始计费时间；尚未接通时可能为空 |

接口不返回落地 IP。

---

## `services()` — 列出可用服务

对应 `GET /api/v1/me/services`。

```python
for service in client.services():
    print(service["id"], service["name"], service["hasAccess"])
```

### 返回

`tuple[dict, …]`，每项对应一个对当前用户可见的服务。完整响还可经 `client.request("GET", "/api/v1/me/services")` 取得：

```json
{
  "ok": true,
  "services": [
    {
      "id": "us.hypixel",
      "name": "Hypixel",
      "alias": "hypixel",
      "description": "…",
      "type": "…",
      "target": "mc.hypixel.net",
      "allowAutoNfa": true,
      "entranceCount": 3,
      "hasAccess": true,
      "accessReason": null,
      "subscriptionActive": false
    }
  ],
  "serviceStartEnabled": true,
  "serviceStartDisabledReason": null
}
```

`start(service_id=…)` 使用这里的 `id`。`hasAccess` 为 `false` 时表示当前权益不足。

---

## `status()` — 查询会话与连接入口

对应 `GET /api/v1/sessions/status`。

```python
status = client.status()
if status.running:
    print(status.address)
```

### 返回 `SessionStatus`

| 字段 | 类型 | 说明 |
|---|---|---|
| `running` | `bool` | 当前是否存在会话 |
| `session` | `dict \| None` | 会话摘要；未运行时为 `None` |
| `address` | `str \| None` | 主连接地址 |
| `entrance` | `str \| None` | 与 `address` 相同 |
| `entrances` | `tuple[Entrance, …]` | 全部可用入口 |
| `raw` | `dict` | 完整 JSON 响应 |

未运行时：

```json
{
  "ok": true,
  "running": false,
  "session": null,
  "entrances": []
}
```

运行中：

```json
{
  "ok": true,
  "running": true,
  "session": { "id": "…", "sessionId": "4242", "state": "running" },
  "entrance": "4242.hk.example",
  "address": "4242.hk.example",
  "entrances": [
    {
      "id": "e1",
      "name": "Hong Kong",
      "host": "hk.example",
      "address": "4242.hk.example"
    }
  ]
}
```

### `Entrance`

| 字段 | 说明 |
|---|---|
| `id` | 入口 ID |
| `name` | 显示名称 |
| `host` | 入口主机名 |
| `address` | 连接地址。会话未开始时等于 `host`；开始后为 `{sessionId}.{host}` |

Minecraft 请连接 `status.address`（或 `entrances[].address`），与加速页复制的字符串相同。更换出口 IP 后入口通常不变。

---

## `entrances(service_id=None)` — 按服务查询入口

对应 `GET /api/v1/me/entrances?serviceId=`。

```python
client.entrances("us.hypixel")
```

未指定 `service_id` 时，服务端默认查询 `default` 服务。服务不可见时返回 404。

### 返回

`tuple[dict, …]`，字段与 `status().entrances` 相同：`id`、`name`、`host`、`address`。若当前已有会话，`address` 会带上会话号前缀。

---

## `start(...)` — 开始计费

对应 `POST /api/v1/sessions/start`。HTTP **202**，不会立即接通。

```python
operation = client.start(wait=True)
print(operation.status, operation.session_id)
print(client.status().address)
```

### 参数（均为可选）

| 参数 | 说明 |
|---|---|
| `service_id` | 服务 ID，来自 `services()` |
| `target` | 上游目标，例如 `mc.hypixel.net` |
| `auto_nfa` | 是否自动分配 NFA |
| `nfa_item_id` | 指定 NFA 账号 |
| `reuse_nfa_item_id` | 复用历史连接的选择 ID |
| `nfa_source` | `local` 或 `solar` |
| `nfa_sku` | NFA SKU |
| `try_previous_nfa` | 尝试复用上一份 NFA |
| `idempotency_key` | 幂等键；缺省由 SDK 生成 |
| `wait` | 默认 `True`，轮询至操作结束 |
| `timeout` | 等待超时秒数，默认 `180` |
| `interval` | 轮询间隔秒数，默认 `1` |

`wait=False` 时立即返回排队中的 `Operation`。`wait=True` 且操作失败或取消时抛出 `OperationFailed`。

即时响应：

```json
{
  "ok": true,
  "operation": {
    "id": "op-…",
    "kind": "session.start",
    "status": "queued",
    "progressPhase": "queued",
    "cancelable": true,
    "createdAt": "2026-01-01T00:00:00.000Z",
    "updatedAt": "2026-01-01T00:00:00.000Z"
  }
}
```

成功后 `operation.result`：

| 字段 | 说明 |
|---|---|
| `kind` | `start` |
| `sessionId` | 对外会话号 |
| `entrances` | 连接入口列表（含 `address`） |
| `state` | 会话状态 |
| `serviceId` | 服务 ID |

已有冲突操作时抛出 `ConflictError`，`existing_operation` 为正在执行的操作。

---

## `change_ip(...)` — 更换出口 IP

对应 `POST /api/v1/sessions/change-ip`。HTTP **202**。

```python
operation = client.change_ip(wait=True)
print(operation.route_acked)
```

更换的是出口，连接入口通常不变。成功表示落地与路由已提交；路由真正生效前应确认 `result.routeAcked` 为 `true`。`wait=True`（默认）时，SDK 会等到操作结束，并在成功后继续等待 `routeAcked`。

成功后 `operation.result`：

| 字段 | 说明 |
|---|---|
| `kind` | `change_ip` |
| `sessionId` | 对外会话号 |
| `state` | 会话状态 |
| `routeStatus` | 路由命令状态 |
| `routeAcked` | 路由是否已确认 |

---

## `stop()` — 停止计费

对应 `POST /api/v1/sessions/stop`。HTTP **200**，同步返回结算结果。

```python
stopped = client.stop()
print(stopped.duration, stopped.deduction)
```

### 返回 `StopResult`

| 字段 | 类型 | 说明 |
|---|---|---|
| `duration` | `int` | 计费时长（分钟） |
| `deduction` | `str` | 扣费金额，十进制字符串 |
| `session` | `dict \| None` | 停止前的会话快照 |
| `canceled_operations` | `int` | 一并取消的未完成操作数 |
| `raw` | `dict` | 完整 JSON 响应 |

```json
{
  "ok": true,
  "duration": 12,
  "deduction": "0.40",
  "session": { "id": "…", "sessionId": "4242", "state": "running" }
}
```

---

## 异步操作

`start` 与 `change_ip` 返回 `Operation`。可用以下方法继续跟踪：

```python
op = client.get_operation("op-…")
op = client.wait_operation("op-…", timeout=180, interval=1)
client.cancel_operation("op-…")
client.list_operations(status="running", kind="session.start", limit=20)
```

### `Operation`

| 字段 | 说明 |
|---|---|
| `id` | 操作 ID |
| `kind` | 例如 `session.start`、`session.change_ip` |
| `status` | `queued` / `waiting` / `running` / `succeeded` / `failed` / `canceled` 等 |
| `progress_phase` | 进度阶段 |
| `result` | 成功后的结果对象 |
| `message` | 说明或失败信息 |
| `error_code` | 失败错误码 |
| `succeeded` | `status == "succeeded"` |
| `terminal` | 是否已结束 |
| `route_acked` | `result.routeAcked is True` |
| `session_id` | `result.sessionId` |
| `entrances` | `result.entrances` 解析后的入口列表 |
| `raw` | 完整 JSON |

`wait_operation` 在 `failed` 或 `canceled` 时抛出 `OperationFailed`。

---

## 异常

| 异常 | 说明 |
|---|---|
| `AuthError` | 令牌无效、已吊销或账户被封禁 |
| `AdmissionError` | 请求未被接受；短暂失败会由 SDK 自动重试 |
| `ConflictError` | 已有冲突操作（HTTP 409），见 `existing_operation` |
| `OperationFailed` | 异步操作以 `failed` 或 `canceled` 结束，见 `operation` |
| `OperationTimeout` | 等待操作超时 |
| `TransportError` | 网络错误 |

---

## 许可证

MIT
