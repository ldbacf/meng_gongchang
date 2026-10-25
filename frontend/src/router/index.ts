import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/chat/:id',
    name: 'ChatConversation',
    component: () => import('@/views/ChatView.vue'),
    meta: { requiresAuth: true },
  },
  // 后台是**独立界面**：自己的左侧导航，不套聊天侧栏。
  // 入口在头像菜单「设置」，也可直接访问 /admin。
  {
    path: '/admin',
    component: () => import('@/components/layout/AdminLayout.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      { path: '', redirect: { name: 'KnowledgeBase' } },
      {
        path: 'knowledge',
        name: 'KnowledgeBase',
        component: () => import('@/views/KnowledgeBaseView.vue'),
      },
      {
        path: 'knowledge/:kbId',
        name: 'KnowledgeBaseDetail',
        component: () => import('@/views/KnowledgeBaseDetailView.vue'),
      },
      {
        path: 'users',
        name: 'UserManagement',
        component: () => import('@/views/UserManagementView.vue'),
      },
    ],
  },
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/chat',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  const user = JSON.parse(localStorage.getItem('user') ?? 'null')

  // Redirect to login if not authenticated and route requires auth
  if (to.meta.requiresAuth !== false && !token) {
    return { name: 'Login' }
  }

  // Redirect to chat if already authenticated and visiting login
  if (to.name === 'Login' && token) {
    return { name: 'Chat' }
  }

  // Redirect non-admin users from admin routes
  if (to.meta.requiresAdmin && user?.role !== 'admin') {
    return { name: 'Chat' }
  }
})

export default router
