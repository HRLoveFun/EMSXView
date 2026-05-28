# EMSXView Trading API - 快速开始指南

## ⚡ 5分钟快速部署

### 步骤 1: 准备环境

确保已安装：
- [Docker Desktop](https://www.docker.com/products/docker-desktop) (Windows/Mac)
- Bloomberg Terminal 已运行并登录

### 步骤 2: 配置

```bash
# 1. 复制环境配置模板
cp .env.example .env

# 2. 编辑 .env 文件，设置关键配置
# Windows/Mac 用户通常不需要修改
# Linux 用户需要设置 BLOOMBERG_HOST=你的主机IP
```

### 步骤 3: 部署

**Windows (PowerShell 管理员):**
```powershell
.\scripts\setup-windows.ps1
```

**Linux/Mac:**
```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh install
./scripts/deploy.sh start
```

### 步骤 4: 部署前端

将之前构建的前端文件复制到 `frontend/dist/`:

```bash
# 从前端项目复制构建文件
cp -r /path/to/emsx-frontend/dist/* frontend/dist/

# 重启服务
./scripts/deploy.sh restart
```

### 步骤 5: 验证

打开浏览器访问：
- **前端界面**: http://localhost
- **API 健康检查**: http://localhost:3000/api/health

## 🔧 常用命令

```bash
# 查看状态
./scripts/deploy.sh status

# 查看日志
./scripts/deploy.sh logs
./scripts/deploy.sh logs backend

# 停止服务
./scripts/deploy.sh stop

# 重启服务
./scripts/deploy.sh restart

# 更新配置后重新部署
./scripts/deploy.sh update
```

## 🐳 Docker 命令

```bash
# 启动
docker-compose up -d

# 停止
docker-compose down

# 查看日志
docker-compose logs -f

# 重启后端
docker-compose restart backend
```

## ⚠️ 常见问题

### Bloomberg 连接失败

**症状**: API 返回 "Bloomberg not connected"

**解决**:
1. 确认 Bloomberg Terminal 已登录
2. 确认 API 访问已启用 (在 Terminal 输入 `API<GO>`)
3. 检查防火墙设置

### Linux 网络问题

**症状**: 无法连接到 Bloomberg

**解决**:
```bash
# 使用 host 网络模式
docker-compose -f docker-compose.host.yml up -d
```

### 端口被占用

**症状**: "port is already allocated"

**解决**:
```bash
# 修改 .env 中的端口配置
API_PORT=3001
FRONTEND_PORT=8080
```

## 📞 获取帮助

查看完整文档: [README.md](README.md)

Bloomberg API 支持: 联系您的 Bloomberg 客户经理
