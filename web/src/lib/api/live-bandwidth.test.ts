import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getLiveBandwidth,
	getLiveBandwidthSetting,
	setLiveBandwidthSetting,
	LiveBandwidthError,
	keepMeasured,
	type LiveBandwidthResponse,
	type LiveBandwidthSample,
	type LiveBandwidthSupported,
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

	it('rejects a measuring reply without its samples, interval or interface', async () => {
		for (const half of [{ supported: true }, { supported: true, samples: [], interval_s: 2 }, { supported: true, samples: {}, interval_s: 2, interface: 'enp4s0' }]) {
			mockFetch(half);
			expect((await caught(getLiveBandwidth({ ip: '192.168.1.5' }))).message).toMatch(/unexpected reply/);
		}
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

// chart gaps: a recreated watch reports "Not measuring yet." for slots this card already measured
describe('keepMeasured', () => {
	const T0 = 1_794_809_620_000;
	/** Slot `tick` read at wall time `t` (ms) and daemon time `mono` (s), with a rate or with none. */
	const slot = (tick: number, t: number | null, mono: number | null, bps: number | null, reason: string | null = null): LiveBandwidthSample => ({
		tick,
		t,
		mono,
		bracket_ms: t === null ? null : 5,
		down_bps: bps,
		up_bps: bps === null ? null : bps / 2,
		reason: bps === null ? (reason ?? 'Not measuring yet.') : null,
	});
	const reply = (samples: LiveBandwidthSample[], extra: Partial<LiveBandwidthSupported> = {}): LiveBandwidthSupported => ({
		supported: true,
		reason: null,
		mode: 'mirror',
		interface: 'enp1s0',
		key: { kind: 'ip', value: '192.168.1.5' },
		layer: 'ethernet-payload',
		offloads: { gro: false, lro: false },
		interval_s: 2,
		latest: samples.at(-1) ?? null,
		latest_age_s: 0.2,
		last_valid_age_s: 0.2,
		measuring_since: T0,
		samples,
		...extra,
	});
	/** Ticks 100–104 on the daemon's grid, 2 s apart, all measured. */
	const measured = () => [0, 1, 2, 3, 4].map((k) => slot(100 + k, T0 + k * 2000, 5000 + k * 2, 1000 * (k + 1)));
	const rates = (r: LiveBandwidthSupported) => r.samples.map((s) => s.down_bps);

	it('returns the reply as it is with nothing earlier', () => {
		const next = reply(measured());
		expect(keepMeasured(null, next)).toBe(next);
	});

	it('keeps the earlier rates after an idle watch is recreated: same ticks, same t and mono, now "Not measuring yet."', () => {
		const prev = reply(measured());
		// 20 s unpolled: the new watch starts at tick 110; its earlier slots repeat the shared tick times with no rate
		const next = reply([...measured().map((s) => slot(s.tick, s.t, s.mono, null)), slot(110, T0 + 20_000, 5020, null, 'Measuring…'), slot(111, T0 + 22_000, 5022, 7000)]);
		expect(rates(keepMeasured(prev, next))).toEqual([1000, 2000, 3000, 4000, 5000, null, 7000]);
	});

	it('a rate in the new reply wins over the earlier one', () => {
		const prev = reply(measured());
		const next = reply(measured().map((s, k) => (k === 2 ? slot(s.tick, s.t, s.mono, 9999) : s)));
		expect(rates(keepMeasured(prev, next))[2]).toBe(9999);
	});

	it('shifted grid: two earlier samples near one new slot stay a gap, neither is chosen', () => {
		const prev = reply([slot(5, T0 + 10_100, 10.1, 111), slot(6, T0 + 11_900, 11.9, 222)]);
		const next = reply([slot(5, T0 + 11_000, 11, null), slot(6, T0 + 13_000, 13, null)]);
		expect(rates(keepMeasured(prev, next))).toEqual([null, null]);
	});

	it('shifted grid: one earlier sample between two new slots is drawn in neither', () => {
		const prev = reply([slot(5, T0 + 10_000, 10, 111)]);
		const next = reply([slot(4, T0 + 9_000, 9, null), slot(5, T0 + 11_000, 11, null)]);
		expect(rates(keepMeasured(prev, next))).toEqual([null, null]);
	});

	it('a daemon restart whose ticks overlap the earlier ones keeps nothing', () => {
		const prev = reply(measured());
		// a new daemon: the same tick numbers, read at other times (or not read at all)
		const next = reply(measured().map((s, k) => slot(s.tick, k < 2 ? null : T0 + 400_000 + k * 2000, k < 2 ? null : 9000 + k * 2, null)));
		expect(rates(keepMeasured(prev, next))).toEqual([null, null, null, null, null]);
	});

	it('the same t with another mono, or no t, stays a gap', () => {
		const prev = reply(measured());
		const next = reply(measured().map((s, k) => slot(s.tick, k === 0 ? null : s.t, k === 1 ? 1 : s.mono, null)).slice(0, 2));
		expect(rates(keepMeasured(prev, next))).toEqual([null, null]);
	});

	it('keeps nothing for another interface, interval or device', () => {
		const prev = reply(measured());
		const gaps = measured().map((s) => slot(s.tick, s.t, s.mono, null));
		for (const extra of [{ interface: 'enp2s0' }, { interval_s: 4 }, { key: { kind: 'ip' as const, value: '192.168.1.6' } }, { key: { kind: 'mac' as const, value: '192.168.1.5' } }]) {
			const next = reply(gaps, extra);
			expect(keepMeasured(prev, next)).toBe(next);
		}
	});

	it('changes neither reply', () => {
		const prev = reply(measured());
		const next = reply(measured().map((s) => slot(s.tick, s.t, s.mono, null)));
		const before = [JSON.stringify(prev), JSON.stringify(next)];
		const out = keepMeasured(prev, next);
		expect([JSON.stringify(prev), JSON.stringify(next)]).toEqual(before);
		expect(out).not.toBe(next);
		expect(out.samples).not.toBe(next.samples);
	});
});
