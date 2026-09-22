# Subscription Relay

一个轻量级的订阅中转与管理服务。

Subscription Relay 部署在境外服务器上，用于统一管理 Clash、v2rayN、Mihomo、sing-box 等客户端使用的订阅地址。服务端负责从原始订阅源获取订阅内容，并通过一个用户可直接访问的中转地址返回订阅内容。

项目主要解决以下问题：

- 某些订阅地址需要代理环境才能访问。
- 当本地代理失效后，无法重新访问订阅地址更新节点。
- 多台设备需要分别维护原始订阅地址。
- 希望隐藏原始订阅 URL 和其中的 Token。
- 希望在原始订阅源暂时不可用时，仍然可以使用最近一次成功获取的订阅内容。
- 希望通过一个简单的网页方便地管理和复制订阅地址。

第一版本以简单、稳定、易维护为目标，不引入数据库，所有配置使用 YAML 文件保存。

---

# 1. 项目目标

整个服务的核心链路如下：

```text
Clash / v2rayN / Mihomo / sing-box
                │
                │ 请求中转订阅
                ▼
       Subscription Relay
        香港 / 境外服务器
                │
                │ HTTPS 请求
                ▼
          原始订阅服务器
                │
                │ 返回订阅内容
                ▼
       Subscription Relay
                │
                ▼
             客户端
```

例如原始订阅地址：

```text
https://provider.example.com/api/subscribe?token=xxxxxxxx
```

经过 Subscription Relay 后，客户端只需要保存：

```text
https://sub.example.com/s/8LxK2pqN7MWa
```

用户无需直接访问原始订阅服务器。

---

# 2. 第一版本设计原则

第一版本定位为 MVP，只实现最核心功能。

设计原则：

1. 配置简单。
2. Docker 一键部署。
3. 不依赖数据库。
4. 不依赖 Redis。
5. 不解析订阅协议。
6. 不修改订阅内容。
7. 尽量原样转发订阅响应。
8. 支持文件缓存。
9. 支持网页管理。
10. 支持快速复制常用地址。

第一版不实现：

- Clash / V2Ray 协议转换
- 节点解析
- 节点合并
- 节点测速
- Redis
- MySQL / PostgreSQL
- 多用户系统
- 复杂权限系统
- 流量计费
- 多租户
- Celery
- 消息队列

Subscription Relay 第一阶段仅负责：

```text
订阅管理
+
远程拉取
+
安全中转
+
缓存容灾
+
快捷复制
```

---

# 3. 技术栈

后端使用 Python 实现。

推荐环境：

```text
Python 3.12
FastAPI
Uvicorn
httpx
PyYAML
Jinja2
Pydantic
Bootstrap
Docker
```

主要依赖：

```txt
fastapi
uvicorn[standard]
httpx
pyyaml
jinja2
python-multipart
itsdangerous
bcrypt
```

各库作用：

| 库 | 用途 |
|---|---|
| FastAPI | Web 服务和 API |
| Uvicorn | ASGI Server |
| httpx | 异步访问原始订阅服务器 |
| PyYAML | YAML 配置读取和保存 |
| Jinja2 | 管理页面 HTML 模板 |
| python-multipart | HTML Form 处理 |
| itsdangerous | Session / Cookie 签名 |
| bcrypt | 管理员密码 Hash |
| Pydantic | 配置结构校验 |

前端第一版不使用 Vue / React。

采用：

```text
Jinja2
+
Bootstrap
+
少量原生 JavaScript
```

实现后台页面。

---

# 4. 项目目录

推荐项目结构：

