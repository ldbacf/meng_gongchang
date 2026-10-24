/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)'],
        mono: ['var(--font-mono)'],
      },
      // 语义色：全部指向 design tokens，暗色模式只改变量、不改类名。
      // 注意：CSS 变量做色值时不能用 bg-surface/50 这类透明度修饰。
      colors: {
        canvas: 'var(--bg)',
        surface: 'var(--surface)',
        'surface-2': 'var(--surface-2)',
        hover: 'var(--surface-hover)',
        line: 'var(--border)',
        'line-strong': 'var(--border-strong)',
        ink: 'var(--text)',
        'ink-2': 'var(--text-2)',
        muted: 'var(--muted)',
        faint: 'var(--faint)',
        accent: {
          DEFAULT: 'var(--accent)',
          hover: 'var(--accent-hover)',
          soft: 'var(--accent-soft)',
          text: 'var(--accent-text)',
        },
        ok: { DEFAULT: 'var(--ok)', soft: 'var(--ok-soft)' },
        warn: { DEFAULT: 'var(--warn)', soft: 'var(--warn-soft)' },
        danger: { DEFAULT: 'var(--danger)', soft: 'var(--danger-soft)' },
        // 兼容旧组件里的 primary-* / slate-*，随组件重写逐步移除
        primary: {
          50: 'var(--accent-soft)',
          100: 'var(--accent-soft)',
          200: 'var(--border-strong)',
          300: 'var(--border-strong)',
          400: 'var(--accent)',
          500: 'var(--accent)',
          600: 'var(--accent)',
          700: 'var(--accent-hover)',
          800: 'var(--accent-hover)',
          900: 'var(--accent-text)',
          950: 'var(--accent-text)',
        },
        slate: {
          50: 'var(--surface)',
          100: 'var(--surface)',
          200: 'var(--border)',
          300: 'var(--border-strong)',
          400: 'var(--faint)',
          500: 'var(--muted)',
          600: 'var(--muted)',
          700: 'var(--text-2)',
          800: 'var(--text)',
          900: 'var(--text)',
        },
      },
      borderRadius: {
        lg: 'var(--r-md)',
        xl: 'var(--r-lg)',
        '2xl': 'var(--r-xl)',
        '3xl': 'var(--r-2xl)',
      },
      boxShadow: {
        sm: 'var(--sh-1)',
        DEFAULT: 'var(--sh-1)',
        md: 'var(--sh-2)',
        lg: 'var(--sh-3)',
      },
      maxWidth: {
        chat: 'var(--col)',
      },
    },
  },
  plugins: [],
}
