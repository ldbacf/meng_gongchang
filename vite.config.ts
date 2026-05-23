import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import fs from 'fs'
import path from 'path'

const pdfDir = resolve(__dirname, 'pdf')

function pdfMiddlewarePlugin() {
  return {
    name: 'vite-pdf-middleware',
    configureServer(server: any) {
      server.middlewares.use('/api/pdf/', (req: any, res: any) => {
        try {
          const files = fs.readdirSync(pdfDir).filter((f: string) => f.endsWith('.pdf'))
          const urlParts = req.url?.split('/') ?? []
          const lastSegment = urlParts[urlParts.length - 1]
          const fileIndex = parseInt(lastSegment, 10)
          if (isNaN(fileIndex) || fileIndex < 1 || fileIndex > files.length) {
            res.statusCode = 404
            res.end('PDF not found')
            return
          }
          const filePath = path.join(pdfDir, files[fileIndex - 1])
          const data = fs.readFileSync(filePath)
          res.setHeader('Content-Type', 'application/pdf')
          res.setHeader('Content-Length', data.length)
          res.end(data)
        } catch {
          res.statusCode = 500
          res.end('Failed to read PDF')
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [vue(), pdfMiddlewarePlugin()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8005',
        changeOrigin: true,
      },
    },
  },
})
