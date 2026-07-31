<template>
  <div class="tool-call-card">
    <div class="tool-header" @click="expanded = !expanded">
      <el-icon :size="14">
        <component :is="expanded ? 'ArrowDown' : 'ArrowRight'" />
      </el-icon>
      <el-tag size="small" type="warning" effect="plain">
        <el-icon style="margin-right: 4px"><Tools /></el-icon>
        {{ tool }}
      </el-tag>
      <span class="tool-status">{{ statusLabel }}</span>
    </div>
    <div v-if="expanded" class="tool-body">
      <div class="tool-section">
        <div class="tool-section-label">输入</div>
        <pre class="tool-code">{{ formatJSON(input) }}</pre>
      </div>
      <div class="tool-section">
        <div class="tool-section-label">输出</div>
        <pre class="tool-code">{{ output }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Tools } from '@element-plus/icons-vue'

interface Props {
  tool: string
  input: Record<string, unknown>
  output: string
}

const props = defineProps<Props>()
const expanded = ref(false)

const statusLabel = '查看详情'

function formatJSON(obj: Record<string, unknown>): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}
</script>

<style scoped>
.tool-call-card {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  margin: 8px 0;
  background: #fafafa;
  overflow: hidden;
}
.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
}
.tool-header:hover {
  background: #f0f0f0;
}
.tool-status {
  color: #909399;
  font-size: 12px;
  margin-left: auto;
}
.tool-body {
  border-top: 1px solid #e0e0e0;
  padding: 8px 12px;
}
.tool-section {
  margin-bottom: 8px;
}
.tool-section-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.tool-code {
  background: #f5f5f5;
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}
</style>
