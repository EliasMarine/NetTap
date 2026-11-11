import { describe, it, expect, vi, afterEach } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { DISPLAY_SETTINGS_KEY, savedDefaultRange, savedLiveMap, startRange, alertsHrefForSignature, byteFigure, fitCount, countDifference, linkedCount, withCount, canonicalName, certificatesHref, chartTime, connLogsHref, customRange, isHostName, logsHrefForIp, logsHrefForQuery, measuredNote, rangeWindow, SCAN_CAP, smartAlertHref, partialListNote, suricataAlertsHref, suricataCategoryHref, windowQuery } from './drilldown';

const MB = 1000 ** 2; // decimal, as formatBytes prints (NET-166)

describe('drill-down wording', () => {
	it('says Not measured when no connection carried a byte count', () => {
		expect(byteFigure({ total: 0, measured: 0, connections: 120, partial: true })).toBe('Not measured');
		expect(measuredNote({ total: 0, measured: 0, connections: 120, partial: true })).toBeNull();
	});

	it('gives a partial total as a lower bound, with how many were measured', () => {
		const b = { total: 3 * MB, measured: 118, connections: 120, partial: true };
		expect(byteFigure(b)).toBe('at least 3.0 MB');
		expect(measuredNote(b)).toBe('118 of 120 connections measured');
	});

	it('gives a complete total as it is, with no note', () => {
		const b = { total: 3 * MB, measured: 120, connections: 120, partial: false };
		expect(byteFigure(b)).toBe('3.0 MB');
		expect(measuredNote(b)).toBeNull();
	});

	it('counts no connections as a measured 0 B', () => {
		expect(byteFigure({ total: 0, measured: 0, connections: 0, partial: false })).toBe('0 B');
	});

	it('builds the window ending now', () => {
		const now = new Date('2026-11-06T12:00:00Z');
		expect(rangeWindow(24, now)).toEqual({ from: '2026-11-05T12:00:00.000Z', to: '2026-11-06T12:00:00.000Z' });
	});

	it('links certificates with the site, server and window', () => {
		const href = certificatesHref({ site: 'example.com', server: '2001:db8::1', from: 'a', to: 'b' });
		const url = new URL(href, 'http://x');
		expect(url.pathname).toBe('/certificates');
		expect(Object.fromEntries(url.searchParams)).toEqual({ site: 'example.com', server: '2001:db8::1', from: 'a', to: 'b' });
		expect(certificatesHref({ site: null, server: '1.2.3.4', from: 'a', to: 'b' })).toBe('/certificates?server=1.2.3.4&from=a&to=b');
	});

	it('canonicalises the site name as recorded, so both spellings filter the same', () => {
		expect(certificatesHref({ site: 'Example.COM.', from: 'a', to: 'b' })).toBe('/certificates?site=example.com&from=a&to=b');
	});

	it('labels timeline points for the bucket size the daemon picks', () => {
		const t = '2026-11-06T18:00:00Z';
		expect(chartTime(t, 24)).toMatch(/^\d\d:\d\d$/);
		expect(chartTime(t, 168)).toMatch(/^6 Nov, \d\d:\d\d$/);
		expect(chartTime(t, 720)).toBe('6 Nov');
	});

	it('searches Log Explorer for either side, quoted', () => {
		// OLD CODE START: expect(decodeURIComponent(logsHrefForIp('2001:db8::1').split('=')[1])).toBe(…); OLD CODE END
		const url = new URL(logsHrefForIp('2001:db8::1', '7d'), 'http://x');
		expect(url.searchParams.get('query')).toBe('(source.ip:"2001:db8::1" OR destination.ip:"2001:db8::1")');
		// Log Explorer opens on the window the link came from, not its own 24 hours
		expect(url.searchParams.get('range')).toBe('7d');
	});

	it('canonicalises a name as the daemon matches it, and knows a host name by its rule', () => {
		expect(canonicalName(' Example.COM. ')).toBe('example.com');
		expect(canonicalName('example.com..')).toBe('example.com.');
		for (const ok of ['example.com', 'Stream.Example.NET.', '_dmarc.example.org', 'a-b.c']) expect(isHostName(ok)).toBe(true);
		for (const bad of ['', '(no name)', 'a..b', 'exa mple.com', 'x'.repeat(64) + '.com', 'example.com:443']) expect(isHostName(bad)).toBe(false);
	});
});

