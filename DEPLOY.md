# 物业集团保安保洁智能审核平台 - 部署指南

## 架构概览

```
用户浏览器 → Nginx(80端口) → 前端静态文件
                         → /api/ 反代到 FastAPI 后端(8000端口)
                         → SQLite 数据库 + 文件存储
```

- 前端：React + Vite 构建，Nginx 托管静态文件
- 后端：Python FastAPI，Uvicorn 2 workers
- 数据库：SQLite（文件型，无需单独安装数据库服务）
- 文件存储：上传的 Excel、生成的 PDF 报告等

---

## 方式一：云服务器 Docker 部署（推荐）

### 1. 准备云服务器

推荐配置：2核 CPU / 4GB 内存 / 40GB 系统盘

常见云服务商：
- 阿里云 ECS
- 腾讯云 CVM
- 华为云 ECS
- AWS EC2
- Vultr / DigitalOcean

操作系统选择 Ubuntu 22.04 LTS 或 CentOS 8+

### 2. 安装 Docker

```bash
# Ubuntu
sudo apt update
sudo apt install -y docker.io docker-compose
sudo systemctl enable docker
sudo systemctl start docker

# CentOS
sudo yum install -y docker docker-compose
sudo systemctl enable docker
sudo systemctl start docker
```

### 3. 上传项目代码

将整个项目目录上传到服务器，例如 `/opt/audit-platform/`

```bash
# 使用 scp 上传（在本地执行）
scp -r ./* root@你的服务器IP:/opt/audit-platform/

# 或使用 git
cd /opt/audit-platform
git clone 你的仓库地址 .
```

### 4. 构建并启动

```bash
cd /opt/audit-platform

# 构建镜像并启动
docker-compose up -d --build

# 查看运行状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

### 5. 配置域名和 HTTPS（可选）

```bash
# 安装 certbot 获取免费 SSL 证书
sudo apt install -y certbot
sudo certbot certonly --standalone -d your-domain.com

# 在 docker-compose.yml 中取消 nginx-ssl 注释
# 配置证书路径后重启
docker-compose up -d
```

### 6. 防火墙配置

```bash
# 开放 80 端口
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp  # HTTPS
sudo ufw reload
```

在云服务商控制台的安全组中也需开放 80（和 443）端口。

---

## 方式二：手动部署（无 Docker）

### 1. 安装依赖

```bash
# Python 3.11+
sudo apt install -y python3 python3-pip nodejs npm

# 安装后端依赖
cd backend
pip install -r requirements.txt

# 构建前端
cd ../frontend
npm install
npm run build
```

### 2. 配置后端

```bash
export STORAGE_DIR=/opt/audit-platform/backend/storage
export DATABASE_PATH=/opt/audit-platform/backend/storage/audit_platform.db

cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

### 3. 用 Nginx 托管前端并反代 API

```nginx
server {
    listen 80;
    server_name your-domain.com;

    root /opt/audit-platform/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        client_max_body_size 50m;
    }
}
```

### 4. 用 systemd 管理后端服务

创建 `/etc/systemd/system/audit-platform.service`:

```ini
[Unit]
Description=Audit Platform Backend
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/audit-platform/backend
Environment=STORAGE_DIR=/opt/audit-platform/backend/storage
Environment=DATABASE_PATH=/opt/audit-platform/backend/storage/audit_platform.db
ExecStart=/usr/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable audit-platform
sudo systemctl start audit-platform
sudo systemctl restart nginx
```

---

## 数据备份

```bash
# 定期备份
crontab -e

# 每天凌晨3点备份
0 3 * * * cp -r /opt/audit-platform/backend/storage /opt/backup/$(date +\%Y\%m\%d)
```

---

## 常用运维命令

```bash
# 重启服务
docker-compose restart

# 更新代码后重新构建
docker-compose up -d --build

# 查看后端日志
docker-compose logs -f backend

# 进入后端容器调试
docker-compose exec backend bash

# 清理旧镜像
docker image prune -f
```
