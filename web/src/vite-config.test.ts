import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'fs';
import { resolve } from 'path';

/**
 * vite.config.ts is a build tool config that can't be imported directly
 * in jsdom (esbuild + TextEncoder incompatibility). Instead, we validate
 * the config file's content as text to ensure expected settings are present.
 */
describe('vite.config', () => {
	const configPath = resolve(__dirname, '../vite.config.ts');
	const content = readFileSync(configPath, 'utf-8');

	it('imports sveltekit plugin', () => {
		expect(content).toContain("from '@sveltejs/kit/vite'");
		// OLD CODE: expect(content).toContain('sveltekit()'); (kit 3: the SvelteKit config is now the plugin's argument; NET-315)
		expect(content).toContain('sveltekit({');
	});

	// kit 3 refuses to build while svelte.config.js exists, so its options live here (NET-315)
	it('configures adapter-node and the import aliases on the sveltekit plugin', () => {
		expect(content).toContain("from '@sveltejs/adapter-node'");
		expect(content).toMatch(/adapter: adapter\(\{\s*out: 'build',\s*precompress: true,/);
		expect(content).toContain("$lib: 'src/lib'");
		expect(content).toContain("$components: 'src/lib/components'");
		expect(content).toContain("$api: 'src/lib/api'");
		expect(existsSync(resolve(__dirname, '../svelte.config.js'))).toBe(false);
	});

	it('configures vitest test settings', () => {
		// OLD CODE: expect(content).toContain("include: ['src/**/*.{test,spec}.{js,ts}', 'e2e/visual/**/*.test.ts']"); (the visual config's own test joined the list)
		expect(content).toContain("include: ['src/**/*.{test,spec}.{js,ts}', 'e2e/visual/**/*.test.ts', 'playwright.visual.config.test.ts']");
		expect(content).toContain("environment: 'jsdom'");
		expect(content).toContain("setupFiles: ['src/tests/setup.ts']");
	});

	it('sets dev server port to 3000', () => {
		expect(content).toContain('port: 3000');
	});

	it('includes browser resolve condition for Svelte 5', () => {
		expect(content).toContain("conditions: ['browser']");
	});

	it('imports defineConfig from vitest', () => {
		expect(content).toContain("from 'vitest/config'");
		expect(content).toContain('defineConfig');
	});
});