```text
subscription-relay/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── relay.py
│   ├── cache.py
│   ├── auth.py
│   ├── security.py
│   │
│   ├── templates/
│   │   ├── login.html
│   │   ├── index.html
│   │   └── edit.html
│   │
│   └── static/
│       ├── app.js
│       └── app.css
│
├── data/
│   ├── config.yaml
│   └── cache/
│
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

模块职责：

### main.py

FastAPI 主入口。

负责：

- 注册路由
- 注册模板
- Session
- API
- 页面路由
- 订阅中转接口

---

### config.py

负责：

```text
读取 config.yaml
保存 config.yaml
配置重新加载
订阅查找
Token 查找
```

---

### models.py

使用 Pydantic 定义 YAML 配置的数据结构。

例如：

```python
class Subscription(BaseModel):
    id: str
    name: str
    source_url: str
    access_token: str
    enabled: bool = True
    cache_ttl: int = 1800
```

通过 Pydantic 校验配置文件是否合法。

---

### relay.py

订阅中转核心模块。

负责：

```text
接收客户端请求
↓
确定订阅
↓
检查缓存
↓
访问原始订阅
↓
处理 Header
↓
保存缓存
↓
返回结果
```

---

### cache.py

负责文件缓存。

缓存不使用数据库。

例如：

```text
data/cache/
├── airport_a/
│   ├── content.bin
│   └── meta.json
│
└── airport_b/
    ├── content.bin
    └── meta.json
```

---

### auth.py

管理后台认证。

第一版仅支持：

```text
单管理员账户
```

无需用户数据库。

---

### security.py

主要负责：

```text
URL 校验
SSRF 防护
IP 地址检查
Token 生成
```

---

# 5. YAML 配置

整个系统的主要配置保存在：

```text
data/config.yaml
```

示例：

```yaml
server:
  public_base_url: "https://sub.example.com"

  admin_username: "admin"
  admin_password_hash: ""

  session_secret: "CHANGE_ME"

defaults:
  cache_ttl: 1800
  connect_timeout: 5
  read_timeout: 15
  max_response_size: 5242880

  user_agent_mode: "passthrough"

subscriptions:

  - id: "airport_a"
    name: "机场 A"

    enabled: true

    source_url: "https://provider-a.example.com/api/subscribe?token=xxxxx"

    access_token: "8LxK2pqN7MWa"

    cache_ttl: 1800

    user_agent_mode: "passthrough"

  - id: "airport_b"
    name: "机场 B"

    enabled: true

    source_url: "https://provider-b.example.com/sub?token=yyyyy"

    access_token: "X9mB7Kq2PLa3"

    cache_ttl: 3600

    user_agent_mode: "fixed"

    user_agent: "clash"
```

---

# 6. 订阅访问地址

每个订阅拥有一个随机访问 Token。

格式：

```text
/s/{token}
```

例如：

```text
https://sub.example.com/s/8LxK2pqN7MWa
```

其中：

```text
8LxK2pqN7MWa
```

本身相当于访问凭证。

因此 Token 应：

- 随机生成
- 长度足够
- 不容易猜测
- 支持重新生成

管理员重新生成 Token 后：

```text
旧地址立即失效
```

---

# 7. 管理后台

管理后台默认路径：

```text
/admin
```

例如：

```text
https://sub.example.com/admin
```

访问后台需要管理员登录。

第一版首页主要显示订阅列表。

示意：

```text
┌──────────────────────────────────────────────────┐
│ 机场 A                                  ● 正常   │
│                                                  │
│ 原始订阅                                         │
│ https://provider.example.com/***************     │
│                                                  │
│ 中转地址                                         │
│ https://sub.example.com/s/8LxK2pqN7MWa           │
│                                                  │
│ 最后成功：2026-09-22 13:40                       │
│ 最后失败：-                                      │
│ 缓存状态：Fresh                                  │
│                                                  │
│ [复制地址] [测试] [刷新缓存] [编辑]              │
│                                                  │
│ [更多服务 ▼]                                     │
└──────────────────────────────────────────────────┘
```

---

# 8. 快捷复制功能

快捷复制是管理后台的重要功能。

每个订阅提供：

```text
复制中转地址
复制原始地址
复制 curl 命令
复制 wget 命令
浏览器打开
```

其中最常用的是：

```text
[复制中转地址]
```

例如复制：

```text
https://sub.example.com/s/8LxK2pqN7MWa
```

---

## 8.1 curl

点击：

```text
复制 curl
```

复制：

```bash
curl -L "https://sub.example.com/s/8LxK2pqN7MWa"
```

---

## 8.2 wget

点击：

```text
复制 wget
```

复制：

```bash
wget -O subscription.txt "https://sub.example.com/s/8LxK2pqN7MWa"
```

---

## 8.3 JavaScript 实现

浏览器直接使用：

```javascript
navigator.clipboard.writeText(text)
```

无需额外前端依赖。

成功后按钮可以短暂显示：

```text
✓ 已复制
```

---

# 9. 原始订阅地址保护

原始订阅 URL 通常包含：

```text
token
key
auth
```

因此后台默认不要完整显示。

例如：

```text
https://provider.example.com/****************
```

提供：

```text
[显示]
[复制]
```

按钮。

避免：

- 截图泄露
- 远程桌面泄露
- 浏览器页面无意暴露

---

# 10. 订阅请求流程

客户端访问：

```text
GET /s/{token}
```

服务端处理流程：

```text
收到请求
   │
   ▼
