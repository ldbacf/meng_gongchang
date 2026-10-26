// @ts-check
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'
import prettier from 'eslint-config-prettier'
import globals from 'globals'

/**
 * ESLint 配置（flat config）。
 *
 * 定位是**守住会出 bug 的东西**，不是改造代码风格 —— 风格交给 Prettier。
 * 所以规则集刻意保守：项目有 47 个文件、219 KB 代码，一上来就开
 * `vue/recommended` 会刷出几百条告警，没人会去看，等于没有。
 *
 * 分两档：
 *   - `error`：真的会导致运行时错误的（未定义变量、重复 key、无效模板）
 *   - `warn`：容易演化成 bug 的（未使用变量、any 泛滥、console 残留）
 */
export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'public/**',
      // 生成物：由 openapi-typescript 输出，改了也会被覆盖
      'src/types/api.gen.ts',
      // 单文件原型页（零依赖 HTML），不参与构建
      '*.html',
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/essential'],

  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        // vue-eslint-parser 需要显式指定 TS 解析器
        parser: tseslint.parser,
      },
    },
  },

  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      // 浏览器 API 一律用 globals.browser，不手写白名单 —— 手写那版会漏掉
      // WebSocket / location / HTMLDivElement 这类，报出的 no-undef 全是假阳性，
      // 真正的问题反而被淹掉。
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    rules: {
      // ── 会出运行时错误的：error ──
      'no-undef': 'error',
      'vue/no-duplicate-attributes': 'error',
      'vue/no-parsing-error': 'error',
      'vue/no-use-v-if-with-v-for': 'error',
      // v-for 缺 key 会导致复用错位（本项目踩过：流式消息串到别人会话）
      'vue/require-v-for-key': 'error',

      // ── 容易演化成 bug 的：warn ──
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'prefer-const': 'warn',
      eqeqeq: ['warn', 'smart'],

      // ── 与本项目既定约定冲突、主动关掉的 ──
      // 组件名沿用 Sidebar / ChatInput 这类单词命名，改名成本远大于收益
      'vue/multi-word-component-names': 'off',
      // CJK 与 ** 相邻时插入零宽空格的写法必须用 \x00-\x7F 控制字符范围
      'no-control-regex': 'off',
      // 正则里 \[ \] 是有意的转义（citation 标记匹配），去掉反而改变语义
      'no-useless-escape': 'off',
    },
  },

  {
    // 测试与构建脚本：放宽
    files: ['**/*.test.ts', '**/*.spec.ts', 'vite.config.ts', 'tailwind.config.js'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      'no-console': 'off',
    },
  },

  // 必须放最后：关掉所有与 Prettier 冲突的格式规则
  prettier,
)
