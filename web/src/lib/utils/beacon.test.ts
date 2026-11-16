import { describe, expect, it } from 'vitest';
import type { BeaconPair, BeaconTiming } from '$lib/api/threats';
import { beaconHref, beaconStory, beaconTodo, blocklistWords, CONFIDENCE_HOW, hostPort, intervalWords, serviceWords, type BeaconContext } from './beacon';

const UNLISTED = { matched: false, feeds: [], indicators: 0, in_window: false };
const LISTED = { matched: true, feeds: [{ feed: 'et_compromised', label: 'Suricata blocklist rules', indicator: '203.0.113.9', type: 'ip' }], indicators: 3, in_window: true };

function pair(timing: Partial<BeaconTiming>, over: Partial<BeaconPair> = {}): BeaconPair {
	return {
		device: '10.10.0.164',
		server: '142.251.150.120',
		port: 443,
		device_excluded: false,
		from: '2026-11-15T00:00:00Z',
		to: '2026-11-16T00:00:00Z',
		interval: '5m',
		connections: 1453,
		first_seen: null,
		last_seen: null,
		timeline: [],
		transports: [{ name: 'tcp', connections: 1453 }],
		services: [{ name: 'ssl', connections: 1453 }],
		timing: { status: 'periodic', slots: 1453, mean_gap_seconds: 60, jitter: 0.026, beacon: { interval_seconds: 60, jitter_coefficient: 0.026, confidence: 100 }, gaps: [], ...timing },
		tls_names: [{ name: 'www.google.com', sessions: 4 }],
		tls_complete: true,
		dns_names: [{ name: 'www.google.com', lookups: 2 }],
		dns_complete: true,
		threat_intel: UNLISTED,
		...over,
	};
}

const CTX: BeaconContext = { words: 'last 24 hours', deviceName: null, owner: 'Google LLC (AS15169)', anycast: false };

describe('beaconHref', () => {
	it('encodes both addresses and keeps the range', () => {
		expect(beaconHref('fe80::1', '2001:db8::9', 0, '7d')).toBe('/threats/beaconing/fe80%3A%3A1/2001%3Adb8%3A%3A9/0?range=7d');
	});
});

describe('hostPort', () => {
	it('brackets an IPv6 address', () => {
		expect(hostPort('203.0.113.9', 443)).toBe('203.0.113.9:443');
		expect(hostPort('2001:db8::1', 443)).toBe('[2001:db8::1]:443');
	});
});

describe('intervalWords', () => {
	it('picks the unit a person would', () => {
		expect(intervalWords(60)).toBe('60 seconds');
		expect(intervalWords(3602.6)).toBe('60 minutes');
		expect(intervalWords(9000)).toBe('2.5 hours');
	});
});

describe('serviceWords', () => {
	it('names pings, HTTPS and SSH from the reply', () => {
		expect(serviceWords({ port: 0, transports: [{ name: 'icmp', connections: 3 }], services: [] })).toMatch(/^pings/);
		expect(serviceWords({ port: 443, transports: [], services: [] })).toMatch(/TLS/);
		expect(serviceWords({ port: 2222, transports: [], services: [{ name: 'ssh', connections: 1 }] })).toMatch(/^SSH/);
		expect(serviceWords({ port: 9999, transports: [], services: [] })).toBe('connections to port 9999');
	});
});

