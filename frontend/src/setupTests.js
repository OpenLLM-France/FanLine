import { vi } from 'vitest'
import '@testing-library/jest-dom'

// Mock simple des fonctions de cycle de vie
const mockFn = () => vi.fn()

// Mock de svelte
vi.mock('svelte', () => ({
  onMount: mockFn(),
  beforeUpdate: mockFn(),
  afterUpdate: mockFn(),
  onDestroy: mockFn(),
  tick: mockFn()
}))

// Mock de svelte/internal
vi.mock('svelte/internal', () => ({
  createEventDispatcher: mockFn()
})) 