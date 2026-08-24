import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 127.0.0.1, not localhost: Flask's dev server binds IPv4 only, and on some
// setups "localhost" resolves to the IPv6 loopback first, which the proxy
// then fails to connect to.
const apiProxy = {
  '/api': {
    target: 'http://127.0.0.1:5001',
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: apiProxy,
  },
  // `vite preview` serves the real production bundle — minified, bundled,
  // and built exactly as the deployed image builds it — so it needs the
  // same API proxy the dev server has. Without this, the only way to
  // exercise a production build is to deploy one, which makes anything
  // that behaves differently between dev and production slow to diagnose.
  preview: {
    proxy: apiProxy,
  },
  optimizeDeps: {
    exclude: ['verovio'],
  },
})
