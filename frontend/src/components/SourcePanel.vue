<template>
  <div class="source-panel" :class="{ collapsed: isCollapsed, 'has-sources': sources.length > 0 }">
    <div class="source-panel-header" @click="toggleCollapse">
      <span class="source-panel-title">
        📚 参考来源 ({{ sources.length }})
      </span>
      <el-button text size="small" @click.stop="isCollapsed = !isCollapsed">
        <el-icon><component :is="isCollapsed ? 'ArrowUp' : 'ArrowDown'" /></el-icon>
      </el-button>
    </div>

    <div v-show="!isCollapsed" class="source-panel-body">
      <div v-if="sources.length === 0" class="source-empty">
        无引用来源
      </div>
      <div
        v-for="(source, idx) in sources"
        :key="source.chunk_id || idx"
        class="source-card"
        :class="{ highlighted: highlightedIndex === idx + 1 }"
        @click="onSourceClick(idx + 1)"
        @mouseenter="$emit('source-hover', idx + 1)"
        @mouseleave="$emit('source-hover', null)"
      >
        <div class="source-card-header">
          <el-tag size="small" :type="highlightedIndex === idx + 1 ? 'primary' : 'info'">
            [{{ idx + 1 }}]
          </el-tag>
          <span class="source-doc-title">
            {{ source.document_title || ('文档 #' + source.document_id) }}
          </span>
          <el-progress
            :percentage="Math.round((source.score || 0) * 100)"
            :stroke-width="4"
            :color="scoreColor(source.score)"
            style="width: 60px"
          />
        </div>
        <div class="source-card-excerpt">
          {{ (source.excerpt || source.content || '').slice(0, 200) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { SearchResult } from '@/types'

interface Props {
  sources: SearchResult[]
  highlightedIndex?: number | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'source-click': [index: number]
  'source-hover': [index: number | null]
}>()

const isCollapsed = ref(false)

// Auto-expand when new sources arrive
watch(() => props.sources?.length, (newLen) => {
  if (newLen > 0) isCollapsed.value = false
})

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
}

function onSourceClick(index: number) {
  emit('source-click', index)
  // Scroll to the corresponding inline citation in the answer
  const el = document.querySelector(`.src-ref[data-src="${index}"]`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('src-ref-flash')
    setTimeout(() => el.classList.remove('src-ref-flash'), 1500)
  }
}

function scoreColor(score: number) {
  if (score > 0.7) return '#67c23a'
  if (score > 0.4) return '#e6a23c'
  return '#f56c6c'
}
</script>

<style scoped>
.source-panel {
  margin-top: 8px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fafafa;
  max-width: 100%;
}
.source-panel.collapsed {
  border-bottom: 1px solid #ebeef5;
}
.source-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  cursor: pointer;
  user-select: none;
}
.source-panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.source-panel-body {
  padding: 0 12px 12px;
}
.source-empty {
  text-align: center;
  color: #909399;
  padding: 16px;
  font-size: 13px;
}
.source-card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.source-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}
.source-card.highlighted {
  border-color: #409eff;
  background: #ecf5ff;
}
.source-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.source-doc-title {
  font-size: 12px;
  color: #606266;
  font-weight: 500;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-card-excerpt {
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

/* 移动端：可折叠为底部抽屉 */
@media (max-width: 768px) {
  .source-panel {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 100;
    border-radius: 12px 12px 0 0;
    max-height: 40vh;
    overflow-y: auto;
    box-shadow: 0 -2px 16px rgba(0,0,0,0.1);
  }
}
</style>

<!-- Global style for flash animation -->
<style>
.src-ref-flash {
  animation: src-flash 0.5s ease-in-out 3;
  background: #ecf5ff;
  border-radius: 2px;
}
@keyframes src-flash {
  0%, 100% { background: transparent; }
  50% { background: #ecf5ff; }
}
</style>