// NET-160 slice 2a: a count links to a list over the count's own window
describe('exact-window links', () => {
	const win = { from: '2026-11-05T13:02:00.000Z', to: '2026-11-06T13:02:00.000Z' };
	const params = (href: string) => new URL(href, 'http://x').searchParams;

	it('writes the window, and the range when given', () => {
		expect(Object.fromEntries(new URLSearchParams(windowQuery(win, '24h')))).toEqual({ ...win, range: '24h' });
		expect(Object.fromEntries(new URLSearchParams(windowQuery(win)))).toEqual(win);
	});

	it('links a signature to the alerts list, with or without a window', () => {
		const sig = 'ET POLICY "odd" & 100% <name>';
		expect(new URL(alertsHrefForSignature(sig), 'http://x').pathname).toBe('/alerts');
		expect(Object.fromEntries(params(alertsHrefForSignature(sig)))).toEqual({ signature: sig });
		expect(Object.fromEntries(params(alertsHrefForSignature(sig, { ...win, range: '7d' })))).toEqual({ signature: sig, ...win, range: '7d' });
	});

	it("narrows a signature link to one device when the count is that device's", () => {
		// OLD CODE: alertsHrefForSignature('ET SCAN x', { ...win, range: '24h' }, '2001:db8::1') (slice 2b-1: the narrowing is an object)
		expect(Object.fromEntries(params(alertsHrefForSignature('ET SCAN x', { ...win, range: '24h' }, { ip: '2001:db8::1' })))).toEqual({ signature: 'ET SCAN x', ip: '2001:db8::1', ...win, range: '24h' });
	});

	it('narrows a signature link to a source and destination, leaving out empty filters', () => {
		const href = alertsHrefForSignature('ET SCAN x', { ...win, range: '6h' }, { ip: '', src: '192.168.1.20', dst: '2001:db8::1' });
		expect(Object.fromEntries(params(href))).toEqual({ signature: 'ET SCAN x', src: '192.168.1.20', dst: '2001:db8::1', ...win, range: '6h' });
		expect(params(alertsHrefForSignature('ET SCAN x', win, { ip: '10.0.0.1', src: undefined })).has('src')).toBe(false);
	});

	it("links a smart alert by its bucket key, never its displayed signature, and not at all when a part is missing", () => {
		const key = { rule_name: 'ET SCAN rule', source_ip: '192.168.1.20', destination_ip: '93.184.216.34' };
		expect(Object.fromEntries(params(smartAlertHref(key, { ...win, range: '24h' }, '192.168.1.20') ?? ''))).toEqual({
			signature: 'ET SCAN rule',
			ip: '192.168.1.20',
			src: '192.168.1.20',
			dst: '93.184.216.34',
			...win,
			range: '24h',
		});
		expect(params(smartAlertHref(key, win) ?? '').has('ip')).toBe(false);
		for (const part of ['rule_name', 'source_ip', 'destination_ip'] as const) {
			expect(smartAlertHref({ ...key, [part]: null }, win)).toBeNull();
			expect(smartAlertHref({ ...key, [part]: '' }, win)).toBeNull();
		}
		expect(smartAlertHref(undefined, win)).toBeNull();
	});

	it('links an activity group to the activity list, and a counted group without it (NET-191)', () => {
		const key = { rule_name: 'ET INFO STUN', source_ip: '192.168.1.20', destination_ip: '93.184.216.34' };
		expect(params(smartAlertHref(key, win, '192.168.1.20', true) ?? '').get('activity')).toBe('true');
		expect(params(smartAlertHref(key, win, undefined, false) ?? '').has('activity')).toBe(false);
		expect(smartAlertHref({ ...key, rule_name: null }, win, undefined, true)).toBeNull();
	});

	it("links a traffic summary's conn records with its window and its excluded sources", () => {
		const href = connLogsHref({ ...win, excluded_ips: ['192.168.1.199', '2001:db8::199'] }, '6h');
		expect(new URL(href, 'http://x').pathname).toBe('/logs');
		expect(Object.fromEntries(params(href))).toEqual({ type: 'zeek.conn', exclude_src: '192.168.1.199,2001:db8::199', ...win, range: '6h' });
		expect(params(connLogsHref({ ...win, excluded_ips: [] }, '24h')).has('exclude_src')).toBe(false);
	});

	it('joins query clauses with AND and carries the exact window', () => {
		const href = logsHrefForQuery(['event.provider:zeek', 'destination.ip:"2001:db8::1"', 'destination.port:443'], win, '30d');
		expect(new URL(href, 'http://x').pathname).toBe('/logs');
		expect(Object.fromEntries(params(href))).toEqual({
			query: 'event.provider:zeek AND destination.ip:"2001:db8::1" AND destination.port:443',
			...win,
			range: '30d',
		});
	});

	it('adds the window to an address link only when given', () => {
		expect(params(logsHrefForIp('192.0.2.1', '7d')).get('from')).toBeNull();
		const p = params(logsHrefForIp('192.0.2.1', '7d', win));
		expect([p.get('range'), p.get('from'), p.get('to')]).toEqual(['7d', win.from, win.to]);
	});

	it('reads a link window back as Custom, exactly', () => {
		expect(customRange(win.from, win.to)).toMatchObject({ value: 'custom', label: 'Custom', hours: 24, ...win });
		expect(customRange(win.to, win.from)).toBeNull();
	});
});

