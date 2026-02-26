import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [sveltekit()],
	test: {
		include: ['src/**/*.{test,spec}.{js,ts}'],
		environment: 'jsdom',
		setupFiles: ['src/tests/setup.ts'],
	},
	resolve: {
		// Svelte 5 uses export conditions — "browser" must be present so that
		// the client-side mount() is resolved instead of the server-only stubs.
		conditions: ['browser'],
	},
	server: {
		port: 3000,
	},
});
