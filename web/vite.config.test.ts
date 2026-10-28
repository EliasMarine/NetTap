import { describe, it, expect } from 'vitest';

describe('Vite Config', () => {
	it('should be importable', async () => {
		const mod = await import('./vite.config');
		expect(mod).toBeDefined();
	});
});
