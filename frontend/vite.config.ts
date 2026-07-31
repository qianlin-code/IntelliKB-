import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "path";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    // Phase 7: 代码分割 — 将大型 vendor 库拆分为独立 chunk
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // Phase 7: manualChunks 使用 Rolldown 函数式语法
        manualChunks(id: string) {
          if (
            id.includes("node_modules/element-plus") ||
            id.includes("node_modules/@element-plus")
          ) {
            return "vendor-element";
          }
          if (
            id.includes("node_modules/marked") ||
            id.includes("node_modules/highlight.js") ||
            id.includes("node_modules/dompurify")
          ) {
            return "vendor-markdown";
          }
          if (
            id.includes("node_modules/vue") ||
            id.includes("node_modules/vue-router") ||
            id.includes("node_modules/pinia")
          ) {
            return "vendor-vue";
          }
        },
      },
    },
  },
});
