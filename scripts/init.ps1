# IntelliKB 一键初始化脚本 (Windows PowerShell)
# 用法: powershell -File scripts/init.ps1

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  IntelliKB 一键初始化" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. 等待服务就绪 ──
Write-Host "[1/4] 等待服务健康检查通过..." -ForegroundColor Yellow
$maxRetries = 30
$retry = 0
while ($retry -lt $maxRetries) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Write-Host "  ✓ App 服务已就绪" -ForegroundColor Green
            break
        }
    } catch {
        # 继续等待
    }
    $retry++
    Write-Host "  等待中... ($retry/$maxRetries)"
    Start-Sleep -Seconds 2
}
if ($retry -ge $maxRetries) {
    Write-Host "  ✗ 服务启动超时，请检查: docker compose logs app" -ForegroundColor Red
    exit 1
}

# ── 2. 数据库迁移 ──
Write-Host "[2/4] 运行数据库迁移..." -ForegroundColor Yellow
docker compose exec -T app alembic upgrade head
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ 数据库迁移完成" -ForegroundColor Green
} else {
    Write-Host "  ✗ 迁移失败" -ForegroundColor Red
    exit 1
}

# ── 3. 下载 Reranker 模型 ──
Write-Host "[3/4] 下载 Reranker 模型..." -ForegroundColor Yellow
Write-Host "  提示: 若已离线部署模型到 reranker_models/ 目录，可跳过"
$download = Read-Host "  是否下载 Reranker 模型? 首次需要网络 (y/N)"
if ($download -eq "y" -or $download -eq "Y") {
    docker compose exec -T app python scripts/download_reranker.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ⚠ 模型下载失败，Reranker 将自动降级" -ForegroundColor Yellow
    }
} else {
    Write-Host "  已跳过模型下载"
}

# ── 4. 创建超级管理员 ──
Write-Host "[4/4] 创建超级管理员账户..." -ForegroundColor Yellow
$adminUser = Read-Host "  用户名 (默认 admin)"
if (-not $adminUser) { $adminUser = "admin" }
$adminPass = Read-Host "  密码 (至少8位，含字母+数字)" -AsSecureString
$adminPassPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminPass)
)

if (-not $adminPassPlain) {
    Write-Host "  ✗ 密码不能为空，请手动创建管理员" -ForegroundColor Red
    Write-Host "  参考 docs/deployment.md"
} else {
    $script = @"
import asyncio
from app.core.database import async_session_factory
from app.services.auth_service import AuthService

async def main():
    async with async_session_factory() as db:
        service = AuthService(db)
        try:
            user = await service.register('$adminUser', '$adminPassPlain', '${adminUser}@intellikb.local')
            user.system_role = 'superadmin'
            await db.commit()
            print(f'Superadmin created: id={user.id}, username={user.username}')
        except Exception as e:
            if '已存在' in str(e) or 'Duplicate' in str(e):
                print(f'用户 $adminUser 已存在，跳过创建')
            else:
                raise

asyncio.run(main())
"@
    $script | docker compose exec -T app python
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ 超级管理员创建完成" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ 创建失败，请手动执行" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  初始化完成!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  前端:      http://localhost:5173"
Write-Host "  API 文档:  http://localhost:8000/docs"
Write-Host "  管理后台:  http://localhost:5173/admin"
Write-Host ""
Write-Host "  登录账户: $adminUser"
Write-Host "  请立即登录并修改密码。"
