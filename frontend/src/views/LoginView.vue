<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { Eye, EyeOff, ArrowRight, AlertCircle } from 'lucide-vue-next'

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
  <div class="flex min-h-screen items-center justify-center bg-canvas px-5">
    <div class="w-full max-w-[400px]">
      <!-- 品牌 -->
      <div class="mb-9 text-center">
        <div
          class="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-xl text-[15px] font-bold text-white shadow-[0_4px_16px_rgba(66,133,244,.35)]"
          style="background: linear-gradient(100deg, var(--grad-1), var(--grad-2), var(--grad-3))"
        >
          M
        </div>
        <h1 class="text-[26px] font-semibold tracking-[-.4px]">MedRAG</h1>
        <p class="mt-1 text-[13.5px] text-muted">医学文献智能问答</p>
      </div>

      <div class="rounded-2xl border border-line bg-surface-2 p-7">
        <label class="mb-1.5 block text-[12.5px] font-medium text-ink-2">用户名</label>
        <input
          v-model="username"
          type="text"
          placeholder="输入用户名"
          class="mb-4 w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-ink placeholder:text-faint outline-none transition-colors focus:border-accent focus:bg-canvas"
          @keydown="handleKeydown"
        />

        <label class="mb-1.5 block text-[12.5px] font-medium text-ink-2">密码</label>
        <div class="relative mb-2">
          <input
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            placeholder="输入密码"
            class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 pr-10 text-[14px] text-ink placeholder:text-faint outline-none transition-colors focus:border-accent focus:bg-canvas"
            @keydown="handleKeydown"
          />
          <button
            class="absolute right-2.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full text-faint transition-colors hover:bg-hover hover:text-ink"
            @click="showPassword = !showPassword"
          >
            <EyeOff v-if="showPassword" :size="15" />
            <Eye v-else :size="15" />
          </button>
        </div>

        <p v-if="error" class="mt-3 flex items-center gap-1.5 text-[12.5px] text-danger">
          <AlertCircle :size="13" />
          {{ error }}
        </p>

        <button
          :disabled="isLoading"
          class="mt-6 flex w-full items-center justify-center gap-1.5 rounded-full bg-accent px-4 py-2.5 text-[14px] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
          @click="handleLogin"
        >
          {{ isLoading ? '登录中…' : '登录' }}
          <ArrowRight v-if="!isLoading" :size="15" />
        </button>

        <p class="mt-5 text-center text-[12.5px] text-muted">
          没有账号？
          <router-link to="/register" class="text-accent-text hover:underline">立即注册</router-link>
        </p>
      </div>

      <p class="mt-6 text-center text-[11px] text-faint">
        基于 1,248 篇中文医学文献 · 回答附原文出处
      </p>
    </div>
  </div>
</template>
