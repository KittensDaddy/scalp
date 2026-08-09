import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Bind every interface by default. Vite otherwise listens on localhost only,
    // so http://<miniserver-ip>:5173 from a laptop just times out with no error
    // anywhere — the most common "can't reach the dashboard" cause.
    host: true,
    port: 5173,
    strictPort: true,
  },
})
