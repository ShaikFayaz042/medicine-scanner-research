import { defineConfig } from 'vite'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'

export default defineConfig(({ mode }) => {
  const clientRoot = fileURLToPath(new URL('.', import.meta.url))
  const env = loadEnv(mode, clientRoot, '')
  const serverUrl = env.VITE_SERVER_URL || 'http://localhost:8000'

  return {
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
    dedupe: [
      '@radix-ui/react-slot',
      '@tanstack/react-router',
      '@xyflow/react',
      'class-variance-authority',
      'clsx',
      'lucide-react',
      'react',
      'react-dom',
      'tailwind-merge',
    ],
  },
  plugins: [
    react(),
    tailwindcss(),
  ],
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('./index.html', import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: serverUrl,
        changeOrigin: true,
        ws: true,
      },
      '/auth': {
        target: serverUrl,
        changeOrigin: true,
      },
      '/scans': {
        target: serverUrl,
        changeOrigin: true,
      },
      '/health': {
        target: serverUrl,
        changeOrigin: true,
      },
      '/static-pdf': {
        target: serverUrl,
        changeOrigin: true,
      },
    },
  },
  }
})
