import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import container from 'markdown-it-container'
import { useMemoize } from '@vueuse/core'

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
      } catch { /* fall through */ }
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
// Intercepts text token rendering to convert [N] / [doc-N] into interactive citation spans.
md.renderer.rules.text = (tokens, idx) => {
  return tokens[idx].content.replace(
    /\[(\d+|doc-\d+)\]/g,
    (_m: string, id: string) => {
      const num = id.replace('doc-', '')
      return `<span class="citation-tag" data-citation-id="${num}">[${num}]</span>`
    },
  )
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

const render = useMemoize(renderRaw)

export function useMarkdown() {
  return { render }
}
