<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { registerApi } from '@/api/auth'
import { useToastStore } from '@/stores/toast'
import { Eye, EyeOff, ArrowRight, AlertCircle } from 'lucide-vue-next'

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
  <div class="flex min-h-screen items-center justify-center bg-canvas px-5 py-10">
    <div class="w-full max-w-[400px]">
      <!-- 品牌 -->
      <div class="mb-8 text-center">
        <div
          class="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-xl text-[15px] font-bold text-white shadow-[0_4px_16px_rgba(66,133,244,.35)]"
          style="background: linear-gradient(100deg, var(--grad-1), var(--grad-2), var(--grad-3))"
        >
          M
        </div>
        <h1 class="text-[26px] font-semibold tracking-[-.4px]">创建账号</h1>
        <p class="mt-1 text-[13.5px] text-muted">注册后需管理员审核通过才能登录</p>
      </div>

      <div class="rounded-2xl border border-line bg-surface-2 p-7">
        <label class="mb-1.5 block text-[12.5px] font-medium text-ink-2">用户名</label>
        <input
          v-model="username"
          type="text"
          placeholder="3-20 位字母、数字、下划线"
          class="mb-4 w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-ink placeholder:text-faint outline-none transition-colors focus:border-accent focus:bg-canvas"
          @keydown="handleKeydown"
        />

        <label class="mb-1.5 block text-[12.5px] font-medium text-ink-2">密码</label>
        <div class="relative mb-4">
          <input
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            placeholder="6-50 位"
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

        <label class="mb-1.5 block text-[12.5px] font-medium text-ink-2">确认密码</label>
        <div class="relative mb-2">
          <input
            v-model="confirmPassword"
            :type="showConfirm ? 'text' : 'password'"
            placeholder="再次输入密码"
            class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 pr-10 text-[14px] text-ink placeholder:text-faint outline-none transition-colors focus:border-accent focus:bg-canvas"
            @keydown="handleKeydown"
          />
          <button
            class="absolute right-2.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full text-faint transition-colors hover:bg-hover hover:text-ink"
            @click="showConfirm = !showConfirm"
          >
            <EyeOff v-if="showConfirm" :size="15" />
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
          @click="handleRegister"
        >
          {{ isLoading ? '注册中…' : '注册' }}
          <ArrowRight v-if="!isLoading" :size="15" />
        </button>

        <p class="mt-5 text-center text-[12.5px] text-muted">
          已有账号？
          <router-link to="/login" class="text-accent-text hover:underline">返回登录</router-link>
        </p>
      </div>
    </div>
  </div>
</template>
