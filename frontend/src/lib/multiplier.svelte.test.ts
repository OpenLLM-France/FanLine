import { expect, test } from 'vitest';
import { multiplier } from './multiplier';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Counter from './Counter.svelte';

test('Counter fonctionne correctement', async () => {
    const { getByRole } = render(Counter);
    const button = getByRole('button');
    
    expect(button.textContent?.trim() ?? '').toBe('0');
    
    await fireEvent.click(button);
    expect(button.textContent?.trim() ?? '').toBe('1');
});

test('Multiplier', () => {
    let value = multiplier(0, 2);
    expect(value).toEqual(0);

    value = multiplier(5, 5);
    expect(value).toEqual(25);
});