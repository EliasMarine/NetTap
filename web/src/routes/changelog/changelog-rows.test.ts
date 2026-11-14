import { describe, it, expect } from 'vitest';
import type { ChangelogEvent } from '$lib/api/changelog';
import type { Device, DeviceListResponse } from '$lib/api/devices';
import {
	changelogKpis, csvCell, eventBuckets, inPick, joinChangelog, keepPick, knownFrom, MISSING_TEXT, pickRange, readPick, spanText, toCsv, toJson,
	type ChangelogRow,
} from './changelog-rows';

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const T0 = Date.parse('2026-11-10T00:00:00.000Z');
const at = (ms: number) => new Date(ms).toISOString();

const event = (over: Partial<ChangelogEvent> = {}): ChangelogEvent => ({
	_id: 'e1', '@timestamp': at(T0), event_type: 'device_joined', title: 'New device aa:bb:cc:dd:ee:01',
	description: '', metadata: { mac: 'aa:bb:cc:dd:ee:01', ip: '192.168.1.10', source: 'dhcp' }, ...over,
});
const device = (over: Partial<Device> = {}): Device => ({
	ip: '192.168.1.10', mac: 'aa:bb:cc:dd:ee:01', hostname: null, manufacturer: null, os_hint: null,
	first_seen: at(T0 + HOUR), last_seen: at(T0 + 2 * HOUR), total_bytes: 100, upload_bytes: 40, download_bytes: 60,
	connection_count: 5, protocols: [], alert_count: 1, ...over,
});
const list = (devices: Device[], total = devices.length): DeviceListResponse => ({
	from: at(T0), to: at(T0 + DAY), limit: 500, devices, total, as_of: at(T0 + DAY), online_since: at(T0 + DAY), online_total: 0,
});
const one = (e: ChangelogEvent, l: DeviceListResponse | null) => joinChangelog([e], l).rows[0];

describe('joinChangelog: matching', () => {
	it('normalises the MAC: case and dashes', () => {
		const row = one(event({ metadata: { mac: 'AA-BB-CC-DD-EE-01' } }), list([device()]));
		expect(row.mac).toBe('aa:bb:cc:dd:ee:01');
		expect(row.total).toBe(100);
	});

	it('sums every address carrying the MAC and lists them, the busiest first', () => {
		const row = one(event(), list([
			device({ ip: '192.168.1.10', total_bytes: 100, upload_bytes: 40, download_bytes: 60, connection_count: 5, alert_count: 1 }),
			device({ ip: '192.168.1.20', mac: 'AA:BB:CC:DD:EE:01', total_bytes: 900, upload_bytes: 300, download_bytes: 600, connection_count: 7, alert_count: 2, hostname: 'Kitchen iPad' }),
			device({ ip: '192.168.1.30', mac: 'aa:bb:cc:dd:ee:99', total_bytes: 5000 }),
		]));
		expect(row.trafficIps).toEqual(['192.168.1.20', '192.168.1.10']);
		expect([row.total, row.sent, row.received, row.connections, row.alerts]).toEqual([1000, 340, 660, 12, 3]);
		expect(row.name).toBe('Kitchen iPad');
		expect(row.eventIp).toBe('192.168.1.10');
		expect(row.missing).toBeNull();
	});

	it("never takes an address whose row carries another device's MAC (the list isn't truncated)", () => {
		const { rows, coverage } = joinChangelog([event()], list([device({ mac: 'aa:bb:cc:dd:ee:99', total_bytes: 9e9 })], 1));
		expect(coverage.devicesTruncated).toBe(false);
		expect(rows[0].missing).toBe('no-figures');
		expect(rows[0].total).toBeNull();
		expect(MISSING_TEXT['no-figures']).toBe('No address-level traffic figures matched this device in this range.');
	});

	it('matches by IP only when the event has no MAC', () => {
		const noMac = one(event({ metadata: { ip: '192.168.1.10' } }), list([device({ mac: 'aa:bb:cc:dd:ee:99' })]));
		expect(noMac.trafficIps).toEqual(['192.168.1.10']);
		expect(noMac.name).toBe('192.168.1.10');
		const withMac = one(event({ metadata: { mac: 'aa:bb:cc:dd:ee:01', ip: '192.168.1.10' } }), list([device({ mac: null })]));
		expect(withMac.missing).toBe('no-figures');
	});
});

describe('joinChangelog: missing figures', () => {
	it('a system event has no device and no figures', () => {
		const row = one(event({ event_type: 'storage_pruned', metadata: { freed_bytes: 5 } }), list([device()]));
		expect(row.kind).toBe('system');
		expect(row.missing).toBe('system');
	});

	it('an unmatched device is never summed as 0', () => {
		const row = one(event(), list([]));
		expect(row.kind).toBe('device');
		expect([row.sent, row.received, row.total, row.connections, row.alerts, row.lastSeen, row.spanMs]).toEqual([null, null, null, null, null, null, null]);
		expect(row.trafficIps).toEqual([]);
	});

	it('a failed list leaves the events, marked', () => {
		const { rows, coverage } = joinChangelog([event()], null);
		expect(rows[0].missing).toBe('devices-failed');
		expect(coverage.devicesFailed).toBe(true);
	});

	it("a field an older daemon doesn't send stays empty, not 0", () => {
		const row = one(event(), list([device({ upload_bytes: undefined })]));
		expect(row.sent).toBeNull();
		expect(row.total).toBe(100);
	});
});

