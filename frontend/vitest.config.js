import { defineConfig } from 'vitest/config'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [
    svelte({
      compilerOptions: {
        hydratable: true
      }
    })
  ],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.js'],
    include: ['src/**/*.{test,spec}.{js,ts}'],
    deps: {
      optimizer: {
        web: {
          include: [/svelte/, /@testing-library\/svelte/]
        }
      }
    }
  },
  cacheDir: './.vite'
}) 