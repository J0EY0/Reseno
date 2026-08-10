import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const backendTarget =
  process.env.VITE_DEV_API_TARGET ?? 'http://127.0.0.1:8000'
const viteCacheDir =
  process.env.RESUMATE_VITE_CACHE_DIR ?? 'node_modules/.vite'
const __dirname = path.dirname(fileURLToPath(import.meta.url))

function isNodePackage(id: string, packageName: string) {
  const escapedPackageName = packageName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const packagePattern = new RegExp(
    `/node_modules/(?:\\.pnpm/[^/]+/node_modules/)?${escapedPackageName}/`,
  )

  return packagePattern.test(id)
}

// https://vite.dev/config/
export default defineConfig({
  cacheDir: viteCacheDir,
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 480,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (
            id.includes('react-jsx-runtime') ||
            id.includes('/react/jsx-runtime') ||
            id.includes('/react/cjs/react-jsx-runtime')
          ) {
            return 'vendor-react'
          }

          if (!id.includes('node_modules')) {
            return
          }

          if (id.includes('/@emotion/')) {
            return
          }

          if (
            isNodePackage(id, 'react') ||
            isNodePackage(id, 'react-dom') ||
            isNodePackage(id, 'react-router') ||
            isNodePackage(id, 'react-router-dom') ||
            isNodePackage(id, 'scheduler')
          ) {
            return 'vendor-react'
          }

          if (
            id.includes('/shiki/') ||
            id.includes('/@shikijs/')
          ) {
            return 'vendor-shiki'
          }

          if (
            id.includes('/streamdown/') ||
            id.includes('/@streamdown/') ||
            id.includes('/mermaid/') ||
            id.includes('/katex/')
          ) {
            return
          }

          if (
            id.includes('/@lobehub/') ||
            id.includes('/antd-style/') ||
            id.includes('/@ant-design/')
          ) {
            return
          }

          if (id.includes('/@tiptap/') || id.includes('/prosemirror-')) {
            return
          }

          if (
            id.includes('/@radix-ui/') ||
            id.includes('/radix-ui/') ||
            id.includes('/cmdk/')
          ) {
            return
          }

          if (
            id.includes('/lucide-react/') ||
            id.includes('/@icons-pack/')
          ) {
            return
          }

          if (id.includes('/@tanstack/')) {
            return
          }

          if (id.includes('/html2canvas/')) {
            return 'vendor-html2canvas'
          }

          if (
            id.includes('/jspdf/') ||
            id.includes('/dompurify/') ||
            id.includes('/fflate/') ||
            id.includes('/canvg/') ||
            id.includes('/raf/') ||
            id.includes('/rgbcolor/') ||
            id.includes('/stackblur-canvas/')
          ) {
            return 'vendor-jspdf'
          }
          return
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
