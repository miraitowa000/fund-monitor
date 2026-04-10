# Fund Monitor

一个基于 Flask 的基金实时监控看板，支持按基金代码添加自选、查看估值涨跌、查看持仓和近 30 天净值走势，并展示主要指数行情。

## 功能

- 基金实时估值查询
- 自选基金列表管理
- 基金详情弹窗
- 持仓明细展示
- 近 30 天净值走势
- 上证、深证、创业板、科创 50、北证 50 指数行情
- 自动刷新
- 移动端适配
- Docker 部署支持

## 技术栈

- Python 3.9
- Flask
- Requests
- BeautifulSoup4
- AkShare
- Vue 3
- ECharts
- Bootstrap 5

## 项目结构

```text
fund-monitor/
├─ app.py
├─ requirements.txt
├─ Dockerfile
├─ docker-compose.yml
├─ templates/
│  └─ index.html
└─ static/
```

## 本地运行

1. 创建并激活虚拟环境

```bash
python -m venv .venv
```

Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 启动项目

```bash
python app.py
```

4. 打开浏览器访问

```text
http://127.0.0.1:5000
```

## Docker 运行

### 使用 Docker Compose

```bash
docker compose up -d --build
```

默认映射端口：

```text
http://127.0.0.1:8065
```

停止服务：

```bash
docker compose down
```

### 使用 Docker 命令

```bash
docker build -t fund-monitor .
docker run -d --name fund-monitor --restart=always -p 8065:5000 fund-monitor
```

## API

### 健康检查

```http
GET /health
```

返回：

```text
ok
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

例如：

```http
GET /api/fund/161725
```

## 数据来源说明

项目依赖第三方公开数据接口，包括但不限于：

- 东方财富
- 新浪行情
- AkShare

第三方接口出现限流、超时、结构变更时，页面可能出现空数据、延迟或短暂异常。

## 部署说明

仓库已包含以下部署文件：

- [Dockerfile](./Dockerfile)
- [docker-compose.yml](./docker-compose.yml)
- [DEPLOY.md](./DEPLOY.md)

如果你准备部署到云服务器，优先使用 `docker compose`。

## 开发说明

- 后端入口文件是 [app.py](./app.py)
- 前端页面是 [templates/index.html](./templates/index.html)
- 当前没有拆分前后端，是一个轻量单体应用

## License

暂未声明。如需开源许可，建议补充 `MIT` License。
