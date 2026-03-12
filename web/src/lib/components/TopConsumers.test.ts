import { describe, it, expect } from 'vitest';

describe('TopConsumers', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./TopConsumers.svelte');
		expect(module.default).toBeDefined();
	});
});
