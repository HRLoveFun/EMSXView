# EMSX Trading Platform

> **开箱即用的完整生产环境部署方案**  
> Bloomberg EMSX 订单管理工具 · React 前端 + FastAPI 后端 · Docker 一键部署

---

## 目录结构

```
EMSX/
├── app/                       # 前端 React + Vite + shadcn/ui
│   ├── src/
│   │   ├── sections/          # 页面区块组件
│   │   ├── services/api.ts    # API 客户端（支持 mock / 真实后端自动切换）
│   │   ├── types/             # TypeScript 类型定义
│   │   └── components/ui/     # 40+ shadcn/ui 组件
│   ├── Dockerfile             # 多阶段构建：Node 打包 → Nginx 服务
│   └── .env.example           # 前端环境变量模板
│
├── emsx-backend/              # 后端 + 基础设施配置
│   ├── backend/
│   │   ├── main.py            # FastAPI 应用（订单 API、WebSocket、健康检查）
│   │   ├── auth.py            # JWT 认证模块
│   │   └── Dockerfile         # Python 多阶段构建
│   ├── config/
│   │   ├── nginx.conf         # Nginx 反代配置（/api, /ws → backend:3000）
│   │   ├── nginx-host.conf    # Linux host-network 变体
│   │   ├── prometheus.yml     # Prometheus 抓取配置
│   │   └── grafana/           # Grafana datasource & dashboard 预配置
│   ├── scripts/
│   │   ├── deploy.sh          # Linux/macOS 部署脚本
│   │   └── setup-windows.ps1  # Windows 部署脚本
│   ├── docker-compose.yml     # 生产环境编排（bridge 网络，Windows/macOS）
│   ├── docker-compose.host.yml# Linux host-network 变体
│   └── .env.example           # 后端环境变量模板
│
└── README.md                  # 本文件
```

---

## 快速开始（5 分钟部署）

### 前置条件

| 组件 | 说明 |
|---|---|
| **Docker Desktop** ≥ 4.x | Windows / macOS |
| **Docker Engine** ≥ 24 + Compose v2 | Linux |
| **Bloomberg Terminal** | 已登录；在 Terminal 输入 `API<GO>` 确认 API 已启用 |

### 第一步：配置环境变量

```bash
cd emsx-backend
cp .env.example .env
```

**必须修改（最低限度）：**

```env
# 生成强密钥：openssl rand -hex 32
JWT_SECRET=<your-random-64-char-string>

# 允许登录的交易员用户名（逗号分隔）
ALLOWED_TRADERS=trader1,trader2
```

### 第二步：一键启动

**Windows（PowerShell 管理员）：**
```powershell
cd emsx-backend\scripts
.\setup-windows.ps1      # 检查环境、构建镜像
cd ..
docker compose up -d     # 启动所有服务
```

**Linux / macOS：**
```bash
cd emsx-backend
chmod +x scripts/deploy.sh
./scripts/deploy.sh install   # 检查环境、构建镜像
./scripts/deploy.sh start     # 启动所有服务
```

**Linux（Bloomberg 在宿主机，使用 host 网络模式）：**
```bash
docker compose -f docker-compose.host.yml up -d
```

### 第三步：验证

| 地址 | 说明 |
|---|---|
| http://localhost | 前端交易界面 |
| http://localhost/api/health | 后端健康检查（JSON） |
| http://localhost/api/docs | FastAPI 交互式 API 文档 |

---

## 服务架构

```
浏览器
  │  :80
  ▼
Nginx (emsx-frontend)
  ├── /          → 前端静态资源（React SPA）
  ├── /api/*     → 反代至 backend:3000/
  └── /ws/*      → WebSocket 升级 → backend:3000/
                         │
                   FastAPI (emsx-backend)
                         │
                   Bloomberg API :8194
                   （运行在宿主机）
```

---

## 认证

使用 JWT Bearer Token。所有 `/api/*` 接口（`/api/health` 除外）均需认证。

```bash
# 登录获取 Token
curl -X POST http://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"trader1","password":"password"}'

# 携带 Token 请求
curl http://localhost/api/orders \
  -H "Authorization: Bearer <token>"
```

**内置演示账户（生产环境请更改密码）：**

| 用户名 | 密码 | 角色 |
|---|---|---|
| trader1 | password | trader |
| trader2 | password | trader |
| admin | password | admin |

要修改密码，使用 Python 生成 bcrypt hash，然后更新 `emsx-backend/backend/auth.py` 中的 `DEMO_USERS`：

