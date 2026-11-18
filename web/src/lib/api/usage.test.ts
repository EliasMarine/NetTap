import { describe, it, expect, vi, afterEach } from 'vitest';
import { getTimezone, getUsageMonth, hasFigures, setTimezone, type UsageDayStatus } from './usage';

// F4 (NET-329): the usage ledger's client, against plans/2026-11-18-f4-usage-ledger.md §4.5 and §4.1

function reply(body: unknown, status = 200): void {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) }));
}

const call = (n = 0) => vi.mocked(fetch).mock.calls[n] as [string, RequestInit | undefined];

afterEach(() => vi.unstubAllGlobals());

describe('getUsageMonth', () => {
	it("asks for the owner's current month, leaving the month to the daemon", async () => {
		const month = { tz: 'America/Los_Angeles', year: 2026, month: 11, days: [], bytes: { download: 0, upload: 0, local: 0, total: 0 } };
		reply(month);
		expect(await getUsageMonth()).toEqual(month);
		expect(call()[0]).toBe('/api/usage/month');
	});

	it('throws on a failed request, so the page shows its error state instead of 0 GB', async () => {
		reply({}, 503);
		await expect(getUsageMonth()).rejects.toThrow('Monthly usage failed: HTTP 503');
	});

	it('refuses a reply without its days or its bytes, instead of drawing an empty month', async () => {
		reply({ tz: 'UTC', bytes: { download: 0, upload: 0, local: 0, total: 0 } });
		await expect(getUsageMonth()).rejects.toThrow("Monthly usage failed: the reply wasn't a month");
		reply({ tz: 'UTC', days: [] });
		await expect(getUsageMonth()).rejects.toThrow("Monthly usage failed: the reply wasn't a month");
		reply(null);
		await expect(getUsageMonth()).rejects.toThrow("Monthly usage failed: the reply wasn't a month");
	});
});

describe('getTimezone', () => {
	it('reads the zone and whether the owner picked it', async () => {
		reply({ tz: 'Europe/London', set: true });
		expect(await getTimezone()).toEqual({ tz: 'Europe/London', set: true });
		expect(call()[0]).toBe('/api/settings/timezone');
	});

	it('an unpicked zone is not set', async () => {
		reply({ tz: 'UTC', set: false });
		expect(await getTimezone()).toEqual({ tz: 'UTC', set: false });
	});

	it('refuses a reply with no zone, and a failed request', async () => {
		reply({});
		await expect(getTimezone()).rejects.toThrow('the reply named no zone');
		reply({}, 502);
		await expect(getTimezone()).rejects.toThrow('Time zone failed: HTTP 502');
	});
});

describe('setTimezone', () => {
	it('PUTs the zone and returns it as set', async () => {
		reply({ tz: 'America/Los_Angeles', set: true });
		expect(await setTimezone('America/Los_Angeles')).toEqual({ ok: true, data: { tz: 'America/Los_Angeles', set: true } });
		const [url, init] = call();
		expect(url).toBe('/api/settings/timezone');
		expect(init?.method).toBe('PUT');
		expect(JSON.parse(String(init?.body))).toEqual({ tz: 'America/Los_Angeles' });
	});

	it("gives the daemon's reason for a zone it refuses", async () => {
		reply({ error: "That isn't a time zone NetTap knows" }, 400);
		expect(await setTimezone('Mars/Olympus')).toEqual({ ok: false, error: "That isn't a time zone NetTap knows" });
	});

	it('names the status when the refusal has no reason, and says when NetTap is unreachable', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json: () => Promise.reject(new Error('no body')) }));
		expect(await setTimezone('UTC')).toEqual({ ok: false, error: 'HTTP 500' });
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		expect(await setTimezone('UTC')).toEqual({ ok: false, error: "couldn't reach NetTap" });
	});
});

describe('hasFigures', () => {
	it('every status but future, not counted and pending carries figures (§4.5 bytes)', () => {
		const all: UsageDayStatus[] = ['future', 'not_counted', 'stale', 'pending', 'recount_pending', 'old_rules', 'approximate', 'counted'];
		expect(all.filter((status) => hasFigures({ status }))).toEqual(['stale', 'recount_pending', 'old_rules', 'approximate', 'counted']);
	});
});
