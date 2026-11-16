import { describe, expect, it } from 'vitest';
import type { DomainFinding, DomainSummary } from '$lib/api/drilldown';
import type { FailedLookups } from '$lib/api/threats';
import { dgaWhy, failedLookupsHref, failedTodo, failedWhy, findingHref, findingTodo, KIND_WORDS, tunnelWhy } from './dns-anomaly';

const TUNNEL_NAME = 'idt-3tol7k-mwin8fiv.loc-en-us.chk-webapp.res-ok.dur-0.v1.dc-telemetry.net';
const TUNNEL_SUB = 'idt-3tol7k-mwin8fiv.loc-en-us.chk-webapp.res-ok.dur-0.v1';

function dns(over: Partial<DomainSummary['dns']> = {}): DomainSummary['dns'] {
	return {
		lookups: 24,
		askers: [{ ip: '192.168.1.20', lan: true, lookups: 24, last_seen: '2026-11-15T10:00:00Z' }],
		askers_complete: true,
		answers: [],
		answers_complete: true,
		addresses: 2,
		rcodes: [{ rcode: 'NOERROR', lookups: 24 }],
		timeline: [],
		...over,
	};
}

const DGA: NonNullable<DomainFinding['dga']> = { label: 'cloudflareinsights', length: 18, entropy: 3.837, threshold: 3.8, min_length: 9 };
const TUNNEL: NonNullable<DomainFinding['tunnel']> = {
	subdomain: TUNNEL_SUB,
	length: 56,
	labels: TUNNEL_SUB.split('.'),
	threshold: 50,
};

function failures(over: Partial<FailedLookups> = {}): FailedLookups {
	return {
		ip: '192.168.1.116',
		excluded: false,
		from: '2026-11-15T00:00:00Z',
		to: '2026-11-16T00:00:00Z',
		lookups: 827,
		failed: 364,
		timeline: [],
		rcodes: [],
		failed_names: [{ name: 'lb._dns-sd._udp.0.1.168.192.in-addr.arpa', lookups: 364, last_seen: null, kind: 'service_discovery' }],
		failed_names_read: 1,
		failed_names_complete: true,
		kinds: [{ kind: 'service_discovery', names: 1, lookups: 364 }],
		generated_names: 0,
		meets_rule: true,
		rule: { min_lookups: 50, min_share: 0.4 },
		...over,
	};
}

describe('links', () => {
	it('opens the failed lookups page on the range', () => {
		expect(failedLookupsHref('fe80::1', '7d')).toBe('/threats/failed-lookups/fe80%3A%3A1?range=7d');
	});

	it('opens the canonical domain page with the raw name the check read', () => {
		expect(findingHref('Static.Example.COM.', { range: '24h' })).toBe('/domain/static.example.com?range=24h&finding=Static.Example.COM.');
	});
});

describe('dgaWhy', () => {
	it('says how close to the line a score is, and that the name resolved', () => {
		const why = dgaWhy(DGA, dns());
		expect(why[0]).toMatch(/“cloudflareinsights” \(18 characters\).*It scored 3\.837.*over 3\.8.*at least 9 characters long\. That is only just over the line\./);
		expect(why[1]).toBe('It is letters only.');
		expect(why[2]).toBe('It resolves: 24 lookups from 1 device in this window, answered with 2 addresses.');
		expect(why.join(' ')).toMatch(/real words can score this high/);
	});

	it('says when a score is far over, the name has digits and every lookup failed', () => {
		const why = dgaWhy({ ...DGA, label: 'kq3z8wxv1m7tbn5r6yhp', length: 20, entropy: 4.322 }, dns({ lookups: 3, rcodes: [{ rcode: 'NXDOMAIN', lookups: 3 }], askers_complete: false }));
		expect(why[0]).not.toMatch(/just over/);
		expect(why[1]).toMatch(/letters and digits/);
		expect(why[2]).toMatch(/Every one of its 3 lookups from at least 1 device .*\(NXDOMAIN\)/);
	});

	it('says no lookup returned an address when some failed another way (SERVFAIL, a filter\'s REFUSED)', () => {
		const dnsReply = dns({ lookups: 5, addresses: 0, rcodes: [{ rcode: 'NXDOMAIN', lookups: 3 }, { rcode: 'SERVFAIL', lookups: 2 }] });
		expect(dgaWhy(DGA, dnsReply)[2]).toBe('None of its 5 lookups from 1 device in this window returned an address.');
	});

	it('says when nothing looked it up and when answers are too many to count', () => {
		expect(dgaWhy(DGA, dns({ lookups: 0 }))[2]).toBe('No device looked it up in this window.');
		expect(dgaWhy(DGA, dns({ addresses: null }))[2]).toMatch(/too many addresses to count/);
	});
});

