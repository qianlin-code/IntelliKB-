/**
 * Phase 8: 引用标记处理
 *
 * 将 LLM 回答中的 [source:N] / [来源 N] 文本标记
 * 转换为可点击的 HTML sup 元素。
 */

// 匹配 [source:N] 或 [来源 N] 或 [来源N]
const CITATION_RE = /\[source:\s*(\d+)\]|\[来源\s*(\d+)\]/gi

/**
 * 将文本中的引用标记替换为 HTML sup 标签。
 *
 * @param text 原始回答文本
 * @returns 替换后的 HTML 字符串
 *
 * 示例:
 *   "这是答案[source:1]内容" → "这是答案<sup class="src-ref" data-src="1">[1]</sup>内容"
 */
export function preprocessCitations(text: string): string {
  return text.replace(CITATION_RE, (_match, n1: string | undefined, n2: string | undefined) => {
    const n = n1 || n2
    return `<sup class="src-ref" data-src="${n}">[${n}]</sup>`
  })
}

/**
 * 从文本中提取所有引用的 source 编号
 */
export function extractCitationIndices(text: string): number[] {
  const indices = new Set<number>()
  let match
  const re = new RegExp(CITATION_RE.source, 'gi')
  while ((match = re.exec(text)) !== null) {
    const n = parseInt(match[1] || match[2])
    if (n >= 1 && n <= 50) {
      indices.add(n)
    }
  }
  return [...indices].sort((a, b) => a - b)
}
