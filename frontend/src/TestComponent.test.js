import { render, screen } from '@testing-library/svelte'
import { describe, it, expect } from 'vitest'
import TestComponent from './TestComponent.svelte'

describe('TestComponent', () => {
  it('should render hello text', () => {
    render(TestComponent)
    const element = screen.getByTestId('test-component')
    expect(element).toHaveTextContent('Hello Test')
  })
}) 