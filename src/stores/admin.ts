import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Document, SystemUser } from '@/types'
import { fetchDocumentsApi, uploadDocumentApi, deleteDocumentApi } from '@/api/knowledge'
import { fetchUsersApi, toggleUserStatusApi } from '@/api/user'

export const useAdminStore = defineStore('admin', () => {
  const documents = ref<Document[]>([])
  const users = ref<SystemUser[]>([])

  async function fetchDocuments() {
    try {
      documents.value = await fetchDocumentsApi()
    } catch {
      documents.value = []
    }
  }

  async function uploadDocument(file: File) {
    try {
      const doc = await uploadDocumentApi(file)
      documents.value.unshift(doc)
    } catch {
      // TODO: show error toast
    }
  }

  async function deleteDocument(id: string) {
    try {
      await deleteDocumentApi(id)
    } catch {
      // Proceed locally
    }
    documents.value = documents.value.filter((d) => d.id !== id)
  }

  async function fetchUsers() {
    try {
      users.value = await fetchUsersApi()
    } catch {
      users.value = []
    }
  }

  async function toggleUserStatus(id: string) {
    const user = users.value.find((u) => u.id === id)
    if (!user) return
    const newEnabled = !user.enabled
    try {
      await toggleUserStatusApi(id, newEnabled)
      user.enabled = newEnabled
    } catch {
      // Revert on error
    }
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
