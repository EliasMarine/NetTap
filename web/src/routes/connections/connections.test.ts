import { describe, it, expect } from 'vitest';

describe('Connections v3 page', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});
