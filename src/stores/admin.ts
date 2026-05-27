import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { SystemUser } from '@/types'
import type { KnowledgeBase, DocumentInfo, KBCreatePayload } from '@/types/knowledge'
import {
  fetchDocumentsApi, uploadDocumentApi, deleteDocumentApi, retryDocumentApi,
  fetchKnowledgeBasesApi, createKnowledgeBaseApi, deleteKnowledgeBaseApi,
} from '@/api/knowledge'
import { fetchUsersApi, toggleUserStatusApi } from '@/api/user'

export const useAdminStore = defineStore('admin', () => {
  const documents = ref<DocumentInfo[]>([])
  const users = ref<SystemUser[]>([])
  const knowledgeBases = ref<KnowledgeBase[]>([])
  const kbLoading = ref(false)
  const activeKbId = ref<string | null>(localStorage.getItem('medrag_active_kb'))

  const activeKb = computed(() =>
    knowledgeBases.value.find((k) => k.id === activeKbId.value)
  )

  // ── KB actions ──

  async function fetchKnowledgeBases() {
    kbLoading.value = true
    knowledgeBases.value = await fetchKnowledgeBasesApi()
    kbLoading.value = false
  }

  async function createKnowledgeBase(payload: KBCreatePayload) {
    const kb = await createKnowledgeBaseApi(payload)
    knowledgeBases.value.unshift(kb)
    return kb
  }

  async function deleteKnowledgeBase(id: string) {
    await deleteKnowledgeBaseApi(id)
    knowledgeBases.value = knowledgeBases.value.filter((k) => k.id !== id)
    if (activeKbId.value === id) {
      activeKbId.value = null
      localStorage.removeItem('medrag_active_kb')
    }
  }

  function setActiveKb(id: string | null) {
    activeKbId.value = id
    if (id) {
      localStorage.setItem('medrag_active_kb', id)
    } else {
      localStorage.removeItem('medrag_active_kb')
    }
  }

  // ── Doc actions ──

  async function fetchDocuments(kbId: string) {
    documents.value = await fetchDocumentsApi(kbId)
  }

  async function uploadDocument(kbId: string, file: File) {
    const doc = await uploadDocumentApi(kbId, file)
    handleDocUpdate(doc)
  }

  async function deleteDocument(id: string) {
    await deleteDocumentApi(id)
    documents.value = documents.value.filter((d) => d.id !== id)
  }

  async function retryDocument(id: string) {
    const res = await retryDocumentApi(id)
    const doc = documents.value.find((d) => d.id === id)
    if (doc) {
      doc.status = 'pending'
      doc.error_msg = null
    }
    return res
  }

  // ── WebSocket handlers ──

  function handleDocUpdate(doc: DocumentInfo) {
    const idx = documents.value.findIndex((d) => d.id === doc.id)
    if (idx >= 0) {
      // 更新第一个匹配项，删除其余重复
      documents.value[idx] = doc
      documents.value = documents.value.filter((d, i) => i === idx || d.id !== doc.id)
    } else {
      documents.value.unshift(doc)
    }
  }

  function handleDocDeleted(docId: string) {
    documents.value = documents.value.filter((d) => d.id !== docId)
  }

  // ── User actions ──

  async function fetchUsers() {
    users.value = await fetchUsersApi()
  }

  async function toggleUserStatus(id: string) {
    const user = users.value.find((u) => u.id === id)
    if (!user) return
    const newEnabled = !user.enabled
    await toggleUserStatusApi(id, newEnabled)
    user.enabled = newEnabled
  }

  return {
    documents,
    users,
    knowledgeBases,
    kbLoading,
    activeKbId,
    activeKb,
    fetchKnowledgeBases,
    setActiveKb,
    createKnowledgeBase,
    deleteKnowledgeBase,
    fetchDocuments,
    uploadDocument,
    deleteDocument,
    retryDocument,
    handleDocUpdate,
    handleDocDeleted,
    fetchUsers,
    toggleUserStatus,
  }
})
