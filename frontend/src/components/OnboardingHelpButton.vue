<template>
  <el-tooltip content="重新查看新手引导" placement="bottom">
    <el-button text size="small" :icon="QuestionFilled" @click="onReset">
      帮助
    </el-button>
  </el-tooltip>
</template>

<script setup lang="ts">
import { QuestionFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useOnboarding } from '@/composables/useOnboarding'

const { resetAll } = useOnboarding()

async function onReset() {
  try {
    await ElMessageBox.confirm('重置后进入各页面会重新显示新手引导，是否继续？', '重置引导', {
      type: 'info',
    })
    resetAll()
    ElMessage.success('已重置，刷新页面或切换页面后重新触发引导')
  } catch {
    // 取消
  }
}
</script>
