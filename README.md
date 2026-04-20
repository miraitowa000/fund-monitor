# Fund Monitor

一个基于 Flask 的基金实时监控看板，支持：

- 自选基金持久化
- 分组管理
- 基金详情
- 持仓明细
- 历史净值
- 市场指数概览
- 移动端适配
- MySQL 持久化
- Docker 部署

## 技术栈

- Python 3.9+
- Flask
- SQLAlchemy
- PyMySQL
- Requests
- BeautifulSoup4
- AkShare
- Vue 3
- ECharts
- Bootstrap 5

## 项目结构

```text
fund-monitor/
├── app.py
├── core/
├── services/
├── static/
├── templates/
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.testing.example
├── .env.production.example
└── DEPLOY.md
```

## 环境区分

当前项目只区分两个环境：

- `testing`
- `production`

配置加载规则：

- 本地测试默认使用 `.env.testing`
- Docker Compose 生产部署固定使用 `.env.production`

## 本地测试

### 1. 创建虚拟环境

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 准备测试配置

参考 [.env.testing.example](./.env.testing.example) 创建 `.env.testing`：

```env
APP_ENV=testing
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=abcd.1234
DB_NAME=fund_monitor_testing
DB_CHARSET=utf8mb4
```

注意：

- 数据库需要你先手动创建
- 应用启动时只会自动创建表，不会自动创建数据库

### 4. 启动项目

```bash
flask run --host=0.0.0.0 --port=5000
```

访问地址：

```text
http://127.0.0.1:5000
```

## 生产部署

生产环境使用 Docker Compose。

### 1. 准备生产配置

参考 [.env.production.example](./.env.production.example) 创建 `.env.production`：

```env
APP_ENV=production
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=replace-with-production-password
DB_NAME=fund_monitor_production
DB_CHARSET=utf8mb4
```

### 2. 启动容器

```bash
docker compose up -d --build
```

默认访问地址：

```text
http://127.0.0.1:8065
```

停止服务：

```bash
docker compose down
```

更多生产部署细节见 [DEPLOY.md](./DEPLOY.md)。

## 数据库说明

项目当前使用 MySQL 持久化以下数据：

- 匿名用户
- 基金分组
- 用户关注基金

应用启动时会自动执行建表逻辑，但你仍然需要先手动创建数据库。

## API

### 健康检查

```http
GET /health
```

### 批量查询基金

```http
POST /api/funds
Content-Type: application/json
```

请求体示例：

```json
{
  "codes": ["161725", "002190", "003095"]
}
```

### 查询指数

```http
GET /api/indexes
```

### 查询基金详情

```http
GET /api/fund/<fund_code>
```

### 查询当前用户基金与分组

```http
GET /api/user/funds-meta
X-Client-Id: <client_id>
```

### 初始化迁移本地基金

```http
POST /api/user/bootstrap
X-Client-Id: <client_id>
Content-Type: application/json
```

### 创建分组

```http
POST /api/user/groups
X-Client-Id: <client_id>
Content-Type: application/json
```

### 添加或更新基金分组

```http
POST /api/user/funds
X-Client-Id: <client_id>
Content-Type: application/json
```

### 移动基金分组

```http
PUT /api/user/funds/<fund_code>/group
X-Client-Id: <client_id>
Content-Type: application/json
```

## 开发说明

- 后端入口：[app.py](./app.py)
- 配置入口：[core/settings.py](./core/settings.py)
- 前端页面入口：[templates/index.html](./templates/index.html)
