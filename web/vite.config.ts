import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-node';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

// OLD CODE START — kit 3 refuses to build while svelte.config.js exists; its options moved into sveltekit({...}) below (NET-315)
// svelte.config.js:
// import adapter from '@sveltejs/adapter-node';
// import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
//
// /** @type {import('@sveltejs/kit').Config} */
// const config = {
// 	preprocess: vitePreprocess(),
// 	kit: {
// 		adapter: adapter({
// 			out: 'build',
// 			precompress: true,
// 		}),
// 		alias: {
// 			'$components': 'src/lib/components',
// 			'$api': 'src/lib/api',
// 		},
// 	},
// };
//
// export default config;
//
// vite.config.ts:
// 	plugins: [sveltekit()],
// OLD CODE END

export default defineConfig({
	plugins: [
		sveltekit({
			preprocess: vitePreprocess(),
			adapter: adapter({
				out: 'build',
				precompress: true,
			}),
			// shortcut: `alias` is deprecated in kit 3 and $lib is gone unless re-added here; move to `#lib` subpath imports when the alias is removed
			alias: {
				$lib: 'src/lib',
				$components: 'src/lib/components',
				$api: 'src/lib/api',
			},
		}),
	],
	test: {
		// e2e/visual: unit tests of the visual harness's own helpers and fixtures, and of its config
		include: ['src/**/*.{test,spec}.{js,ts}', 'e2e/visual/**/*.test.ts', 'playwright.visual.config.test.ts'],
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
