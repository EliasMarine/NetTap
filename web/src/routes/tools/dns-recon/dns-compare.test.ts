import { describe, it, expect, vi, afterEach } from 'vitest';
import type { DnsCompareAnswer, DnsCompareReply, DnsScope } from '$api/tools';
import { compareVerdict, labeller, saveResolvers, savedResolvers, MAX_RESOLVERS } from './dns-compare';

// Shaped like the daemon's replies to the real dig output in daemon/tests/dig_compare_fixtures.py
const a = (value: string, ttl: number, scope: DnsScope, name = 'setup.ui.com.'): DnsCompareAnswer => ({
	name,
	ttl,
	class: 'IN',
	type: 'A',
	value,
	key: `${name.replace(/\.$/, '')} IN A ${value}`,
	scope,
});
const reply = (resolver: string, status: string | null, answers: DnsCompareAnswer[] = []): DnsCompareReply => ({
	resolver,
	status,
	answers,
	ttl: answers.length ? Math.min(...answers.map((x) => x.ttl)) : null,
	latency_ms: status ? 8 : null,
	error: status ? null : 'No reply from NetTap',
	truncated: false,
});

const ROUTER = reply('192.168.1.1', 'NOERROR', [a('192.168.1.1', 0, 'private')]);
const CLOUDFLARE = reply('1.1.1.1', 'NOERROR', [a('3.169.231.76', 32, 'public'), a('3.169.231.111', 32, 'public')]);
const QUAD9_NX = reply('9.9.9.9', 'NXDOMAIN');
const SILENT = reply('192.0.2.53', null);
const VPN_NOTE = 'NetTap asks from its own network interface, so a resolver that only answers inside a VPN tunnel cannot be reached.';

const names = labeller([
	{ ip: '192.168.1.1', label: 'Router' },
	{ ip: '1.1.1.1', label: '' },
	{ ip: ' 192.0.2.53 ', label: 'VPN' },
]);

describe('compareVerdict', () => {
	it('says nothing can be compared when every resolver timed out', () => {
		const v = compareVerdict([SILENT, reply('192.0.2.54', null)], names);
		expect(v.tone).toBe('warn');
		expect(v.lines).toEqual([
			'No resolver replied, so nothing can be compared.',
			`VPN did not reply. ${VPN_NOTE}`,
			`192.0.2.54 did not reply. ${VPN_NOTE}`,
		]);
	});

	it('names the one resolver that replied when the others timed out', () => {
		const v = compareVerdict([ROUTER, SILENT], names);
		expect(v.tone).toBe('warn');
		expect(v.lines).toEqual(['Only Router replied.', `VPN did not reply. ${VPN_NOTE}`]);
	});

	it('just says it replied when only one resolver was asked', () => {
		expect(compareVerdict([ROUTER], names)).toEqual({ tone: 'ok', lines: ['Router replied.'] });
	});

	it('agrees over usable replies only, ignoring TTL and order', () => {
		const later = reply('9.9.9.9', 'NOERROR', [a('3.169.231.111', 3, 'public'), a('3.169.231.76', 300, 'public')]);
		const dup = reply('8.8.8.8', 'NOERROR', [...CLOUDFLARE.answers, CLOUDFLARE.answers[0]]);
		expect(compareVerdict([CLOUDFLARE, later], names)).toEqual({ tone: 'ok', lines: ['Both resolvers that replied agree.'] });
		const v = compareVerdict([CLOUDFLARE, later, dup, SILENT], names);
		expect(v.tone).toBe('ok');
		expect(v.lines).toEqual(['All 3 resolvers that replied agree.', `VPN did not reply. ${VPN_NOTE}`]);
	});

	it('tells NOERROR with no records apart from NXDOMAIN', () => {
		const v = compareVerdict([reply('1.1.1.1', 'NOERROR'), QUAD9_NX], names);
		expect(v).toEqual({ tone: 'warn', lines: ['Resolvers disagree: 1.1.1.1 returns no records; 9.9.9.9 returns NXDOMAIN.'] });
	});

	it('spots split DNS: a private answer beside a public one or NXDOMAIN', () => {
		expect(compareVerdict([ROUTER, CLOUDFLARE], names).lines).toEqual([
			'Resolvers disagree: Router returns 192.168.1.1 (private); 1.1.1.1 returns 3.169.231.76 (public), 3.169.231.111 (public).',
			'This looks like split DNS.',
		]);
		expect(compareVerdict([ROUTER, QUAD9_NX], names).lines).toEqual([
			'Resolvers disagree: Router returns 192.168.1.1 (private); 9.9.9.9 returns NXDOMAIN.',
			'This looks like split DNS.',
		]);
	});

	it('does not call two different public answers split DNS', () => {
		const other = reply('9.9.9.9', 'NOERROR', [a('104.20.23.154', 3, 'public')]);
		expect(compareVerdict([CLOUDFLARE, other], names).lines).toEqual([
			'Resolvers disagree: 1.1.1.1 returns 3.169.231.76 (public), 3.169.231.111 (public); 9.9.9.9 returns 104.20.23.154 (public).',
		]);
	});

	it('compares the same data under different owners as different', () => {
		const other = reply('9.9.9.9', 'NOERROR', [a('192.168.1.1', 0, 'private', 'other.ui.com.')]);
		expect(compareVerdict([ROUTER, other], names).tone).toBe('warn');
	});
});