查找 token
   │
   ├── 不存在 → 404
   │
   ▼
检查 enabled
   │
   ├── false → 404
   │
   ▼
检查缓存
   │
   ├── Fresh
   │      │
   │      └── 直接返回
   │
   ▼
请求原始订阅
   │
   ├── 成功
   │      │
   │      ├── 保存缓存
   │      │
   │      └── 返回最新内容
   │
   └── 失败
          │
          ├── 有旧缓存
          │      │
          │      └── 返回旧缓存
          │
          └── 无缓存
                 │
                 └── 返回错误
```

---

# 11. 缓存设计

第一版使用文件缓存。

无需 Redis。

例如：

```text
data/cache/airport_a/
```

包含：

```text
content.bin
meta.json
```

`content.bin`：

```text
原始订阅响应内容
```

`meta.json`：

```json
{
  "updated_at": "2026-09-22T13:40:00",
  "status_code": 200,
  "content_type": "text/plain",
  "source_url": "...",
  "headers": {}
}
```

---

# 12. 缓存生命周期

默认：

```text
cache_ttl = 1800
```

即：

```text
30 分钟
```

请求时：

```text
当前时间 - 最后成功更新时间 < TTL
```

则：

```text
直接返回缓存
```

否则重新访问原始订阅源。

每个订阅可以覆盖默认 TTL。

---

# 13. Stale Cache

如果原始订阅访问失败，但是存在历史缓存：

```text
返回最后一次成功缓存
```

例如：

```text
2026-09-22 12:00
成功获取订阅

2026-09-22 13:00
机场服务不可用

客户端请求
↓
返回 12:00 的缓存
```

响应可以增加：

```text
X-Subscription-Cache: stale
```

正常缓存：

```text
X-Subscription-Cache: hit
```

重新获取：

```text
X-Subscription-Cache: miss
```

方便调试。

---

# 14. Header 透传

订阅服务除了 Body 外，部分 Header 也很重要。

例如：

```text
subscription-userinfo
profile-update-interval
profile-web-page-url
content-type
```

其中：

```text
subscription-userinfo
```

可能包含：

```text
upload
download
total
expire
```

客户端可能通过这些信息显示：

```text
已用流量
剩余流量
套餐总量
到期时间
```

因此服务端应该建立允许透传的 Header 白名单。

例如：

```text
content-type
subscription-userinfo
profile-update-interval
profile-web-page-url
content-disposition
```

不要无条件透传所有 Header。

---

# 15. User-Agent

部分订阅提供商会根据 User-Agent 返回不同的订阅格式。

例如：

```text
clash
v2rayN
sing-box
Shadowrocket
```

因此支持两种模式。

## passthrough

客户端 User-Agent 原样发送给源服务器。

```text
v2rayN
  │
  │ User-Agent: v2rayN
  ▼
Relay
  │
  │ User-Agent: v2rayN
  ▼