describe('blocklistWords', () => {
	it("mirrors the address page's four states", () => {
		expect(blocklistWords(null)).toEqual({ tone: 'unknown', chip: 'Not checked', note: "This window's alerts couldn't all be checked" });
		expect(blocklistWords(LISTED).note).toBe('A Suricata blocklist rule named it in this window');
		expect(blocklistWords({ ...LISTED, in_window: false }).note).toMatch(/doesn't keep the date/);
		expect(blocklistWords({ ...LISTED, in_window: null }).note).toMatch(/couldn't all be checked/);
		expect(blocklistWords(LISTED).chip).toBe('On a threat list: Suricata blocklist rules');
		expect(blocklistWords(UNLISTED).note).toBe("Checked this window's alerts");
		expect(blocklistWords({ ...UNLISTED, indicators: 1 }).note).toBe("Checked this window's alerts and 1 cached indicator");
	});
});

describe('beaconStory', () => {
	it('tells a periodic pair with its own figures, and the owner only as context', () => {
		const story = beaconStory(pair({}), { ...CTX, deviceName: 'Kitchen speaker' });
		expect(story[0]).toBe('Kitchen speaker (10.10.0.164) contacted 142.251.150.120:443 about every 60 seconds, 1,453 times in the last 24 hours; the gaps between calls typically varied by only 2.6%.');
		expect(story.join(' ')).toMatch(/whose network it is, not which app or customer/);
		expect(story.join(' ')).toMatch(/www\.google\.com/);
		expect(story.join(' ')).not.toMatch(/nothing to worry|safe|harmless/i);
	});

	it('names the calls that fell short when there are too few', () => {
		const few = beaconStory(pair({ status: 'too_few', slots: 9, beacon: null }, { connections: 9 }), CTX)[0];
		expect(few).toMatch(/9 times in the last 24 hours; NetTap needs at least 10 calls/);
	});

	it('names the occupied intervals that fell short when the calls bunch up', () => {
		const bunched = beaconStory(pair({ status: 'too_few', slots: 9, beacon: null }, { connections: 100 }), CTX)[0];
		expect(bunched).toMatch(/100 times .* only 9 distinct 10-second intervals; NetTap needs 10 occupied intervals/);
	});

	it('says an irregular pair would not be listed, with its jitter', () => {
		const line = beaconStory(pair({ status: 'irregular', mean_gap_seconds: 169.1, jitter: 0.8, beacon: null }, { connections: 12 }), CTX)[0];
		expect(line).toMatch(/on average every 3 minutes/);
		expect(line).toMatch(/varied by 80\.0%.*wouldn't list this pair/);
	});

	it('claims no schedule when capped', () => {
		const line = beaconStory(pair({ status: 'capped', beacon: null, mean_gap_seconds: null, jitter: null }), CTX)[0];
		expect(line).toMatch(/can't say whether they keep a schedule/);
	});

	it('says when there is no name, no owner or an anycast address', () => {
		const bare = beaconStory(pair({}, { tls_names: [], dns_names: [] }), { ...CTX, owner: null }).join(' ');
		expect(bare).toMatch(/no name to go on/);
		expect(bare).toMatch(/doesn't know whose network/);
		expect(beaconStory(pair({}), { ...CTX, anycast: true }).join(' ')).toMatch(/anycast/);
	});

	it('words the three blocklist outcomes', () => {
		expect(beaconStory(pair({}, { threat_intel: LISTED }), CTX).at(-1)).toMatch(/A blocklist names this address: Suricata blocklist rules/);
		expect(beaconStory(pair({}, { threat_intel: null }), CTX).at(-1)).toMatch(/couldn't check every blocklist alert/);
		expect(beaconStory(pair({}), CTX).at(-1)).toMatch(/isn't a clean bill of health/);
	});
});

describe('beaconTodo', () => {
	it('always starts by finding the app, and never says nothing needs doing', () => {
		const todo = beaconTodo(pair({}), CTX);
		expect(todo).toEqual(['Find the app on 10.10.0.164 that makes these calls, and confirm this destination is expected for it.']);
	});

	it('adds disconnect-and-check for a listed address', () => {
		expect(beaconTodo(pair({}, { threat_intel: LISTED }), CTX)[1]).toMatch(/disconnect the device/);
	});

	it('adds the next step for an unchecked list, a capped read and a nameless pair', () => {
		const todo = beaconTodo(pair({ status: 'capped', beacon: null }, { threat_intel: null, tls_names: [], dns_names: [] }), CTX).join(' ');
		expect(todo).toMatch(/blocklist alerts can all be read/);
		expect(todo).toMatch(/calls can be timed/);
		expect(todo).toMatch(/other connections/);
	});
});

it('describes the confidence the scan computes', () => {
	expect(CONFIDENCE_HOW).toMatch(/up to 50 for steady timing/);
	expect(CONFIDENCE_HOW).toMatch(/20 when the interval is within 10% of a common timer/);
});
