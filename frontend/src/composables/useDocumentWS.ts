import { ref, watch, onMounted, onUnmounted } from 'vue'
import type { Ref } from 'vue'
import { useAdminStore } from '@/stores/admin'

export function useDocumentWS(kbId: Ref<string | null>) {
  const ws = ref<WebSocket | null>(null)
  const connected = ref(false)
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectDelay = 1000
  let stopped = false

  function connect() {
    if (stopped) return
    const kid = kbId.value
    if (!kid) return

    const token = localStorage.getItem('access_token')
    if (!token) return

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/api/v1/ws/documents/${kid}?token=${token}`

    try {
      const socket = new WebSocket(url)
      ws.value = socket

      socket.onopen = () => {
        connected.value = true
        reconnectDelay = 1000
      }

      socket.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data)
          const store = useAdminStore()
          if (event.type === 'doc_update') {
            store.handleDocUpdate(event.doc)
          } else if (event.type === 'doc_deleted') {
            store.handleDocDeleted(event.doc_id)
          }
        } catch {
          // ignore malformed messages
        }
      }

      socket.onclose = () => {
        connected.value = false
        ws.value = null
        scheduleReconnect()
      }

      socket.onerror = () => {
        socket.close()
      }
    } catch {
      scheduleReconnect()
    }
  }

  function scheduleReconnect() {
    if (stopped) return
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(() => {
      reconnectDelay = Math.min(reconnectDelay * 2, 30000)
      connect()
    }, reconnectDelay)
  }

  function disconnect() {
    stopped = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    ws.value?.close()
    ws.value = null
    connected.value = false
  }

  // kbId 切换时重连
  watch(kbId, (newId, oldId) => {
    if (oldId) {
      // 简单断开旧连接，不设置 stopped=true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      reconnectTimer = null
      ws.value?.close()
      ws.value = null
      connected.value = false
      reconnectDelay = 1000
    }
    if (newId) {
      // 等一小段时间让旧连接关闭，再建新连接
      setTimeout(() => {
        reconnectDelay = 1000
        connect()
      }, 200)
    }
  })

  onMounted(() => {
    stopped = false
    if (kbId.value) connect()
  })

  onUnmounted(() => {
    disconnect()
  })

  return { connected }
}
