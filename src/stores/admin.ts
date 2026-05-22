import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Document, SystemUser } from '@/types'
import { fetchDocumentsApi, uploadDocumentApi, deleteDocumentApi } from '@/api/knowledge'
import { fetchUsersApi, toggleUserStatusApi } from '@/api/user'

export const useAdminStore = defineStore('admin', () => {
  const documents = ref<Document[]>([])
  const users = ref<SystemUser[]>([])

  async function fetchDocuments() {
    documents.value = await fetchDocumentsApi()
  }

  async function uploadDocument(file: File) {
    const doc = await uploadDocumentApi(file)
    documents.value.unshift(doc)
  }

  async function deleteDocument(id: string) {
    await deleteDocumentApi(id)
    documents.value = documents.value.filter((d) => d.id !== id)
  }

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
    fetchDocuments,
    uploadDocument,
    deleteDocument,
    fetchUsers,
    toggleUserStatus,
  }
})