describe('joinChangelog: times', () => {
	it("first seen is the device_joined event's own time (the device's first record)", () => {
		const row = one(event({ '@timestamp': at(T0 - DAY) }), list([device({ first_seen: at(T0 + HOUR) })]));
		expect(row.firstSeen).toBe(at(T0 - DAY));
	});

	it('another event takes the earliest matched first seen', () => {
		const row = one(event({ event_type: 'device_left' }), list([device({ first_seen: at(T0 + 3 * HOUR) }), device({ ip: '192.168.1.20', first_seen: at(T0 + HOUR) })]));
		expect(row.firstSeen).toBe(at(T0 + HOUR));
	});

	it('two records six days apart are "seen over" 6 days, gaps included', () => {
		const row = one(event(), list([device({ first_seen: at(T0), last_seen: at(T0 + 6 * DAY) })]));
		expect(row.spanMs).toBe(6 * DAY);
		expect(spanText(row.spanMs)).toBe('6d 0h');
	});

	it('a negative or missing span is no span', () => {
		expect(one(event({ '@timestamp': at(T0 + 5 * HOUR) }), list([device()])).spanMs).toBeNull();
		expect(one(event(), list([])).spanMs).toBeNull();
		expect(spanText(null)).toBe('—');
		expect(spanText(3 * HOUR + 12 * 60_000)).toBe('3h 12m');
		// review L1: records a moment apart, not "0µs"
		expect(spanText(0)).toBe('< 1s');
	});
});

describe('joinChangelog: coverage', () => {
	it('says when the daemon returned its cap of 1,000 events', () => {
		const many = (n: number) => Array.from({ length: n }, (_, i) => event({ _id: `e${i}`, metadata: {} }));
		expect(joinChangelog(many(1000), list([])).coverage.eventsTruncated).toBe(true);
		expect(joinChangelog(many(999), list([])).coverage.eventsTruncated).toBe(false);
	});

	it('says when the device list was cut (total above its rows)', () => {
		expect(joinChangelog([event()], list([device()], 600)).coverage.devicesTruncated).toBe(true);
	});

	it('keeps an IPv6 note per matched address, for both reasons', () => {
		const { rows, coverage } = joinChangelog(
			[event(), event({ _id: 'e2', metadata: { mac: 'aa:bb:cc:dd:ee:02' } })],
			list([
				device({ ipv6_left_out: 3, ipv6_left_out_reason: 'router' }),
				device({ ip: '192.168.1.20', ipv6_left_out: 1, ipv6_left_out_reason: 'router' }),
				device({ ip: '192.168.1.40', mac: 'aa:bb:cc:dd:ee:02', ipv6_left_out: 2, ipv6_left_out_reason: 'no_gateway' }),
			]),
		);
		expect(rows[0].ipv6Notes).toEqual([
			"The device at 192.168.1.10 forwards other devices' traffic (it's the router), so only its link-local IPv6 is counted.",
			"The device at 192.168.1.20 forwards other devices' traffic (it's the router), so only its link-local IPv6 is counted.",
		]);
		expect(rows[1].ipv6Notes).toEqual(["IPv6 traffic other than link-local isn't counted for this period: no internet traffic showed which device is the router."]);
		expect(coverage.ipv6Notes).toHaveLength(3);
	});
});

describe('changelogKpis', () => {
	it('covers matched new devices only', () => {
		const { rows } = joinChangelog(
			[event({ _id: 'a' }), event({ _id: 'b', metadata: { mac: 'aa:bb:cc:dd:ee:02' } }), event({ _id: 'c', event_type: 'storage_pruned', metadata: {} })],
			list([device({ total_bytes: 700 })]),
		);
		const k = changelogKpis(rows);
		expect(k).toMatchObject({ events: 3, newDevices: 2, matched: 1, moved: 700 });
		expect(k.busiest?.id).toBe('a');
	});

	it('shows no traffic figure when none matched, and counts a device recorded twice once', () => {
		const k = changelogKpis(joinChangelog([event({ _id: 'a' }), event({ _id: 'b' })], list([])).rows);
		expect(k).toMatchObject({ newDevices: 1, matched: 0, moved: null, busiest: null });
	});
});

