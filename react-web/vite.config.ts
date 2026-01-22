/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  envPrefix: ['VITE_', 'REACT_APP_'],
  define: {
    global: 'globalThis',
    'process.env': {},
  },
  resolve: {
    alias: {
      // Node.js polyfills for browser
      buffer: 'buffer',
      process: 'process/browser',
      util: 'util',
      stream: 'stream-browserify',
      crypto: 'crypto-browserify',
      path: 'path-browserify',
      url: 'url',
      assert: 'assert',
      querystring: 'querystring-es3',
      events: 'events',
      os: 'os-browserify',
      constants: 'constants-browserify',
    },
  },
  optimizeDeps: {
    include: [
      'buffer',
      'process/browser',
      'util',
      'stream-browserify',
      'crypto-browserify',
      'path-browserify',
      'url',
      'assert',
      'querystring-es3',
      'events',
      'os-browserify',
      'constants-browserify',
    ],
  },
  build: {
    rollupOptions: {
      external: [],
    },
  },
  server: {
    port: 3000,
    open: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})