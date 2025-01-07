import { flushSync } from 'svelte';
import { expect, test } from 'vitest';
import { multiplier } from './multiplier';

/* 
npx sv create frontend-2
cd frontend-2
npm install
npm install -D vitest

vite.config.ts
import { defineConfig } from 'vite'; -> import { defineConfig } from 'vitest/config';

	resolve: process.env.VITEST
		? {
			conditions: ['browser']
		}
		: undefined
*/

// npm run test
// https://svelte.dev/docs/svelte/testing
test('Multiplier', () => {
	let value = multiplier(0, 2);

	expect(value).toEqual(0);

	value = multiplier(5, 5);

	expect(value).toEqual(25);
});