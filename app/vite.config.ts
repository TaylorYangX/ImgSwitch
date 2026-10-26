import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// One build serves both the Tauri window and `python main.py --gui` (which serves imgswitch/gui/dist).
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  base: './',
  clearScreen: false,
  build: {
    outDir: '../imgswitch/gui/dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    port: 1420,
    strictPort: true,
    // `npm run dev` in a browser talks to a dashboard started with `python main.py --gui`.
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
})
