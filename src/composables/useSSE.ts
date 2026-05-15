import { ref, onUnmounted } from 'vue'
import type { StreamChunk } from '@/types'

export function useSSE() {
  const isStreaming = ref(false)
  let abortController: AbortController | null = null

  async function startStream(
    url: string,
    body: Record<string, unknown>,
    onChunk: (chunk: StreamChunk) => void,
    onError?: (err: Error) => void,
  ) {
    const token = localStorage.getItem('token')
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
        throw new Error(`SSE error: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6).trim()
            if (jsonStr === '[DONE]') {
              onChunk({ type: 'done', data: '' })
              continue
            }
            try {
              const chunk: StreamChunk = JSON.parse(jsonStr)
              onChunk(chunk)
            } catch {
              // Ignore unparseable chunks
            }
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        onError?.(err as Error)
      }
    } finally {
      isStreaming.value = false
      abortController = null
    }
  }

  function abort() {
    abortController?.abort()
    isStreaming.value = false
  }

  onUnmounted(() => {
    abort()
  })

  return { isStreaming, startStream, abort }
}
