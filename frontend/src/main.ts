import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

// 令牌必须先于 Tailwind 引入（后者在 @layer base 里引用 var(--bg) 等）
import './styles/tokens.css'
import './style.css'

// Code highlight theme
import 'highlight.js/styles/github-dark.min.css'

// 主题初始化：跟随上次选择，否则跟随系统
;(function initTheme() {
  const saved = localStorage.getItem('medrag_theme')
  const dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches
  document.documentElement.classList.toggle('dark', dark)
})()

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
