<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { Stethoscope, Eye, EyeOff, LogIn } from 'lucide-vue-next'

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const isLoading = ref(false)
const error = ref('')

const router = useRouter()
const authStore = useAuthStore()

async function handleLogin() {
  error.value = ''
  if (!username.value.trim() || !password.value.trim()) {
    error.value = '请输入用户名和密码'
    return
  }

  isLoading.value = true
  try {
    await authStore.login(username.value.trim(), password.value)
    router.push('/chat')
  } catch {
    error.value = '登录失败，请重试'
  } finally {
    isLoading.value = false
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') handleLogin()
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-100 via-white to-primary-50 px-4">
    <!-- Login Card -->
    <div class="w-full max-w-md">
      <!-- Logo -->
      <div class="mb-8 text-center">
        <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-600 to-sky-500 shadow-lg">
          <Stethoscope :size="28" class="text-white" />
        </div>
        <h1 class="text-2xl font-bold tracking-tight text-slate-900">
          MedRAG
        </h1>
        <p class="mt-1.5 text-sm text-slate-500">
          医学文献可视化 RAG 辅助问答系统
        </p>
      </div>

      <!-- Form -->
      <div class="rounded-2xl border bg-white/80 backdrop-blur-xl p-8 shadow-sm">
        <div class="mb-6">
          <label class="mb-1.5 block text-sm font-medium text-slate-700">
            用户名
          </label>
          <input
            v-model="username"
            type="text"
            placeholder="输入用户名 (admin 为管理员)"
            class="w-full rounded-xl border bg-slate-50 px-4 py-2.5 text-sm text-slate-900 placeholder-slate-400 outline-none transition-all focus:border-primary-400 focus:bg-white focus:ring-2 focus:ring-primary-100"
            @keydown="handleKeydown"
          />
        </div>

        <div class="mb-2">
          <label class="mb-1.5 block text-sm font-medium text-slate-700">
            密码
          </label>
          <div class="relative">
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              placeholder="输入密码"
              class="w-full rounded-xl border bg-slate-50 px-4 py-2.5 pr-10 text-sm text-slate-900 placeholder-slate-400 outline-none transition-all focus:border-primary-400 focus:bg-white focus:ring-2 focus:ring-primary-100"
              @keydown="handleKeydown"
            />
            <button
              class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              @click="showPassword = !showPassword"
            >
              <EyeOff v-if="showPassword" :size="16" />
              <Eye v-else :size="16" />
            </button>
          </div>
        </div>

        <p v-if="error" class="mb-4 text-sm text-red-500">{{ error }}</p>

        <button
          :disabled="isLoading"
          class="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-all hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
          @click="handleLogin"
        >
          <LogIn :size="16" />
          <span v-if="!isLoading">登录</span>
          <span v-else>登录中...</span>
        </button>

        <p class="mt-4 text-center text-xs text-slate-400">
          提示：默认管理员账号 admin / admin123，登录后请修改密码
        </p>
      </div>
    </div>
  </div>
</template>
