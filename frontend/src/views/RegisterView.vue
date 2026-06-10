<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { registerApi } from '@/api/auth'
import { useToastStore } from '@/stores/toast'
import { Stethoscope, Eye, EyeOff, UserPlus } from 'lucide-vue-next'

const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const showConfirm = ref(false)
const isLoading = ref(false)
const error = ref('')

const router = useRouter()
const toastStore = useToastStore()

function validate(): string | null {
  if (!username.value.trim()) return '请输入用户名'
  if (!/^[a-zA-Z0-9_]+$/.test(username.value.trim())) return '用户名仅允许字母、数字、下划线'
  if (username.value.trim().length < 3 || username.value.trim().length > 20) return '用户名需 3-20 字符'
  if (password.value.length < 6 || password.value.length > 50) return '密码需 6-50 字符'
  if (password.value !== confirmPassword.value) return '两次输入的密码不一致'
  return null
}

async function handleRegister() {
  error.value = ''
  const err = validate()
  if (err) { error.value = err; return }

  isLoading.value = true
  try {
    await registerApi(username.value.trim(), password.value)
    toastStore.success('注册成功，请等待管理员审核')
    router.push('/login')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '注册失败'
    toastStore.error(msg)
    error.value = msg
  } finally {
    isLoading.value = false
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') handleRegister()
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-100 via-white to-primary-50 px-4">
    <div class="w-full max-w-md">
      <!-- Logo -->
      <div class="mb-8 text-center">
        <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-600 to-sky-500 shadow-lg">
          <Stethoscope :size="28" class="text-white" />
        </div>
        <h1 class="text-2xl font-bold tracking-tight text-slate-900">MedRAG</h1>
        <p class="mt-1.5 text-sm text-slate-500">注册新账号</p>
      </div>

      <!-- Form Card -->
      <div class="rounded-2xl border bg-white/80 backdrop-blur-xl p-8 shadow-sm">
        <!-- Username -->
        <div class="mb-5">
          <label class="mb-1.5 block text-sm font-medium text-slate-700">用户名</label>
          <input
            v-model="username"
            type="text"
            placeholder="3-20 位字母、数字、下划线"
            class="w-full rounded-xl border bg-slate-50 px-4 py-2.5 text-sm text-slate-900 placeholder-slate-400 outline-none transition-all focus:border-primary-400 focus:bg-white focus:ring-2 focus:ring-primary-100"
            @keydown="handleKeydown"
          />
        </div>

        <!-- Password -->
        <div class="mb-5">
          <label class="mb-1.5 block text-sm font-medium text-slate-700">密码</label>
          <div class="relative">
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              placeholder="6-50 位"
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

        <!-- Confirm Password -->
        <div class="mb-2">
          <label class="mb-1.5 block text-sm font-medium text-slate-700">确认密码</label>
          <div class="relative">
            <input
              v-model="confirmPassword"
              :type="showConfirm ? 'text' : 'password'"
              placeholder="再次输入密码"
              class="w-full rounded-xl border bg-slate-50 px-4 py-2.5 pr-10 text-sm text-slate-900 placeholder-slate-400 outline-none transition-all focus:border-primary-400 focus:bg-white focus:ring-2 focus:ring-primary-100"
              @keydown="handleKeydown"
            />
            <button
              class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              @click="showConfirm = !showConfirm"
            >
              <EyeOff v-if="showConfirm" :size="16" />
              <Eye v-else :size="16" />
            </button>
          </div>
        </div>

        <!-- Error -->
        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>

        <!-- Submit -->
        <button
          :disabled="isLoading"
          class="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-all hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]"
          @click="handleRegister"
        >
          <UserPlus :size="16" />
          <span v-if="!isLoading">注册</span>
          <span v-else>注册中...</span>
        </button>

        <!-- Login link -->
        <p class="mt-4 text-center text-xs text-slate-400">
          已有账号？
          <router-link to="/login" class="text-primary-600 hover:text-primary-700 transition-colors">返回登录</router-link>
        </p>
      </div>
    </div>
  </div>
</template>
