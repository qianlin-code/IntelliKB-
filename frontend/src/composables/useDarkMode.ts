/**
 * Phase 9 P2.2: 暗黑模式切换
 */
import { ref, watchEffect } from 'vue'

const isDark = ref(false)

export function useDarkMode() {
  // Init from localStorage
  const saved = localStorage.getItem('theme')
  if (saved === 'dark') {
    isDark.value = true
    document.documentElement.classList.add('dark')
  }

  function toggle() {
    isDark.value = !isDark.value
    localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    if (isDark.value) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }

  return { isDark, toggle }
}
