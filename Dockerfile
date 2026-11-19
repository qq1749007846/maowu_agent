# ==========================================
# MaoWu Agent 生产级 Docker 镜像（全链路国内镜像源极速构建）
# ==========================================
FROM docker.m.daocloud.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# 1. 替换 Debian apt 源为清华大学开源镜像站（支持经典 sources.list 及 Debian 12 debian.sources 格式）
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources; \
        sed -i 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources; \
    fi && \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
        sed -i 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. 拷贝依赖清单（充分利用 Docker Layer 缓存）
COPY requirements.txt .

# 3. 使用清华源 + 阿里源双镜像并发加速安装 Python 依赖
RUN pip install --no-cache-dir -U pip wheel setuptools \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn && \
    pip install --no-cache-dir -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --extra-index-url https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
        --trusted-host mirrors.aliyun.com

# 4. 拷贝项目源码
COPY . .

# 创建数据与持久化目录
RUN mkdir -p /app/data/prompts

# 暴露服务端口
EXPOSE 8000

# 容器健康检查
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 启动命令
CMD ["python", "main.py"]