```python
from passlib.context import CryptContext
pwd = CryptContext(schemes=["bcrypt"])
print(pwd.hash("your-new-password"))
```

---

## API 端点

| 端点 | 方法 | 认证 | 说明 |
|---|---|---|---|
| `/api/health` | GET | 否 | 健康检查 |
| `/api/docs` | GET | 否 | Swagger UI |
| `/api/auth/login` | POST | 否 | 获取 JWT Token |
| `/api/orders` | GET | 是 | 获取订单（支持过滤参数） |
| `/api/orders/refresh` | GET | 是 | 强制从 Bloomberg 刷新 |
| `/api/orders/batch-update` | POST | 是 | 批量修改订单 |
| `/api/orders/{id}/cancel` | POST | 是 | 取消单个订单 |
| `/api/connection` | GET | 是 | Bloomberg 连接状态 |
| `/api/connection/reconnect` | POST | 是 | 重连 Bloomberg |
| `/ws/orders` | WebSocket | 否 | 实时订单推送 |

---

## 环境变量说明

完整列表见 [emsx-backend/.env.example](emsx-backend/.env.example)。关键项：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `BLOOMBERG_HOST` | `host.docker.internal` | Bloomberg Terminal 地址 |
| `BLOOMBERG_PORT` | `8194` | Bloomberg API 端口 |
| `JWT_SECRET` | **必须修改** | JWT 签名密钥 |
| `ALLOWED_TRADERS` | 空（允许所有） | 白名单用户 |
| `MAX_BATCH_SIZE` | `100` | 批量更新上限 |
| `FRONTEND_PORT` | `80` | 前端对外端口 |

---

## 前端开发模式（无需后端）

前端默认在没有 `VITE_API_URL` 时自动使用 **mock 数据**，无需 Docker 即可开发：

```bash
cd app
cp .env.example .env   # 保持 VITE_API_URL 为空
npm install
npm run dev            # http://localhost:5173
```

连接真实后端时设置：
```env
# app/.env
VITE_API_URL=http://localhost:3000
```

---

## 常用运维命令

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f backend
docker compose logs -f frontend

# 重启单个服务
docker compose restart backend

# 重新构建并启动（代码有更新时）
docker compose build --no-cache && docker compose up -d

# 停止所有服务
docker compose down

# 停止并清除数据卷（慎用）
docker compose down -v
```

---

## 监控（可选）

启用 Prometheus + Grafana：

```bash
docker compose --profile monitoring up -d
```

| 地址 | 说明 |
|---|---|
| http://localhost:9090 | Prometheus |
| http://localhost:3001 | Grafana（admin / 见 .env） |

---

## 生产部署检查清单

- [ ] `JWT_SECRET` 已设置为强随机字符串（≥ 32字节）
- [ ] `GRAFANA_PASSWORD` 已修改
- [ ] `ALLOWED_TRADERS` 已配置白名单
- [ ] 演示账户密码已修改（`auth.py` → `DEMO_USERS`）
- [ ] 防火墙：仅开放端口 80（或 443），关闭 3000 对外暴露
- [ ] Bloomberg API 已在 Terminal 启用（`API<GO>`）
- [ ] 已测试 `http://localhost/api/health` 返回 `connected`
- [ ] 日志轮转已配置（docker logging `max-file` 已设置）

---

## 故障排除

### Bloomberg 连接失败

```bash
# 检查 Bloomberg 端口
# Windows: 在终端（非 Docker 内）
Test-NetConnection -ComputerName localhost -Port 8194

# Linux/macOS
nc -zv localhost 8194
```

1. 确认 Bloomberg Terminal 已登录
2. 在 Bloomberg 输入 `API<GO>` 确认 API 已启用
3. Windows 防火墙 → 允许 Docker 访问端口 8194

### Linux 无法连接 Bloomberg

使用 host 网络模式：
```bash
docker compose -f docker-compose.host.yml up -d
```

### 端口冲突

修改 `.env`：
```env
FRONTEND_PORT=8080
API_PORT=3001
```

### 查看详细错误

```bash
docker compose logs -f backend
tail -f emsx-backend/logs/emsx_api.log   # 本地日志卷
```

---

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 19, Vite 7, TypeScript, TailwindCSS 3, shadcn/ui, Recharts |
| 后端 | Python 3.11, FastAPI, Pydantic v2, python-jose, passlib |
| Bloomberg | blpapi 3.23 (EMSX beta service) |
| 服务发现 | Docker Compose bridge network |
| 反代 & 静态 | Nginx 1.27-alpine |
| 缓存 | Redis 7-alpine |
| 监控 | Prometheus + Grafana |
