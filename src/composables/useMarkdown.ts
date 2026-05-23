import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import container from 'markdown-it-container'


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
// Converts [N], [doc-N], and [A,B,C] citation patterns into interactive citation spans.
md.renderer.rules.text = (tokens, idx) => {
  let content = tokens[idx].content
  // First split multi-citation [1,4] or [1,2,3] into separate tags
  content = content.replace(
    /\[(\d+(?:,\d+)+)\]/g,
    (_m: string, ids: string) =>
      ids
        .split(',')
        .map((n: string) => `[${n.trim()}]`)
        .join(''),
  )
  // Then convert each [N] into a citation-tag span
  return content.replace(
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

function render(text: string): string {
  return renderRaw(text)
}

export function useMarkdown() {
  return { render }
}
