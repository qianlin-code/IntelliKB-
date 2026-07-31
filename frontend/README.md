# IntelliKB Frontend

## 开发环境

- 推荐 Node.js 20.x LTS 或 22.x LTS
- Node.js 24.x 可能与 vue-tsc 3.3.8 存在兼容性问题，报错 `ERR_PACKAGE_PATH_NOT_EXPORTED`
- 遇到时请切换 Node 版本：`nvm use 22`

## 启动

```bash
npm install
npm run dev       # Vite dev server → http://localhost:5173
npm run build     # 生产构建（vue-tsc --noEmit + vite build）
```
