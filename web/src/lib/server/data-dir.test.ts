import { afterEach, describe, it, expect, vi } from 'vitest';

describe('DATA_DIR', () => {
	afterEach(() => vi.unstubAllEnvs());

	it('is the web-data volume unless DATA_DIR moves it', async () => {
		vi.stubEnv('DATA_DIR', '');
		vi.resetModules();
		expect((await import('./data-dir')).DATA_DIR).toBe('/var/lib/nettap-web');

		vi.stubEnv('DATA_DIR', '/srv/nettap-web');
		vi.resetModules();
		expect((await import('./data-dir')).DATA_DIR).toBe('/srv/nettap-web');
	});
});
