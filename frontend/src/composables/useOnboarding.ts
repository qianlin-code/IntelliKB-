/**
 * Phase P0: 新手引导 (driver.js)
 *
 * - 按页面记录完成状态到 localStorage
 * - 提供 startTour 方法在页面挂载后延迟触发
 * - 步骤支持动态选择器（若元素不存在则跳过）
 */
import { driver, type DriveStep } from 'driver.js'
import 'driver.js/dist/driver.css'

const STORAGE_KEY_PREFIX = 'intellikb_onboarding_'

export interface TourOptions {
  pageKey: string
  steps: DriveStep[]
  delay?: number
}

export function useOnboarding() {
  function hasCompleted(pageKey: string): boolean {
    try {
      return localStorage.getItem(`${STORAGE_KEY_PREFIX}${pageKey}`) === 'done'
    } catch {
      return false
    }
  }

  function markCompleted(pageKey: string) {
    try {
      localStorage.setItem(`${STORAGE_KEY_PREFIX}${pageKey}`, 'done')
    } catch {
      // ignore
    }
  }

  function startTour(options: TourOptions) {
    const validSteps = options.steps.filter((s) => {
      if (typeof s.element === 'string') {
        return !!document.querySelector(s.element)
      }
      return true
    })
    if (validSteps.length === 0) return

    const d = driver({
      showProgress: true,
      allowClose: true,
      stagePadding: 4,
      popoverClass: 'intellikb-driver-popover',
      steps: validSteps,
      onDestroyStarted: () => {
        markCompleted(options.pageKey)
        d.destroy()
      },
    })

    const delay = options.delay ?? 500
    setTimeout(() => d.drive(), delay)
  }

  function resetAll() {
    try {
      Object.keys(localStorage)
        .filter((k) => k.startsWith(STORAGE_KEY_PREFIX))
        .forEach((k) => localStorage.removeItem(k))
    } catch {
      // ignore
    }
  }

  return { startTour, hasCompleted, markCompleted, resetAll }
}
