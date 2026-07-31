<template>
  <span class="source-reference">
    <el-popover
      placement="top"
      :width="400"
      trigger="click"
      :show-after="0"
    >
      <template #reference>
        <sup class="source-badge" @click.stop>[{{ index }}]</sup>
      </template>
      <div class="source-popover-content">
        <div class="source-popover-header">
          <el-tag size="small" type="info">来源 {{ index }}</el-tag>
          <span v-if="source?.document_id" class="source-doc-id">
            文档 #{{ source.document_id }}
          </span>
        </div>
        <div class="source-popover-text">{{ source?.excerpt || source?.content || '(内容不可用)' }}</div>
      </div>
    </el-popover>
  </span>
</template>

<script setup lang="ts">
import type { SearchResult } from '@/types'

interface CitationInfo {
  source_index: number
  chunk_id: number
  document_id: number
  excerpt: string
}

interface Props {
  index: number
  source?: SearchResult | null
}

const props = defineProps<Props>()
</script>

<style scoped>
.source-reference {
  display: inline;
}
.source-badge {
  color: #409eff;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.85em;
  padding: 0 2px;
  user-select: none;
}
.source-badge:hover {
  color: #337ecc;
  text-decoration: underline;
}
.source-popover-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.source-doc-id {
  font-size: 12px;
  color: #909399;
}
.source-popover-text {
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
  max-height: 200px;
  overflow-y: auto;
}
</style>
