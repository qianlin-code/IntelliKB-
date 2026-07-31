# Contributing to IntelliKB

感谢你对 IntelliKB 的关注！

## 开发环境搭建

```bash
git clone https://github.com/yourname/intellikb.git
cd intellikb
cp .env.example .env
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## 代码规范

- Python: 遵循 PEP 8，使用 ruff 格式化
- TypeScript/Vue: 遵循 ESLint + Prettier
- 提交信息: 使用约定式提交格式

```bash
# 格式化后端
ruff format app/
ruff check app/

# 格式化前端
cd frontend && npm run lint
```

## 提交规范

```
feat: 新功能
fix: Bug 修复
docs: 文档更新
refactor: 重构
test: 测试
chore: 构建/工具
```

## 分支策略

- `main`: 稳定版本
- `feature-*`: 功能分支
- `fix-*`: 修复分支

## Pull Request 流程

1. Fork 仓库
2. 创建 feature 分支
3. 编写代码 + 测试
4. 确保 `ruff check app/` 通过
5. 提交 PR 并描述改动

## 测试

```bash
# 单元测试
pytest tests/ -v

# 集成测试 (需要 MySQL + Redis + Ollama)
pytest tests/integration/ -v -m integration
```

## 问题反馈

使用 GitHub Issues 提交 Bug 或功能建议。