// NET-160 slice 2b-2: a raw Suricata category's page and the lists its figures open
describe('Suricata category links', () => {
	const win = { from: '2026-11-05T13:02:00.000Z', to: '2026-11-06T13:02:00.000Z', range: '7d' };

	it('encodes "/", "&", "%" and spaces into one path segment, with the window only when given', () => {
		expect(suricataCategoryHref('A/B & C 50%')).toBe('/alerts/suricata/A%2FB%20%26%20C%2050%25');
		const href = new URL(suricataCategoryHref('Misc activity', win), 'http://x');
		expect(decodeURIComponent(href.pathname.split('/').at(-1)!)).toBe('Misc activity');
		expect(Object.fromEntries(href.searchParams)).toEqual(win);
	});

	it("opens the Alerts list for the category, narrowed as the figure was, over the figure's window", () => {
		const href = suricataAlertsHref('A/B & C', win, { signature: 'ET SCAN x', src: '192.0.2.1', dst: '' });
		expect(new URL(href, 'http://x').pathname).toBe('/alerts');
		expect(Object.fromEntries(new URL(href, 'http://x').searchParams)).toEqual({ signature: 'ET SCAN x', src: '192.0.2.1', suricata_category: 'A/B & C', ...win });
		expect(Object.fromEntries(new URL(suricataAlertsHref('X', win), 'http://x').searchParams)).toEqual({ suricata_category: 'X', ...win });
	});
});

describe('partialListNote', () => {
	it('says the rows are the highest among those read, with how many when the reply says', () => {
		expect(partialListNote('addresses', 5000)).toBe('Highest counts among the 5,000 addresses read; the full set was too large to read');
		expect(partialListNote('rules')).toBe('Highest counts among the rules read; the full set was too large to read');
	});
});

describe('the figure clicked (section D)', () => {
	const ALERTS = { lead: 'This search now matches', one: 'alert', many: 'alerts' };

	it('withCount appends count to a link with or without a query, and only a whole number of 0 or more', () => {
		expect(withCount('/alerts?from=a&to=b', 1234)).toBe('/alerts?from=a&to=b&count=1234');
		expect(withCount('/devices', 0)).toBe('/devices?count=0');
		expect(withCount('/alerts?x=1', -1)).toBe('/alerts?x=1');
		expect(withCount('/alerts?x=1', 1.5)).toBe('/alerts?x=1');
		expect(withCount('/alerts?x=1', Number.NaN)).toBe('/alerts?x=1');
		expect(withCount('/alerts?x=1', null)).toBe('/alerts?x=1');
		expect(withCount('/alerts?x=1', undefined)).toBe('/alerts?x=1');
	});

	it('linkedCount takes up to 15 digits and nothing else', () => {
		expect(linkedCount('1204')).toBe(1204);
		expect(linkedCount('0')).toBe(0);
		expect(linkedCount('999999999999999')).toBe(999_999_999_999_999);
		for (const bad of ['', '1e3', '-1', ' 5', '5 ', '1.0', '1234567890123456', 'abc']) expect(linkedCount(bad)).toBeNull();
		expect(linkedCount(null)).toBeNull();
	});

	it('countDifference states the net difference in en-GB figures, or nothing when they agree', () => {
		expect(countDifference(1234, 1234, ALERTS)).toBeNull();
		expect(countDifference(1234, 1240, ALERTS)).toBe(
			'You clicked 1,234. This search now matches 1,240 alerts (6 more). Records can be logged after a figure is counted (a connection is logged when it ends), and old records are deleted to free disk space.'
		);
		expect(countDifference(1234, 1200, ALERTS)).toMatch(/^You clicked 1,234\. This search now matches 1,200 alerts \(34 fewer\)\. /);
		expect(countDifference(2, 1, ALERTS)).toMatch(/matches 1 alert \(1 fewer\)/);
		expect(countDifference(53, 54, { lead: 'This window now has', one: 'device', many: 'devices' })).toMatch(/^You clicked 53\. This window now has 54 devices \(1 more\)\./);
	});

	it('logsHrefForIp opens one log type when given one', () => {
		expect(logsHrefForIp('10.0.0.5', '24h', { from: 'A', to: 'B' }, 'zeek.conn')).toBe(
			`/logs?query=${encodeURIComponent('(source.ip:"10.0.0.5" OR destination.ip:"10.0.0.5")')}&range=24h&type=zeek.conn&from=A&to=B`
		);
		expect(logsHrefForIp('10.0.0.5', '24h')).not.toContain('type=');
	});
});

