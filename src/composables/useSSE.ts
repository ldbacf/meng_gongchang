import { ref, onUnmounted } from 'vue'
import type { SSEMessage } from '@/types'

export function useSSE() {
  const isStreaming = ref(false)
  let abortController: AbortController | null = null

  async function startStream(
    url: string,
    body: Record<string, unknown>,
    onMsg: (msg: SSEMessage) => void,
    onError?: (err: Error) => void,
  ) {
    const token = localStorage.getItem('access_token')
    abortController = new AbortController()
    isStreaming.value = true

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: abortController.signal,
      })

      if (!response.ok) {
        const errText = await response.text().catch(() => '')
        onMsg({ t: 'error', message: `HTTP ${response.status}: ${errText.slice(0, 200)}` })
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        const allText = await response.text()
        _parseLines(allText, onMsg)
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        buffer = _parseLines(buffer, onMsg)
      }
      // Flush any remaining complete line
      _parseLines(buffer + '\n', onMsg)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        onError?.(err as Error)
        onMsg({ t: 'error', message: (err as Error).message || '连接失败' })
      }
    } finally {
      isStreaming.value = false
      abortController = null
    }
  }

  function _parseLines(text: string, onMsg: (msg: SSEMessage) => void): string {
    const lines = text.split('\n')
    const remaining = lines.pop() || ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const raw = JSON.parse(line.slice(6))
        const msg = raw as SSEMessage
        if (msg.t) onMsg(msg)
      } catch {
        // skip unparseable lines
      }
    }
    return remaining
  }

  function abort() {
    abortController?.abort()
    isStreaming.value = false
  }

  onUnmounted(() => { abort() })

  return { isStreaming, startStream, abort }
}
