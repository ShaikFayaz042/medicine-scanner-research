import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'

export default defineConfig({
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
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/static-pdf': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
