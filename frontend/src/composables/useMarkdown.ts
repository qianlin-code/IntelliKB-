/**
 * 统一 Markdown 渲染 composable
 *
 * 复用 StreamingText 已有的 marked + DOMPurify 方案，新增 highlight.js 代码语法高亮。
 * ChatMessage 和 StreamingText 统一使用此 composable。
 */
import { computed, ref } from 'vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github.css'

// marked v13+ API：使用 marked.use({ renderer }) 自定义代码渲染
// 编码时以实际安装的 marked 版本导出的 Renderer 类型为准
const renderer = new marked.Renderer()
renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
  const highlighted = lang && hljs.getLanguage(lang)
    ? hljs.highlight(text, { language: lang }).value
    : text
  return `<pre><code class="hljs ${lang || ''}">${highlighted}</code></pre>`
}
marked.use({ renderer })

export function useMarkdown(content: () => string) {
  const renderedContent = computed(() => {
    const raw = content()
    if (!raw) return ''
    try {
      const html = marked.parse(raw, { async: false }) as string
      return DOMPurify.sanitize(html)
    } catch {
      return raw
    }
  })

  return { renderedContent }
}

/**
 * 同步渲染 markdown 字符串为安全 HTML
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    const html = marked.parse(text, { async: false }) as string
    return DOMPurify.sanitize(html)
  } catch {
    return text
  }
}
