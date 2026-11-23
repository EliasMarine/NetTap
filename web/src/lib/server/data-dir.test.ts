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

	// NET-358: a built server started by hand must find the owner and retire the right key, so no dev default here
	it.each([
		['unset', ''],
		['production', 'production'],
		['development', 'development'],
	])('falls back to the volume with NODE_ENV %s', async (_, nodeEnv) => {
		vi.stubEnv('DATA_DIR', '');
		vi.stubEnv('NODE_ENV', nodeEnv);
		vi.resetModules();
		expect((await import('./data-dir')).DATA_DIR).toBe('/var/lib/nettap-web');
	});
});