describe('buckets and the pick', () => {
	const WIN = { from: at(T0 + 30 * 60_000), to: at(T0 + 3 * HOUR + 30 * 60_000) };
	const rowAt = (ms: number, id = String(ms)) => ({ ...one(event({ _id: id, metadata: {} }), null), t: ms }) as ChangelogRow;

	it('counts events per bucket, buckets on the hour', () => {
		const rows = [rowAt(T0 + 40 * 60_000), rowAt(T0 + HOUR + 1), rowAt(T0 + HOUR + 2)];
		const b = eventBuckets(rows, WIN, HOUR, knownFrom(rows, WIN, HOUR, false));
		expect(b.map((x) => x.timestamp)).toEqual([at(T0), at(T0 + HOUR), at(T0 + 2 * HOUR), at(T0 + 3 * HOUR)]);
		expect(b.map((x) => x.count)).toEqual([1, 2, 0, 0]);
	});

	it('when cut at 1,000: the bucket holding the oldest event and every earlier one are unknown, a tie included', () => {
		// the oldest returned event sits exactly on 02:00, so others at 02:00 may be missing
		const rows = [rowAt(T0 + 2 * HOUR, 'a'), rowAt(T0 + 3 * HOUR, 'b')];
		const known = knownFrom(rows, WIN, HOUR, true);
		expect(known).toBe(T0 + 3 * HOUR);
		const b = eventBuckets(rows, WIN, HOUR, known);
		expect(b.map((x) => Number.isFinite(x.count))).toEqual([false, false, false, true]);
		expect(pickRange(b, 3, 3, HOUR, WIN)).toEqual({ from: at(T0 + 3 * HOUR), to: WIN.to });
		expect(pickRange(b, 2, 2, HOUR, WIN)).toBeNull();
		expect(pickRange(b, 3, 1, HOUR, WIN)).toBeNull();
	});

	it('a pick is clipped to the loaded window at both edges, with an inclusive end', () => {
		const b = eventBuckets([], WIN, HOUR, Date.parse(WIN.from));
		expect(pickRange(b, 0, 0, HOUR, WIN)).toEqual({ from: WIN.from, to: at(T0 + HOUR - 1) });
		expect(pickRange(b, 3, 3, HOUR, WIN)).toEqual({ from: at(T0 + 3 * HOUR), to: WIN.to });
		expect(pickRange(b, 2, 1, HOUR, WIN)).toEqual({ from: at(T0 + HOUR), to: at(T0 + 3 * HOUR - 1) });
	});

	it("filters with inclusive bounds: an event on the next bucket's start is out", () => {
		const rows = [rowAt(T0 + HOUR, 'start'), rowAt(T0 + 2 * HOUR - 1, 'end'), rowAt(T0 + 2 * HOUR, 'next')];
		const picked = inPick(rows, pickRange(eventBuckets(rows, WIN, HOUR, Date.parse(WIN.from)), 1, 1, HOUR, WIN));
		expect(picked.map((r) => r.id)).toEqual(['start', 'end']);
		expect(inPick(rows, null)).toHaveLength(3);
	});

	it('a final-bucket pick survives an immediate reload; one outside the new window is dropped', () => {
		const b = eventBuckets([], WIN, HOUR, Date.parse(WIN.from));
		const last = pickRange(b, 3, 3, HOUR, WIN)!;
		const later = { from: at(Date.parse(WIN.from) + 1000), to: at(Date.parse(WIN.to) + 1000) };
		expect(keepPick(last, later, Date.parse(later.from))).toEqual(last);
		const first = pickRange(b, 0, 0, HOUR, WIN)!;
		expect(keepPick(first, later, Date.parse(later.from))).toBeNull();
		expect(keepPick(last, later, Date.parse(WIN.to) + 1)).toBeNull();
	});

	it('reads a pick from the URL only when both ends are dates in order', () => {
		expect(readPick(WIN.from, WIN.to)).toEqual(WIN);
		expect(readPick(WIN.to, WIN.from)).toBeNull();
		expect(readPick('soon', WIN.to)).toBeNull();
		expect(readPick(null, null)).toBeNull();
	});
});

describe('export', () => {
	it.each(['=SUM(A1)', '+1', '-1', '@cmd', '\tx', '\rx'])('csvCell makes %j literal', (v) => {
		expect(csvCell(v)).toBe(`"'${v}"`);
	});

	it('csvCell doubles quotes, keeps numbers numeric and leaves nothing empty', () => {
		expect(csvCell('Kitchen "big" iPad')).toBe('"Kitchen ""big"" iPad"');
		expect(csvCell(-5)).toBe('-5');
		expect(csvCell(null)).toBe('');
	});

	it('the CSV carries the joined columns; the JSON keeps the original event', () => {
		const rows = joinChangelog([event()], list([device({ hostname: '=evil' })])).rows;
		const [head, line] = toCsv(rows).split('\n');
		expect(head).toContain('"Device name","MAC","Vendor","Joined at","Counted from","First seen","Last seen in range","Seen over (s)","Sent (bytes)","Received (bytes)"');
		expect(line).toContain(`"'=evil","aa:bb:cc:dd:ee:01"`);
		expect(line).toContain(',40,60,100,5,1,');
		const json = JSON.parse(toJson(rows));
		expect(json[0]).toMatchObject({ _id: 'e1', title: 'New device aa:bb:cc:dd:ee:01', joined: { name: '=evil', sent: 40, trafficIps: ['192.168.1.10'] } });
	});
});