describe('tunnelWhy', () => {
	it('measures the long part, its labels and the longest one', () => {
		const why = tunnelWhy(TUNNEL, TUNNEL_NAME, dns());
		expect(why[0]).toBe(`The part before dc-telemetry.net, “${TUNNEL_SUB}”, is 56 characters long; the check lists a name when that part is over 50. It has 6 labels, the longest “idt-3tol7k-mwin8fiv” (19 characters).`);
	});

	it('stays inconclusive about a repeated name', () => {
		const why = tunnelWhy(TUNNEL, TUNNEL_NAME, dns()).join(' ');
		expect(why).toMatch(/looked up 24 times.*can't show whether.*under dc-telemetry\.net.*counts only this name/);
		expect(why).not.toMatch(/not a tunnel|is tunnelling|safe/i);
		expect(why).not.toMatch(/looks like an ID/);
	});

	it('points out an ID by its text pattern', () => {
		const uuid = '0b5c4f9e-3d2a-4f6b-9c1e-7a8b9c0d1e2f.netseer';
		const why = tunnelWhy({ ...TUNNEL, subdomain: uuid, labels: uuid.split('.'), length: uuid.length }, `${uuid}.fbcdn.net.`, dns({ lookups: 1 }));
		expect(why[1]).toMatch(/looks like an ID/);
		expect(why[0]).toMatch(/^The part before fbcdn\.net,/);
		expect(why[2]).toMatch(/looked up 1 time in/);
	});
});

describe('findingTodo', () => {
	it('adds the tunnelling check for a tunnel finding and the malware check for a DGA one', () => {
		const tunnel = findingTodo({ name: TUNNEL_NAME, dga: null, tunnel: TUNNEL }, TUNNEL_NAME);
		expect(tunnel[0]).toMatch(/Check the devices listed below/);
		expect(tunnel.join(' ')).toMatch(/other lookups under dc-telemetry\.net/);
		expect(tunnel.join(' ')).not.toMatch(/malware/);
		const dga = findingTodo({ name: 'x', dga: DGA, tunnel: null }, 'x');
		expect(dga.join(' ')).toMatch(/check that device for malware/);
	});
});

describe('failedWhy', () => {
	it("tells the G11's service discovery case from what was read", () => {
		const why = failedWhy(failures(), '192.168.1.116', 'last 24 hours');
		expect(why[0]).toBe('192.168.1.116 made 827 lookups in the last 24 hours; 364 of them (44%) came back as “no such name” (NXDOMAIN). NetTap lists a device when more than 40% of more than 50 lookups fail.');
		expect(why[1]).toBe('All 364 failures were for one name, lb._dns-sd._udp.0.1.168.192.in-addr.arpa.');
		expect(why[2]).toBe(KIND_WORDS.service_discovery.meaning);
		expect(why).toHaveLength(3);
	});

	it("says when this window doesn't meet the rule the Threats scan listed it by", () => {
		const NOT_MET = "In this window that isn't met, so the check wouldn't list this device for it.";
		expect(failedWhy(failures(), 'x', 'w')).not.toContain(NOT_MET);
		// OLD CODE START — the page computed the rule; it reads the daemon's meets_rule now
		// expect(failedWhy(failures({ lookups: 50, failed: 40 }), 'x', 'w')[1]).toBe(NOT_MET);
		// expect(failedWhy(failures({ lookups: 827, failed: 300 }), 'x', 'w')[1]).toBe(NOT_MET);
		// expect(failedWhy(failures({ lookups: 0, failed: 0 }), 'x', 'w')[1]).toBe(NOT_MET);
		// OLD CODE END
		expect(failedWhy(failures({ lookups: 50, failed: 40, meets_rule: false }), 'x', 'w')[1]).toBe(NOT_MET);
		// the rule's numbers are the daemon's
		expect(failedWhy(failures({ rule: { min_lookups: 100, min_share: 0.5 } }), 'x', 'w')[0]).toMatch(/more than 50% of more than 100 lookups fail\.$/);
	});

	it('makes no claim about every name when the read was capped', () => {
		const why = failedWhy(failures({ failed_names_complete: false, failed_names_read: 5000, generated_names: 40 }), 'x', 'last 7 days');
		expect(why[1]).toMatch(/read the first 5,000 in name order.*a busier name may be missing/);
		expect(why).toHaveLength(2);
		expect(why.join(' ')).not.toMatch(/generated|Service discovery/);
	});

	it('names many generated names as the malware pattern, and a few as a count', () => {
		const many = failures({ failed_names_read: 30, failed: 300, generated_names: 12, kinds: [{ kind: 'generated', names: 12, lookups: 100 }, { kind: 'other', names: 18, lookups: 200 }], failed_names: [{ name: 'a.test', lookups: 20, last_seen: null, kind: 'other' }] });
		const text = failedWhy(many, 'x', 'w').join(' ');
		expect(text).toMatch(/All 30 names that failed were read\./);
		expect(text).toMatch(/12 of the names that failed look generated\. That is the pattern of malware/);
		expect(text).toMatch(/Ordinary names that don't exist/);
		expect(failedWhy(failures({ generated_names: 1 }), 'x', 'w').join(' ')).toMatch(/1 of the names that failed looks generated\./);
	});

	it('suggests a DNS filter when many ordinary names failed', () => {
		const text = failedWhy(failures({ failed_names_read: 25, kinds: [{ kind: 'other', names: 25, lookups: 364 }] }), 'x', 'w').join(' ');
		expect(text).toMatch(/A DNS filter \(Pi-hole, NextDNS or a router blocklist\)/);
	});
});

describe('failedTodo', () => {
	it('always says to find the app, and adds a malware check for generated names', () => {
		expect(failedTodo(failures(), 'Laptop')).toEqual(['Find the app or setting on Laptop that asks for the busiest names below.']);
		expect(failedTodo(failures({ generated_names: 2 }), 'Laptop')[1]).toMatch(/malware/);
	});
});
