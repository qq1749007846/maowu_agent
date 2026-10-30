# ==========================================
# MaoWu Agent 生产级 Docker 镜像构建文件
# ==========================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# 安装必要的系统运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖清单，充分利用 Docker 缓存层
COPY requirements.txt .

# 优先使用国内清华源或官方源安装依赖
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir -r requirements.txt \
    || pip install --no-cache-dir -r requirements.txt

# 拷贝项目源码
COPY . .

# 创建数据与持久化目录
RUN mkdir -p /app/data/prompts

# 暴露 FastAPI 服务端口
EXPOSE 8000

# 容器健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 启动命令
CMD ["python", "main.py"]
