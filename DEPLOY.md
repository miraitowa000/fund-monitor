# 项目部署说明

这是一个 Flask 应用，容器内通过 `gunicorn` 启动，默认监听 `5000` 端口。

## 项目概况

- 入口文件：`app.py`
- Web 框架：`Flask`
- 容器启动命令：`gunicorn -b 0.0.0.0:5000 app:app`
- 健康检查接口：`GET /health`
- 前端页面：`GET /`

## 推荐部署方式

服务器已经安装 Docker 时，优先使用 `docker compose` 部署。

## 1. 上传代码到服务器

把整个项目目录上传到服务器，例如：

```bash
/opt/fund-monitor
```

进入项目目录：

```bash
cd /opt/fund-monitor
```

## 2. 构建并启动

首次部署：

```bash
docker compose up -d --build
```

查看容器状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f
```

## 3. 访问服务

当前 `docker-compose.yml` 把服务器的 `8065` 端口映射到容器 `5000` 端口，所以可以直接访问：

```text
http://服务器IP:8065
```

如果你的 `OpenResty` 反向代理已经转发到 `127.0.0.1:8065`，这里不需要再改。

如果你想改成其他端口，对外改这里：

```yaml
ports:
  - "8065:5000"
```

然后重新启动：

```bash
docker compose up -d --build
```

## 4. 更新发布

以后代码更新后，进入项目目录重新执行：

```bash
docker compose up -d --build
```

如果只想重启：

```bash
docker compose restart
```

如果需要停止：

```bash
docker compose down
```

## 5. 防火墙和安全组

你至少要放行以下端口中的一个：

- `5000`，如果你直接对外暴露应用端口
- `8065`，如果你通过 `OpenResty/Nginx` 转发到该端口
- `80`，如果你改成 `80:5000`
- `443`，如果你后面接 `Nginx` 做 HTTPS

云服务器还需要同步检查安全组规则。

## 6. 推荐的线上接入方式

更稳妥的做法是：

- Docker 容器继续监听 `5000`
- 宿主机用 `Nginx` 监听 `80/443`
- `Nginx` 反向代理到 `127.0.0.1:5000`

这样更方便：

- 绑定域名
- 配置 HTTPS 证书
- 做访问日志和限流
- 后续平滑扩容

`OpenResty/Nginx` 示例：

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

## 7. 纯 Docker 命令方式

如果你不想用 `docker compose`，也可以直接运行：

```bash
docker build -t fund-monitor .
docker run -d \
  --name fund-monitor \
  --restart=always \
  -p 8065:5000 \
  fund-monitor
```

## 8. 排障命令

查看日志：

```bash
docker logs -f fund-monitor
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

## 9. 部署注意点

- 这个项目依赖外部财经数据接口，服务器需要具备正常外网访问能力
- `Dockerfile` 使用了清华 PyPI 镜像，如果你的服务器不在国内且下载异常，可以改回默认 PyPI
- 如果你准备挂域名，建议不要直接长期暴露 `5000`，而是配合 `Nginx + HTTPS`
