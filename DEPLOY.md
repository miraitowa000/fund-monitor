# 部署说明

项目提供两种运行方式：

- 本地测试：直接 `flask run`
- 生产环境：使用 `docker compose`

当前项目只区分两个环境：

- `testing`
- `production`

配置加载规则如下：

- 本地测试默认读取 `.env.testing`
- `docker-compose.yml` 固定读取 `.env.production`

## 一、部署前准备

### 1. 安装基础依赖

服务器需要具备以下运行条件：

- Docker
- Docker Compose
- 可访问外网
- 可连接 MySQL

### 2. 创建生产数据库

应用启动时会自动创建缺失的表，但不会自动创建数据库本身。

请先在 MySQL 中手动创建数据库，例如：

```sql
CREATE DATABASE fund_monitor_production CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 3. 准备生产配置文件

在项目根目录创建 `.env.production`：

```env
APP_ENV=production
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=replace-with-production-password
DB_NAME=fund_monitor_production
DB_CHARSET=utf8mb4
```

说明：

- `APP_ENV` 必须是 `production`
- `DB_NAME` 必须是你已创建好的数据库名
- `.env.production` 已加入 `.gitignore`，不要提交到仓库

## 二、首次部署

### 1. 上传代码

将项目上传到服务器，例如：

```bash
cd /opt
git clone <your-repo> fund-monitor
cd /opt/fund-monitor
```

如果不是通过 Git，也可以直接上传项目目录。

### 2. 构建并启动

```bash
docker compose up -d --build
```

### 3. 查看状态

```bash
docker compose ps
```

### 4. 查看日志

```bash
docker compose logs -f
```

## 三、访问服务

当前 [docker-compose.yml](./docker-compose.yml) 将宿主机 `8065` 端口映射到容器 `5000` 端口，因此可直接访问：

```text
http://服务器IP:8065
```

健康检查地址：

```text
http://服务器IP:8065/health
```

## 四、更新发布

代码更新后，在项目目录执行：

```bash
docker compose up -d --build
```

如果只是重启：

```bash
docker compose restart
```

如果需要停止：

```bash
docker compose down
```

## 五、数据库初始化说明

应用启动时会调用数据库初始化逻辑：

- 自动创建缺失的表
- 不会自动创建数据库

因此生产部署时你只需要：

1. 手动创建数据库
2. 正确配置 `.env.production`
3. 启动容器

## 六、推荐接入方式

推荐生产环境使用：

- Docker 容器监听 `5000`
- 宿主机暴露 `8065`
- Nginx / OpenResty 反向代理到 `127.0.0.1:8065`

示例：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8065;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 七、排查命令

查看日志：

```bash
docker compose logs -f
```

进入容器：

```bash
docker exec -it fund-monitor /bin/bash
```

测试健康检查：

```bash
curl http://127.0.0.1:5000/health
curl http://127.0.0.1:8065/health
```

## 八、注意事项

- 项目依赖外部基金数据接口，服务器必须具备外网访问能力
- `.env.production` 不要提交到仓库
- 如果更换数据库配置，重新执行 `docker compose up -d --build`
- 生产环境建议通过 Nginx 配置域名和 HTTPS，不建议长期直接暴露应用端口
