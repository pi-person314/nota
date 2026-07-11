import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // 127.0.0.1, not localhost: Flask's dev server binds IPv4 only, and
      // on some setups "localhost" resolves to the IPv6 loopback first,
      // which the proxy then fails to connect to.
      '/api': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true,
      },
    },
  },
  optimizeDeps: {
    exclude: ['verovio'],
  },
})
