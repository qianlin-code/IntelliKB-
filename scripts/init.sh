#!/usr/bin/env bash
# IntelliKB 一键初始化脚本
# 用法: bash scripts/init.sh

set -e

echo "========================================="
echo "  IntelliKB 一键初始化"
echo "========================================="
echo ""

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── 1. 等待服务就绪 ──
echo -e "${YELLOW}[1/4]${NC} 等待服务健康检查通过..."
max_retries=30
retry=0
while [ $retry -lt $max_retries ]; do
    if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓${NC} App 服务已就绪"
        break
    fi
    retry=$((retry + 1))
    echo "  等待中... ($retry/$max_retries)"
    sleep 2
done
if [ $retry -ge $max_retries ]; then
    echo -e "${RED}  ✗${NC} 服务启动超时，请检查: docker compose logs app"
    exit 1
fi

# ── 2. 数据库迁移 ──
echo -e "${YELLOW}[2/4]${NC} 运行数据库迁移..."
if docker compose exec -T app alembic upgrade head; then
    echo -e "${GREEN}  ✓${NC} 数据库迁移完成"
else
    echo -e "${RED}  ✗${NC} 迁移失败，请检查数据库连接"
    exit 1
fi

# ── 3. 下载 Reranker 模型（可选，首次需要网络）──
echo -e "${YELLOW}[3/4]${NC} 下载 Reranker 模型..."
echo "  提示: 若已离线部署模型到 reranker_models/ 目录，可跳过此步"
read -p "  是否下载 Reranker 模型? 首次需要网络 (y/N): " download_model
if [ "$download_model" = "y" ] || [ "$download_model" = "Y" ]; then
    docker compose exec -T app python scripts/download_reranker.py || \
        echo -e "${YELLOW}  ⚠${NC} 模型下载失败，Reranker 将自动降级"
else
    echo "  已跳过模型下载"
fi

# ── 4. 创建超级管理员 ──
echo -e "${YELLOW}[4/4]${NC} 创建超级管理员账户..."
read -p "  用户名 (默认 admin): " admin_user
admin_user=${admin_user:-admin}
read -s -p "  密码 (至少8位，含字母+数字): " admin_pass
echo ""

if [ -z "$admin_pass" ]; then
    echo -e "${RED}  ✗${NC} 密码不能为空，请手动创建管理员:"
    echo "    docker compose exec app python -c \"...\""
    echo "  参考 docs/deployment.md #首次初始化"
else
    # 调用 Python 创建 superadmin
    docker compose exec -T app python -c "
import asyncio
from app.core.database import async_session_factory
from app.services.auth_service import AuthService

async def main():
    async with async_session_factory() as db:
        service = AuthService(db)
        try:
            user = await service.register('$admin_user', '$admin_pass', '${admin_user}@intellikb.local')
            user.system_role = 'superadmin'
            await db.commit()
            print(f'Superadmin created: id={user.id}, username={user.username}')
        except Exception as e:
            if '已存在' in str(e) or 'Duplicate' in str(e):
                print(f'用户 $admin_user 已存在，跳过创建')
            else:
                raise

asyncio.run(main())
" && echo -e "${GREEN}  ✓${NC} 超级管理员创建完成" || \
    echo -e "${YELLOW}  ⚠${NC} 创建失败，请手动执行"
fi

echo ""
echo "========================================="
echo -e "${GREEN}  初始化完成!${NC}"
echo "========================================="
echo ""
echo "  前端:      http://localhost:5173"
echo "  API 文档:  http://localhost:8000/docs"
echo "  管理后台:  http://localhost:5173/admin"
echo ""
echo "  登录账户: $admin_user"
echo "  请立即登录并修改密码。"
echo ""
