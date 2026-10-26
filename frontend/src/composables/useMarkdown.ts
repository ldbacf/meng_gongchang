import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import container from 'markdown-it-container'

// ── 按需注册语法 ──────────────────────────────────────────────
//
// 不要 `import hljs from 'highlight.js'`：那个入口会注册**全部 192 种语言**
// （实测 lib/index.js 里 192 次 registerLanguage，语言包合计 1517 KB），
// 直接把聊天页 chunk 撑到 1 MB 以上。本产品是医学文献问答，代码块只出现在
// 技术追问里，注册下面这些足够；未注册的语言走 escapeHtml 分支降级为纯文本，
// 不报错、不丢内容。
//
// 语言名会自动带上自身别名（`registerAliases`），所以 `py`/`js`/`sh` 等
// 写法无需额外注册。
import bash from 'highlight.js/lib/languages/bash'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import css from 'highlight.js/lib/languages/css'
import go from 'highlight.js/lib/languages/go'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import rust from 'highlight.js/lib/languages/rust'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

const LANGUAGES = {
  bash,
  c,
  cpp,
  css,
  go,
  java,
  javascript,
  json,
  python,
  rust,
  sql,
  typescript,
  xml,
  yaml,
}

for (const [name, def] of Object.entries(LANGUAGES)) {
  hljs.registerLanguage(name, def)
}

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return (
          '<pre class="hljs"><code>' +
          hljs.highlight(str, { language: lang, ignoreIllegals: true }).value +
          '</code></pre>'
        )
      } catch {
        /* fall through */
      }
    }
    return '<pre class="hljs"><code>' + md.utils.escapeHtml(str) + '</code></pre>'
  },
})

// ── Custom containers: tip, warning, info ──
md.use(container, 'tip', {
  render(tokens: any, idx: number) {
    if (tokens[idx].nesting === 1) {
      return '<div class="md-container md-container-tip">\n'
    }
    return '</div>\n'
  },
})

md.use(container, 'warning', {
  render(tokens: any, idx: number) {
    if (tokens[idx].nesting === 1) {
      return '<div class="md-container md-container-warning">\n'
    }
    return '</div>\n'
  },
})

md.use(container, 'info', {
  render(tokens: any, idx: number) {
    if (tokens[idx].nesting === 1) {
      return '<div class="md-container md-container-info">\n'
    }
    return '</div>\n'
  },
})

// ── Citation plugin ──
// Converts [N], [doc-N], and [A,B,C] citation patterns into interactive citation spans.
md.renderer.rules.text = (tokens, idx) => {
  let content = tokens[idx].content
  // First split multi-citation [1,4] or [1,2,3] into separate tags
  content = content.replace(/\[(\d+(?:,\d+)+)\]/g, (_m: string, ids: string) =>
    ids
      .split(',')
      .map((n: string) => `[${n.trim()}]`)
      .join(''),
  )
  // Then convert each [N] into a citation-tag span
  return content.replace(/\[(\d+|doc-\d+)\]/g, (_m: string, id: string) => {
    const num = id.replace('doc-', '')
    return `<span class="citation-tag" data-citation-id="${num}">[${num}]</span>`
  })
}

// ── Render entry ──

function renderRaw(text: string): string {
  // Zero-width spaces around ** when adjacent to CJK characters,
  // so markdown-it recognizes emphasis boundaries
  const cjkFriendly = text
    .replace(/([^\x00-\x7F])(\*\*)/g, '$1​**')
    .replace(/(\*\*)([^\x00-\x7F])/g, '$1​$2')
  return md.render(cjkFriendly)
}

function render(text: string): string {
  return renderRaw(text)
}

export function useMarkdown() {
  return { render }
}