describe('compareVerdict: blocked names, failures and long answers', () => {
	const PIHOLE = reply('192.168.1.2', 'NOERROR', [a('0.0.0.0', 2, 'unspecified')]);
	const piNames = labeller([{ ip: '192.168.1.2', label: 'Pi-hole' }]);

	it('reads 0.0.0.0 beside a public answer as a block, not split DNS', () => {
		const v = compareVerdict([PIHOLE, CLOUDFLARE], piNames);
		expect(v.tone).toBe('warn');
		expect(v.lines).toEqual([
			'Resolvers disagree: Pi-hole returns 0.0.0.0; 1.1.1.1 returns 3.169.231.76 (public), 3.169.231.111 (public).',
			'Pi-hole returns 0.0.0.0, which usually means it blocks this name.',
		]);
	});

	it('does not count loopback as private either', () => {
		const local = reply('127.0.0.53', 'NOERROR', [a('127.0.0.1', 0, 'loopback')]);
		const v = compareVerdict([local, CLOUDFLARE], names);
		expect(v.lines[0]).toBe('Resolvers disagree: 127.0.0.53 returns 127.0.0.1 (loopback); 1.1.1.1 returns 3.169.231.76 (public), 3.169.231.111 (public).');
		expect(v.lines).not.toContain('This looks like split DNS.');
	});

	it('uses a neutral tone when the replies agree on a failure, or the one reply is one', () => {
		const servfail = (ip: string) => reply(ip, 'SERVFAIL');
		expect(compareVerdict([servfail('9.9.9.9'), servfail('1.1.1.1')], names)).toEqual({ tone: 'neutral', lines: ['Both resolvers that replied agree.'] });
		expect(compareVerdict([reply('9.9.9.9', 'REFUSED')], names)).toEqual({ tone: 'neutral', lines: ['9.9.9.9 replied.'] });
		expect(compareVerdict([QUAD9_NX, reply('1.1.1.1', 'NXDOMAIN')], names).tone).toBe('ok');
	});

	it('lists at most three values per resolver, and says when a reply was cut', () => {
		const many = { ...reply('1.1.1.1', 'NOERROR', ['10.0.0.1', '10.0.0.2', '10.0.0.3', '10.0.0.4', '10.0.0.5'].map((ip) => a(ip, 60, 'private'))), truncated: true };
		const v = compareVerdict([many, QUAD9_NX], names);
		expect(v.lines).toEqual([
			'Resolvers disagree: 1.1.1.1 returns 10.0.0.1 (private), 10.0.0.2 (private), 10.0.0.3 (private) and 2 more; 9.9.9.9 returns NXDOMAIN.',
			'This looks like split DNS.',
			'1.1.1.1 returned more than 100 records, so only 100 of them were compared.',
		]);
	});
});

describe('labeller', () => {
	it('names a reply by its label, else its address, matching the address as typed', () => {
		const nameOf = labeller([{ ip: ' 2606:4700:4700::1111 ', label: ' Cloudflare ' }, { ip: '9.9.9.9', label: '' }]);
		expect(nameOf('2606:4700:4700::1111')).toBe('Cloudflare');
		expect(nameOf('9.9.9.9')).toBe('9.9.9.9');
		expect(labeller([{ ip: '2606:4700:4700::ABCD', label: 'Upper' }])('2606:4700:4700::abcd')).toBe('Upper');
	});
});

describe('saved resolvers', () => {
	afterEach(() => {
		localStorage.clear();
		vi.restoreAllMocks();
	});

	it('starts with two empty rows, then keeps what was saved', () => {
		expect(savedResolvers()).toEqual([
			{ ip: '', label: '' },
			{ ip: '', label: '' },
		]);
		saveResolvers([{ ip: ' 9.9.9.9 ', label: 'Quad9' }]);
		expect(savedResolvers()).toEqual([{ ip: '9.9.9.9', label: 'Quad9' }]);
	});

	it('drops malformed rows and anything past the sixth', () => {
		const rows = Array.from({ length: 8 }, (_, i) => ({ ip: `10.0.0.${i}`, label: '', extra: true }));
		localStorage.setItem('nettap-dns-compare-resolvers', JSON.stringify([{ ip: 1 }, null, ...rows]));
		expect(savedResolvers()).toHaveLength(MAX_RESOLVERS);
		expect(savedResolvers()[0]).toEqual({ ip: '10.0.0.0', label: '' });
	});

	it('survives storage that is unreadable or blocked', () => {
		localStorage.setItem('nettap-dns-compare-resolvers', '{not json');
		expect(savedResolvers()).toHaveLength(2);
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		expect(savedResolvers()).toHaveLength(2);
		expect(() => saveResolvers([{ ip: '9.9.9.9', label: '' }])).not.toThrow();
	});
});
