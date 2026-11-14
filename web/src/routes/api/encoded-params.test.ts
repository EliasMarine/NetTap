import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * NET-257 review: explicit routes that put a route param into the daemon path must encode it.
 * SvelteKit hands the param over decoded, so `..%2F..%2Fpcap%2Fdownload` arrived as `../../pcap/download`
 * and fetch walked it up to another daemon route. (Kept here: SvelteKit refuses +server.test.ts in routes/.)
 */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const fields = await import('./logs/fields/[log_type]/+server.js');
const enable = await import('./suricata/rules/sources/[id]/enable/+server.js');
const disable = await import('./suricata/rules/sources/[id]/disable/+server.js');

const call = async (handler: (e: never) => Response | Promise<Response>, params: Record<string, string>) => handler({ params } as never);

describe('explicit /api routes encode their route params', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } }));
	});

	it('logs/fields keeps a ../ inside its own segment', async () => {
		await call(fields.GET, { log_type: '../../pcap/download?filter=tcp' });
		expect(daemonFetch.mock.calls[0][0]).toBe('/api/logs/fields/..%2F..%2Fpcap%2Fdownload%3Ffilter%3Dtcp');
	});

	it('logs/fields passes an ordinary log type unchanged', async () => {
		await call(fields.GET, { log_type: 'conn' });
		expect(daemonFetch.mock.calls[0][0]).toBe('/api/logs/fields/conn');
	});

	it.each([
		['enable', enable.POST],
		['disable', disable.POST],
	])('suricata source %s keeps a ../ inside its own segment', async (action, handler) => {
		await call(handler, { id: '../../../settings' });
		expect(daemonFetch.mock.calls[0][0]).toBe(`/api/suricata/rules/sources/..%2F..%2F..%2Fsettings/${action}`);
	});
});
