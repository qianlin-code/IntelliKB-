FROM python:3.11-slim
WORKDIR /app

# 配置 PyPI 国内镜像（中国大陆用户加速 pip 安装）
# 若不需要可删除此 ARG 或设置为空
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN if [ -n "${PIP_INDEX_URL}" ]; then \
      pip config set global.index-url ${PIP_INDEX_URL}; \
    fi

# 配置 Debian 国内镜像（中国大陆用户加速 apt 安装）
# 若不需要可删除此 ARG 或设置为空
ARG DEBIAN_MIRROR=mirrors.ustc.edu.cn
RUN if [ -n "${DEBIAN_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi

# 安装 curl（healthcheck 用），然后安装 Python 依赖
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 创建非 root 用户，UID/GID 与 docker-compose.yml 的 user: "1000:1000" 保持一致
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -d /home/appuser -m appuser

# 拷贝应用代码并切换用户
COPY --chown=appuser:appuser . .
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