Provider
```

配置：

```yaml
user_agent_mode: "passthrough"
```

---

## fixed

管理员指定固定 User-Agent。

例如：

```yaml
user_agent_mode: "fixed"
user_agent: "clash"
```

---

# 16. User-Agent 与缓存

如果使用：

```text
passthrough
```

不同 User-Agent 可能得到不同内容。

例如：

```text
Clash → YAML

v2rayN → Base64
```

因此后续可以考虑：

```text
subscription_id + user_agent
```

作为缓存 Key。

第一版可以采用简化方案：

```text
优先推荐每个订阅使用固定 User-Agent
```

或者根据几个常见客户端类型生成缓存。

---

# 17. 网络请求限制

访问原始订阅时，需要避免长时间阻塞。

默认：

```text
connect timeout: 5s

read timeout: 15s

max response size: 5MB
```

例如：

```yaml
defaults:
  connect_timeout: 5
  read_timeout: 15
  max_response_size: 5242880
```

订阅文件通常远小于 5 MB，因此足够使用。

---

# 18. SSRF 防护

由于服务器可以访问用户配置的 URL，因此必须考虑 SSRF。

第一版虽然只有管理员可以配置 URL，仍建议增加基本保护。

仅允许：

```text
http://
https://
```

禁止访问：

```text
localhost
127.0.0.0/8
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
169.254.0.0/16
::1
```

同时需要注意 DNS Rebinding。

不能只检查：

```text
URL 字符串
```

而应该：

```text
URL
 ↓
解析 hostname
 ↓
DNS 查询
 ↓
获得 IP
 ↓
检查是否属于禁止 IP
 ↓
允许请求
```

对于 HTTP Redirect，也需要重新验证新的目标地址。

---

# 19. 管理后台认证

第一版只支持一个管理员账户。

例如：

```yaml
server:
  admin_username: "admin"
```

密码不建议明文保存。

可以使用 bcrypt 保存 Hash。

管理员登录成功后，通过 Session Cookie 保持登录状态。

Session Cookie 建议：

```text
HttpOnly
Secure
SameSite=Lax
```

---

# 20. Token 生成

订阅访问 Token 可以使用 Python：

```python
import secrets

token = secrets.token_urlsafe(16)
```

例如：

```text
iwk32Ji_QYgB6nhTPW8cZw
```

Token 不应该：

```text
airport
clash
v2ray
123456
```

等容易猜测的内容。

---

# 21. 配置修改

后台修改订阅时：

```text
Web
 ↓
FastAPI
 ↓
校验数据
 ↓
修改 config.yaml
 ↓
重新加载配置
```

写文件时需要避免配置文件损坏。

建议流程：

```text
config.yaml
    │
    ▼
写入 config.yaml.tmp
    │
    ▼
fsync
    │
    ▼
rename
    │
    ▼
config.yaml
```

利用操作系统原子 rename 尽量保证配置安全。

---

# 22. 管理接口

第一版可以提供以下 API。

## 获取订阅列表

```http
GET /api/subscriptions
```

---

## 创建订阅

```http
POST /api/subscriptions
```

---

## 编辑订阅

```http
PUT /api/subscriptions/{id}
```

---

## 删除订阅

```http
DELETE /api/subscriptions/{id}
```

---

## 测试订阅

```http
POST /api/subscriptions/{id}/test
```

只测试源地址能否访问，不改变客户端配置。

---

## 刷新缓存

```http
POST /api/subscriptions/{id}/refresh
```

强制访问源地址，并覆盖缓存。

---

## 重新生成 Token

```http
POST /api/subscriptions/{id}/regenerate-token
```

调用后：

```text
旧中转地址失效
```

---

# 23. 状态显示

管理后台每个订阅至少显示：

```text
状态

最后成功时间

最后失败时间

最后错误信息

缓存状态

缓存大小
```

例如：

```text
机场 A

状态：
● 正常

最后成功：
2026-09-22 13:40:02

缓存：
Fresh

大小：
12.6 KB
```

失败：

```text
机场 B

状态：
● 源地址异常

