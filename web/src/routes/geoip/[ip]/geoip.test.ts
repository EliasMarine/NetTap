import { describe, it, expect } from 'vitest';

describe('GeoIP Lookup Page', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});