describe('fitCount (NET-192)', () => {
	it('keeps a count exact while it fits, and shortens it past 99,999', () => {
		expect(fitCount(0)).toBe('0');
		expect(fitCount(99_999)).toBe('99,999');
		expect(fitCount(100_000)).toBe('100K');
		expect(fitCount(214_000)).toBe('214K');
		expect(fitCount(1_250_000)).toBe('1.3M');
	});
});

describe('the saved default range (NET-195)', () => {
	const save = (value: unknown) => localStorage.setItem(DISPLAY_SETTINGS_KEY, JSON.stringify(value));
	afterEach(() => {
		localStorage.clear();
		vi.restoreAllMocks();
	});

	it('is null when nothing is saved, the JSON is bad, or storage throws', () => {
		expect(savedDefaultRange()).toBeNull();
		localStorage.setItem(DISPLAY_SETTINGS_KEY, '{not json');
		expect(savedDefaultRange()).toBeNull();
		save({ defaultRange: '7d' });
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new Error('SecurityError');
		});
		expect(savedDefaultRange()).toBeNull();
	});

	it.each([
		[{ defaultRange: '7d' }, '7d'],
		[{ defaultRange: '15m' }, null],
		// an invalid new field is present: no fallback to the legacy one
		[{ defaultRange: '15m', defaultTimeRange: '7d' }, null],
		[{ defaultTimeRange: '6h' }, '6h'],
		[{ defaultTimeRange: '24h' }, '24h'],
		[{ defaultTimeRange: '7d' }, '7d'],
		[{ defaultTimeRange: '30d' }, '30d'],
		// Settings' own fallback, written by any Display save, and the ranges no longer offered
		[{ defaultTimeRange: '1h' }, null],
		[{ defaultTimeRange: '15m' }, null],
		[{ defaultTimeRange: '4h' }, null],
		[{ defaultRange: '24h', defaultTimeRange: '7d' }, '24h'],
	])('reads %j as %s', (stored, expected) => {
		save(stored);
		expect(savedDefaultRange()).toBe(expected);
	});

	it('is null for JSON that is not an object', () => {
		for (const stored of ['7d', 7, null, ['7d']]) {
			save(stored);
			expect(savedDefaultRange()).toBeNull();
		}
	});

	it("startRange gives the saved range, else the page's own", () => {
		expect(startRange('24h')).toBe('24h');
		save({ defaultRange: '30d' });
		expect(startRange('24h')).toBe('30d');
		save({ defaultTimeRange: '1h' });
		expect(startRange('24h')).toBe('24h');
	});
});

describe('the Live map choice', () => {
	const save = (value: unknown) => localStorage.setItem(DISPLAY_SETTINGS_KEY, JSON.stringify(value));
	afterEach(() => {
		localStorage.clear();
		vi.restoreAllMocks();
	});

	it('is the globe unless this browser picked the flat map', () => {
		expect(savedLiveMap()).toBe('globe');
		save({ liveMap: 'flat' });
		expect(savedLiveMap()).toBe('flat');
		save({ liveMap: 'flat', defaultRange: '7d' });
		expect(savedLiveMap()).toBe('flat');
		expect(savedDefaultRange()).toBe('7d');
		for (const stored of [{ liveMap: 'FLAT' }, { liveMap: 1 }, { defaultRange: '7d' }, 'flat', null]) {
			save(stored);
			expect(savedLiveMap()).toBe('globe');
		}
	});

	it('is the globe when the JSON is bad or storage throws', () => {
		localStorage.setItem(DISPLAY_SETTINGS_KEY, '{not json');
		expect(savedLiveMap()).toBe('globe');
		save({ liveMap: 'flat' });
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new Error('SecurityError');
		});
		expect(savedLiveMap()).toBe('globe');
	});

	it("a saved flat map doesn't count as a default range", () => {
		save({ liveMap: 'flat' });
		expect(savedDefaultRange()).toBeNull();
	});
});

// NET-238 review: the capped-scan notices quote the daemon's cap, so a change there must reach them
describe('SCAN_CAP', () => {
	it("matches the daemon's MAX_BUCKETS", () => {
		const source = readFileSync(resolve(__dirname, '../../../../daemon/storage/all_buckets.py'), 'utf-8');
		const daemonCap = Number(source.match(/^MAX_BUCKETS = ([\d_]+)$/m)?.[1].replaceAll('_', ''));
		expect(SCAN_CAP).toBe(daemonCap);
	});
});
