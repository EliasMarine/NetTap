import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getLiveBandwidth,
	getLiveBandwidthSetting,
	setLiveBandwidthSetting,
	LiveBandwidthError,
	type LiveBandwidthResponse,
	type LiveBandwidthSetting,
} from './live-bandwidth';

function mockFetch(body: unknown, status = 200): ReturnType<typeof vi.fn> {
	const fn = vi.fn().mockResolvedValue(
		new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
	);
	vi.stubGlobal('fetch', fn);
	return fn;
}

async function caught(p: Promise<unknown>): Promise<LiveBandwidthError> {
	try {
		await p;
	} catch (e) {
		return e as LiveBandwidthError;
	}
	throw new Error('expected a rejection');
}

const UNSUPPORTED: LiveBandwidthResponse = {
	supported: false,
	reason: "In bridge mode NetTap sits in front of your router and sees only its public address, so it can't split the rate by device.",
	mode: 'bridge',
	interface: 'br0',
	key: { kind: 'ip', value: '192.168.1.5' },
};

describe('getLiveBandwidth', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('asks by MAC on the MAC page, encoding the colons', async () => {
		const fn = mockFetch(UNSUPPORTED);
		await getLiveBandwidth({ mac: 'aa:bb:cc:dd:ee:ff' });
		expect(fn.mock.calls[0][0]).toBe('/api/live-bandwidth?mac=aa%3Abb%3Acc%3Add%3Aee%3Aff');
	});

	it('asks by IP on the IP page, with only that key', async () => {
		const fn = mockFetch(UNSUPPORTED);
		const res = await getLiveBandwidth({ ip: '192.168.1.5' });
		expect(fn.mock.calls[0][0]).toBe('/api/live-bandwidth?ip=192.168.1.5');
		expect(res).toEqual(UNSUPPORTED);
	});

	it('passes the abort signal through to fetch', async () => {
		const fn = mockFetch(UNSUPPORTED);
		const ctrl = new AbortController();
		await getLiveBandwidth({ ip: '192.168.1.5' }, ctrl.signal);
		expect((fn.mock.calls[0][1] as RequestInit).signal).toBe(ctrl.signal);
	});

	it.each([
		[400, 'Give exactly one of mac= or ip=.'],
		[503, 'Too many live views are open. Close one and try again.'],
		[503, 'Starting…'],
		[500, 'tc failed: RTNETLINK answers: Operation not supported'],
	])('throws the daemon’s own reason with the status on %i', async (status, error) => {
		mockFetch({ error }, status);
		const err = await caught(getLiveBandwidth({ ip: '192.168.1.5' }));
		expect(err).toBeInstanceOf(LiveBandwidthError);
		expect(err.message).toBe(error);
		expect(err.status).toBe(status);
	});

	it('falls back to the HTTP status when the error body is not JSON', async () => {
		mockFetch('<html>Bad gateway</html>', 502);
		const err = await caught(getLiveBandwidth({ ip: '192.168.1.5' }));
		expect(err.message).toBe('HTTP 502');
		expect(err.status).toBe(502);
	});

	it('rejects a 2xx that is not the daemon’s answer', async () => {
		mockFetch('<html>login</html>');
		expect((await caught(getLiveBandwidth({ ip: '192.168.1.5' }))).message).toMatch(/unexpected reply/);
		mockFetch({ hello: 1 });
		expect((await caught(getLiveBandwidth({ ip: '192.168.1.5' }))).message).toMatch(/unexpected reply/);
	});

	it('lets an abort reject as the AbortError', async () => {
		const ctrl = new AbortController();
		vi.stubGlobal(
			'fetch',
			vi.fn((_url: string, init: RequestInit) => new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))),
		);
		const p = getLiveBandwidth({ mac: 'aa:bb:cc:dd:ee:ff' }, ctrl.signal);
		ctrl.abort();
		await expect(p).rejects.toMatchObject({ name: 'AbortError' });
	});
});

const OFF: LiveBandwidthResponse = {
	supported: false,
	off: true,
	reason: 'Live bandwidth is off. Turn it on in Settings › Capture.',
	mode: 'mirror',
	interface: 'enp4s0',
	key: { kind: 'mac', value: 'aa:bb:cc:dd:ee:ff' },
};

describe('getLiveBandwidth while the setting is off', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('returns the off reply as it came', async () => {
		mockFetch(OFF);
		expect(await getLiveBandwidth({ mac: 'aa:bb:cc:dd:ee:ff' })).toEqual(OFF);
	});
});

const SETTING: LiveBandwidthSetting = {
	enabled: false,
	supported: true,
	reason: null,
	mode: 'mirror',
	cleanup: { state: 'retrying', failed: { enp4s0: 'RTNETLINK answers: Device or resource busy' } },
};

describe('the live bandwidth setting', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('reads the setting', async () => {
		const fn = mockFetch(SETTING);
		expect(await getLiveBandwidthSetting()).toEqual(SETTING);
		expect(fn.mock.calls[0][0]).toBe('/api/settings/live-bandwidth');
	});

	it('saves with a PUT of a JSON bool and returns what the daemon now has', async () => {
		const fn = mockFetch({ ...SETTING, enabled: true });
		expect((await setLiveBandwidthSetting(true)).enabled).toBe(true);
		const [url, init] = fn.mock.calls[0] as [string, RequestInit];
		expect(url).toBe('/api/settings/live-bandwidth');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(String(init.body))).toEqual({ enabled: true });
	});

	it('carries the unchanged value from a failed save', async () => {
		mockFetch({ error: "Couldn't save the setting: disk full.", enabled: true }, 500);
		const err = await caught(setLiveBandwidthSetting(false));
		expect(err).toBeInstanceOf(LiveBandwidthError);
		expect(err.message).toBe("Couldn't save the setting: disk full.");
		expect(err.status).toBe(500);
		expect(err.enabled).toBe(true);
	});

	it('has no value when the reply gave none', async () => {
		mockFetch({ error: 'enabled must be true or false.' }, 400);
		const err = await caught(setLiveBandwidthSetting(true));
		expect(err.status).toBe(400);
		expect(err.enabled).toBeUndefined();
	});

	it.each([
		['not JSON', '<html>login</html>'],
		['no enabled', { ...SETTING, enabled: undefined }],
		['a string for enabled', { ...SETTING, enabled: 'true' }],
		['no cleanup', { ...SETTING, cleanup: undefined }],
		['an unknown clean-up state', { ...SETTING, cleanup: { state: 'done', failed: {} } }],
		['a failure that is not text', { ...SETTING, cleanup: { state: 'retrying', failed: { enp4s0: 1 } } }],
	])('rejects a reply with %s', async (_, body) => {
		mockFetch(body);
		expect((await caught(getLiveBandwidthSetting())).message).toMatch(/unexpected reply/);
	});
});