最后成功：
2026-09-22 10:21:16

最后失败：
2026-09-22 13:42:01

错误：
HTTP 403 Forbidden

当前：
正在返回历史缓存
```

---

# 24. Docker 部署

Docker 容器只运行 Subscription Relay。

示例：

```yaml
services:

  subscription-relay:

    build: .

    container_name: subscription-relay

    restart: unless-stopped

    ports:
      - "8080:8080"

    volumes:
      - ./data:/app/data
```

配置和缓存全部位于：

```text
./data
```

因此容器删除后：

```text
配置
缓存
```

仍然存在。

---

# 25. HTTPS

Subscription Relay 本身可以只监听：

```text
0.0.0.0:8080
```

外部使用：

```text
Caddy
```

或者：

```text
Nginx
```

处理：

```text
HTTPS
域名
证书
反向代理
```

例如：

```text
https://sub.example.com
       │
       ▼
Caddy
       │
       ▼
127.0.0.1:8080
```

推荐管理后台和订阅地址全部使用 HTTPS。

---

# 26. 日志

第一版不需要复杂日志系统。

使用 Python logging 即可。

主要记录：

```text
启动
配置加载
订阅访问
源站获取成功
源站获取失败
缓存命中
Stale Cache
管理员登录
配置修改
```

但日志不要记录完整的：

```text
source_url
```

因为 URL 中可能包含 Token。

例如：

不要：

```text
GET https://provider.com/api?token=abcdefg
```

可以记录：

```text
Fetch subscription airport_a
```

---

# 27. 第一版页面

页面只需要三个主要界面。

## Login

```text
用户名

密码

[登录]
```

---

## Subscription List

首页显示所有订阅。

支持：

```text
复制
测试
刷新
编辑
删除
```

---

## Edit Subscription

字段：

```text
名称

原始订阅地址

Enabled

Cache TTL

User-Agent 模式

固定 User-Agent

Access Token
```

按钮：

```text
保存

随机生成 Token
```

---

# 28. MVP 功能列表

第一阶段必须实现：

- FastAPI 服务
- YAML 配置读取
- YAML 配置保存
- Pydantic 配置校验
- 管理员登录
- 订阅列表
- 新增订阅
- 编辑订阅
- 删除订阅
- 随机 Token
- `/s/{token}` 中转接口
- httpx 异步请求
- User-Agent 处理
- Header 白名单透传
- 文件缓存
- Cache TTL
- Stale Cache
- 手动刷新
- 测试源地址
- 一键复制中转地址
- 一键复制 curl
- 一键复制 wget
- Docker 部署
- 基础 SSRF 防护

---

# 29. 后续可选功能

MVP 稳定以后，可以逐步增加。

例如：

## 自动刷新

后台定期主动获取订阅。

```text
每 30 分钟
每 1 小时
每 6 小时
```

---

## 多客户端缓存

根据：

```text
User-Agent
```

分别缓存：

```text
Clash
v2rayN
sing-box
```

---

## 订阅历史

记录：

```text
成功
失败
响应时间
文件大小
```

例如：

```text
2026-09-20    OK
2026-09-21    OK
2026-09-22    403
```

---

## 订阅合并

未来可以支持：

```text
机场 A
+
机场 B
+
机场 C
```

生成统一订阅。

该功能不属于第一版。

---

# 30. 项目定位

Subscription Relay 不定位为 VPN，也不提供网络代理能力。

它本质上是：

```text
Subscription Management
+
HTTP Relay
+
Cache
+
Recovery
```

即：

> 一个通过网页管理 YAML 配置的轻量级订阅中转服务。服务端负责代替客户端访问原始订阅源，并通过稳定的中转地址提供订阅内容，同时提供缓存、故障回退、安全控制和快捷复制功能。

第一版本的核心原则是：

> 能解决问题，就不要增加不必要的复杂度。

因此整个 MVP：

```text
Python
+
FastAPI
+
YAML
+
文件缓存
+
简单网页
+
Docker
```

即可完成。