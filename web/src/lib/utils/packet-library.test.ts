import { describe, it, expect } from 'vitest';
import data from './packet-library.json';
import { LIBRARY, KINDS, COMMON_QUESTIONS } from './packet-library';
import { filterFor } from './packet-query';

const filters = LIBRARY.flatMap((g) => g.filters);

describe('packet library (NET-188)', () => {
	it("holds the mockup's 37 filters in its six groups, in the mockup's order", () => {
		expect(filters).toHaveLength(37);
		expect(LIBRARY.map((g) => [g.label, g.filters.length])).toEqual([
			['Name lookups', 6],
			['Web and secure sites', 7],
			['Connection problems', 8],
			['Local network', 8],
			['Logins and remote access', 5],
			['Narrow it down', 3],
		]);
	});

	it('gives every group, kind and filter an id, and no id twice', () => {
		const ids = [...KINDS, ...filters].map((f) => f.id);
		expect(new Set(ids).size).toBe(ids.length);
		expect(new Set(LIBRARY.map((g) => g.id)).size).toBe(6);
		expect([...ids, ...LIBRARY.map((g) => g.id)].every((id) => /^[a-z0-9-]+$/.test(id))).toBe(true);
	});

	// The device check passes each filter to TShark; none may carry shell or quoting characters
	it.each(['\'', ';', '`', '$'])('has no filter containing %s', (ch) => {
		expect([...filters, ...KINDS].filter((f) => f.filter.includes(ch))).toEqual([]);
	});

	it('gives every library filter a label, a filter and an explanation', () => {
		expect(filters.every((f) => f.label && f.filter && f.explain)).toBe(true);
	});

	it('keeps the mockup text word for word (spot checks)', () => {
		const byId = Object.fromEntries(filters.map((f) => [f.id, f]));
		expect(byId['tcp-problems']).toEqual({
			id: 'tcp-problems',
			label: 'Every problem TShark noticed',
			filter: 'tcp.analysis.flags && !tcp.analysis.window_update && !tcp.analysis.keep_alive && !tcp.analysis.keep_alive_ack',
			explain: 'Wireshark\'s own "Bad TCP" rule',
		});
		expect(byId['hide-chatter'].filter).toBe('!(arp || mdns || ssdp || llmnr || nbns || igmp)');
		expect(byId['dns-skips-router'].explain).toBe("A device using its own name server · your router's address is filled in");
	});

	it('is plain data the device check can read: groups, kinds and common questions, filters as strings', () => {
		expect(Object.keys(data).sort()).toEqual(['common', 'groups', 'kinds']);
		const strings = (o: object) => Object.values(o).every((v) => typeof v === 'string');
		expect(data.kinds.every(strings)).toBe(true);
		expect(data.groups.every((g) => typeof g.id === 'string' && typeof g.label === 'string' && g.filters.every(strings))).toBe(true);
		// common: text fields and one question each, holding only what CommonQuestion allows
		expect(data.common).toHaveLength(5);
		for (const c of data.common) {
			expect(Object.keys(c).sort()).toEqual(['explain', 'id', 'label', 'question']);
			expect([c.id, c.label, c.explain].every((v) => typeof v === 'string' && v)).toBe(true);
			expect(Object.keys(c.question).sort()).toEqual(['kinds', 'other', 'port', 'when']);
			expect(c.question.kinds.every((k) => typeof k === 'string')).toBe(true);
		}
	});

	it('has the nine "What" pills, All traffic first with the empty filter', () => {
		expect(KINDS.map((k) => k.label)).toEqual([
			'All traffic',
			'Name lookups',
			'Sites opened',
			'Unencrypted web pages',
			'New connections',
			'Resent data',
			'Pings',
			'Address leases',
			'Remote logins',
		]);
		expect(KINDS[0].filter).toBe('');
		expect(KINDS.slice(1).every((k) => k.filter)).toBe(true);
	});

	it("gives each common question the mockup's filter exactly, with the device left to pick", () => {
		expect(COMMON_QUESTIONS.map((c) => [c.label, filterFor({ device: null, ...c.question }, null)])).toEqual([
			['Which sites did a device open?', 'tls.handshake.type == 1'],
			['What did a device look up?', 'dns.flags.response == 0'],
			['Was anything sent without encryption?', 'http.request'],
			['Why did a connection fail?', 'tcp.flags.reset == 1 || tcp.analysis.retransmission'],
			['Did a name fail to look up?', 'dns.flags.rcode != 0'],
		]);
		expect(COMMON_QUESTIONS.every((c) => c.question.other.kind === 'anyone' && c.question.port === null)).toBe(true);
		// The JSON can't be typed, so check what the cast in packet-library.ts promises
		expect(COMMON_QUESTIONS.every((c) => c.question.when.kind === 'last' && [300, 900, 1800].includes(c.question.when.seconds))).toBe(true);
		expect(COMMON_QUESTIONS.every((c) => !('device' in c.question) && !('limit' in c.question))).toBe(true);
		expect(COMMON_QUESTIONS.every((c) => c.explain)).toBe(true);
	});
});
