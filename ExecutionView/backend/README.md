# EMSXView Trading API - Production Deployment

开箱即用的彭博EMSX交易API后端服务，用于生产环境部署。

## 📋 系统要求

### 必需组件
- **Docker Desktop** (Windows/Mac) 或 **Docker Engine** (Linux)
- **Docker Compose** v2.0+
- **Bloomberg Terminal** (已安装并登录)
- **Bloomberg API** (blpapi) 访问权限

### 网络要求
- Bloomberg Terminal 端口 `8194` 可访问
- 防火墙允许 Docker 容器访问主机网络

## 🚀 快速开始

### 1. 下载并解压

```bash
cd /path/to/emsx-backend
```

### 2. 配置环境变量

```bash
# 复制环境模板
cp .env.example .env

# 编辑配置
nano .env  # 或 notepad .env (Windows)
```

**关键配置项：**

```env
# Bloomberg 终端配置
BLOOMBERG_HOST=host.docker.internal  # Windows/Mac
# BLOOMBERG_HOST=192.168.1.100      # Linux (使用主机IP)
BLOOMBERG_PORT=8194

# 安全设置
JWT_SECRET=your-super-secret-key-change-this
ALLOWED_TRADERS=trader1,trader2

# 交易设置
MAX_BATCH_SIZE=100
```

### 3. 运行部署脚本

**Linux/Mac:**
```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh install
./scripts/deploy.sh start
```

**Windows (PowerShell 管理员):**
```powershell
.\scripts\setup-windows.ps1
```

### 4. 部署前端

将前端构建文件复制到 `frontend/dist/` 目录：

```bash
# 假设前端项目已构建
cp -r /path/to/frontend/dist/* frontend/dist/
```

### 5. 验证部署

```bash
# 检查服务状态
./scripts/deploy.sh status

# 查看日志
./scripts/deploy.sh logs

# 测试API
curl http://localhost:3000/api/health
```

## 📁 项目结构

```
emsx-backend/
├── backend/
│   ├── main.py              # FastAPI 主应用
│   ├── auth.py              # 认证模块
│   ├── requirements.txt     # Python 依赖
│   └── Dockerfile           # Docker 构建文件
├── config/
│   ├── nginx.conf           # Nginx 反向代理配置
│   └── prometheus.yml       # 监控配置
├── scripts/
│   ├── deploy.sh            # Linux/Mac 部署脚本
│   └── setup-windows.ps1    # Windows 部署脚本
├── frontend/
│   └── dist/                # 前端构建文件
├── logs/                    # 日志目录
├── docker-compose.yml       # Docker Compose 配置
├── .env.example             # 环境变量模板
└── README.md                # 本文件
```

## 🔧 配置详解

### Bloomberg 连接

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BLOOMBERG_HOST` | Bloomberg 终端主机 | `host.docker.internal` |
| `BLOOMBERG_PORT` | Bloomberg API 端口 | `8194` |
| `BLOOMBERG_TIMEOUT` | 请求超时(毫秒) | `30000` |

**Windows/Mac:** 使用 `host.docker.internal`

**Linux:** 使用主机 IP 地址或配置 `extra_hosts`

### 安全设置

| 变量 | 说明 | 示例 |
|------|------|------|
| `JWT_SECRET` | JWT 签名密钥 | `openssl rand -hex 32` |
| `JWT_EXPIRE_MINUTES` | Token 有效期(分钟) | `480` |
| `ALLOWED_TRADERS` | 允许的交易员列表 | `trader1,trader2` |

### 网络设置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `API_PORT` | 后端API端口 | `3000` |
| `FRONTEND_PORT` | 前端端口 | `80` |
| `ALLOWED_ORIGINS` | CORS 允许来源 | `http://localhost` |

## 🐳 Docker 命令

```bash
# 启动所有服务
docker-compose up -d

# 停止服务
docker-compose down

# 查看日志
docker-compose logs -f backend
docker-compose logs -f frontend

# 重启服务
docker-compose restart backend

# 重建镜像
docker-compose build --no-cache

# 进入容器调试
docker-compose exec backend sh
```

## 🔌 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/orders` | GET | 获取订单列表 |
| `/api/orders/batch-update` | POST | 批量修改订单 |
| `/api/orders/{id}/cancel` | POST | 取消单个订单 |
| `/api/connection/reconnect` | POST | 重新连接 Bloomberg |
| `/ws/orders` | WebSocket | 实时订单更新 |

### 认证

所有 API 端点需要 Bearer Token：

```bash
# 获取 Token (示例)
curl -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"trader1","password":"password"}'

# 使用 Token
curl http://localhost:3000/api/orders \
  -H "Authorization: Bearer <your-token>"
```

## 📊 监控 (可选)

启用监控栈：

```bash
docker-compose --profile monitoring up -d
```

访问地址：
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3001 (admin/admin)

## 🐛 故障排除

### Bloomberg 连接失败

```bash
# 测试 Bloomberg 端口连通性
telnet localhost 8194

# 检查 Bloomberg 终端状态
# 确保终端已登录且 API 已启用
```

### Docker 网络问题 (Linux)

```bash
# 查看主机IP
ip addr show

# 更新 .env
BLOOMBERG_HOST=192.168.1.100  # 替换为实际IP

# 或使用 host 网络模式
docker-compose -f docker-compose.host.yml up -d
```

### 权限问题

```bash
# 修复日志目录权限
sudo chown -R $USER:$USER logs/
chmod +x scripts/deploy.sh
```

### 查看详细日志

```bash
# 后端日志
docker-compose logs -f backend

# 系统日志
tail -f logs/emsx_api.log
```

## 🔒 生产环境检查清单

- [ ] 修改 `JWT_SECRET` 为强密码
- [ ] 配置 `ALLOWED_TRADERS` 限制访问
- [ ] 启用 HTTPS (配置 SSL 证书)
- [ ] 配置防火墙规则
- [ ] 设置日志轮转
- [ ] 启用审计日志
- [ ] 配置监控告警
- [ ] 测试灾难恢复流程

## 📞 支持

### Bloomberg API 文档
- [Bloomberg API Developer Guide](https://developer.bloomberg.com/)
- [EMSX API Reference](https://data.bloomberglp.com/professional/sites/10/EMSX_API_User_Guide.pdf)

### 常见问题

**Q: 如何获取 Bloomberg API 访问权限？**  
A: 联系您的 Bloomberg 客户经理申请 EMSX API 许可。

**Q: 支持哪些订单类型？**  
A: LIMIT, MARKET, STOP, STOP_LIMIT, TRAILING_STOP

**Q: 批量更新最多支持多少订单？**  
A: 默认 100 个，可通过 `MAX_BATCH_SIZE` 配置。

## 📄 许可证

内部使用 - 交易技术部

---

**版本**: 1.0.0  
**更新日期**: 2024
