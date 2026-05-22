import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import { useMemoize } from '@vueuse/core'

const md = new MarkdownIt({
  html: true,
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
        // fall through
      }
    }
    return '<pre class="hljs"><code>' + md.utils.escapeHtml(str) + '</code></pre>'
  },
})

function transformCitations(text: string): string {
  return text.replace(
    /\[(\d+|doc-\d+)\]/g,
    (_match, id: string) => {
      const num = id.replace('doc-', '')
      return `<span class="citation-tag" data-citation-id="${num}">[${num}]</span>`
    },
  )
}

function renderRaw(text: string): string {
  return md.render(transformCitations(text))
}

const render = useMemoize(renderRaw)

export function useMarkdown() {
  return { render }
}
