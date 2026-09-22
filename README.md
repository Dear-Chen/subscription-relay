# Subscription Relay

轻量级订阅中转与管理服务。部署在境外服务器上，统一管理 Clash / v2rayN / Mihomo / sing-box 等客户端的订阅地址：服务端代替客户端访问原始订阅源，通过稳定的中转地址返回订阅内容，并提供缓存容灾与快捷复制功能。

## 功能

- 订阅管理（新增 / 编辑 / 删除 / 启停），全部配置保存在 `data/config.yaml`
- `/s/{token}` 订阅中转，随机 Token 作为访问凭证，支持一键重新生成
- 文件缓存（`data/cache/`），TTL 控制 + 源站故障时自动回退到最近一次成功内容（Stale Cache）
- Header 白名单透传（`content-type`、`subscription-userinfo`、`profile-update-interval`、`profile-web-page-url`、`content-disposition`）
- User-Agent 两种模式：`passthrough`（透传客户端 UA）/ `fixed`（固定 UA）
- 管理后台：一键复制中转地址 / 原始地址 / curl / wget，测试源地址，手动刷新缓存
- 基础 SSRF 防护：仅允许 http/https，禁止内网/保留地址，逐跳校验重定向目标
- 无数据库、无 Redis，YAML 配置 + 文件缓存 + Docker 一键部署

## 快速开始

### 本地运行

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Docker

```bash
docker compose up -d --build
```

配置和缓存全部位于 `./data`，容器删除后数据保留。

### 使用预构建镜像（Docker Hub）

GitHub Actions 会自动构建多架构镜像（linux/amd64、linux/arm64）并推送到 Docker Hub：

```bash
docker run -d --name subscription-relay \
  -p 8080:8080 \
  -v ./data:/app/data \
  --restart unless-stopped \
  dearchen/subscription-relay:latest
```

标签说明：`latest` 为主分支最新构建；`v0.1.0` 等语义化标签对应 git tag；另有 7 位 commit SHA 标签。首次启动前把 `data/config.example.yaml` 复制为 `data/config.yaml` 并按需修改。

## CI/CD

推送 `main`/`master` 分支或推送 `v*` 标签（如 `v0.1.0`）时，`.github/workflows/docker.yml` 自动构建并推送镜像到 `dearchen/subscription-relay`。

使用前需要在 GitHub 仓库 **Settings → Secrets and variables → Actions** 配置两个 Secrets：

| Secret | 说明 |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub 用户名（`dearchen`） |
| `DOCKERHUB_TOKEN` | Docker Hub 访问令牌（hub.docker.com → Account Settings → Security → New Access Token） |

发布新版本：在本地打 tag 并推送即可自动出镜像：

```bash
git tag v0.1.0
git push origin v0.1.0
```

## 首次启动

- 默认登录账号密码为 `admin` / `admin`（来自 `config.yaml` 的 `server.admin_password` 明文字段，该字段优先于 `admin_password_hash`，启动时仅在内存中计算 bcrypt 哈希）
- 若 `admin_password` 与 `admin_password_hash` 均为空：读取环境变量 `SUBRELAY_ADMIN_PASSWORD`，若也未设置则生成随机密码并打印到日志
- `session_secret` 为空时自动生成并写回
- 登录后访问管理后台 `/admin`

## 配置说明

见 `data/config.yaml` 内注释。订阅级字段可覆盖全局默认值（`cache_ttl`、`user_agent_mode`、`user_agent`）。

## 中转地址

管理后台复制的中转地址格式：

```text
https://sub.example.com/s/{access_token}
```

其中 `access_token` 即访问凭证，重新生成后旧地址立即失效。

## 响应头

调试时可通过以下响应头判断缓存状态：

```text
X-Subscription-Cache: hit | miss | stale
```

## HTTPS

服务本身只监听 HTTP（`0.0.0.0:8080`），生产环境建议在前面挂 Caddy / Nginx 处理证书与反向代理，并把 `server.public_base_url` 设置为 `https://` 开头的地址。

## 管理 API

所有接口需要管理员登录（Session Cookie）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/subscriptions` | 订阅列表（含运行状态） |
| POST | `/api/subscriptions` | 创建订阅 |
| PUT | `/api/subscriptions/{id}` | 编辑订阅 |
| DELETE | `/api/subscriptions/{id}` | 删除订阅（连同缓存与状态） |
| POST | `/api/subscriptions/{id}/test` | 测试源地址（不写缓存） |
| POST | `/api/subscriptions/{id}/refresh` | 强制刷新缓存 |
| POST | `/api/subscriptions/{id}/regenerate-token` | 重新生成 Token |

## 环境变量

| 变量 | 说明 |
|---|---|
| `SUBRELAY_DATA_DIR` | 数据目录（config.yaml / cache / state.yaml），默认 `./data` |
| `SUBRELAY_ADMIN_PASSWORD` | 首次启动时的管理员明文密码（仅当 `admin_password` 与 `admin_password_hash` 均为空时生效） |

## 日志

默认 INFO 级别，记录启动、配置加载/修改、订阅访问、缓存命中/回退、管理员登录等。为安全起见，日志只记录订阅 ID，不会输出包含 Token 的完整 `source_url`。
