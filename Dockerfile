# 使用官方 Python 轻量级镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装依赖
# 使用清华源加速安装（可选）
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 还需要安装 gunicorn 用于生产环境部署
RUN pip install gunicorn

# 复制当前目录下的所有文件到工作目录
COPY . .

# 暴露端口
EXPOSE 5000

CMD ["gunicorn", "-w", "2", "--threads", "4", "--timeout", "90", "--graceful-timeout", "90", "-b", "0.0.0.0:5000", "app:app"]
