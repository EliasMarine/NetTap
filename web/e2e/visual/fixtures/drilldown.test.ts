import { describe, it, expect } from 'vitest';
import type { AddressSummary, DomainSummary } from '../../../src/lib/api/drilldown.ts';
import { ADDRESS, ADDRESS_EMPTY, ADDRESS_QUIET, DOMAIN, DOMAIN_EMPTY, DOMAIN_QUIET, DRILLDOWN_ROUTES } from './drilldown.ts';

// NET-160: the fixtures must add up the way the daemon's figures do, or page tests and visual
// baselines would show numbers the real page never could
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

describe('address fixtures', () => {
	it.each([
		['complete', ADDRESS],
		['quiet', ADDRESS_QUIET],
		['empty', ADDRESS_EMPTY],
	] as [string, AddressSummary][])('%s: totals agree with their parts', (_name, a) => {
		expect(sum(a.timeline.map((p) => p.n))).toBe(a.connections);
		for (const b of [a.bytes_to, a.bytes_from]) {
			expect(b.connections).toBe(a.connections);
			expect(b.measured).toBeLessThanOrEqual(b.connections);
			expect(b.partial).toBe(b.measured < b.connections);
		}
		if (a.peers_complete) {
			expect(sum(a.peers.map((p) => p.connections))).toBe(a.connections);
			// a partial peer makes the whole total partial
			if (a.peers.some((p) => p.bytes_partial)) expect(a.bytes_to.partial).toBe(true);
			expect(sum(a.peers.map((p) => p.bytes_to))).toBe(a.bytes_to.total);
			expect(sum(a.peers.map((p) => p.bytes_from))).toBe(a.bytes_from.total);
		}
		if (a.ports_complete) expect(sum(a.ports.map((p) => p.connections))).toBeLessThanOrEqual(a.connections);
		for (const t of a.tls_names) expect(sum(Object.values(t.statuses))).toBe(t.sessions);
	});
});

describe('domain fixtures', () => {
	it.each([
		['complete', DOMAIN],
		['quiet', DOMAIN_QUIET],
		['empty', DOMAIN_EMPTY],
	] as [string, DomainSummary][])('%s: totals agree with their parts', (_name, d) => {
		expect(sum(d.dns.timeline.map((p) => p.n))).toBe(d.dns.lookups);
		expect(sum(d.dns.rcodes.map((r) => r.lookups))).toBe(d.dns.lookups);
		if (d.dns.askers_complete) expect(sum(d.dns.askers.map((a) => a.lookups))).toBe(d.dns.lookups);
		if (d.dns.answers_complete) expect(d.dns.addresses).toBe(d.dns.answers.filter((a) => a.kind === 'ip').length);
		else expect(d.dns.addresses).toBeNull();
		if (d.tls.servers_complete) expect(sum(d.tls.servers.map((s) => s.sessions))).toBe(d.tls.sessions);
		if (d.tls.clients_complete) expect(sum(d.tls.clients.map((c) => c.sessions))).toBe(d.tls.sessions);
		expect(sum(Object.values(d.tls.statuses))).toBe(d.tls.sessions);
		expect(d.alerts.with_host_field).toBeLessThanOrEqual(d.alerts.alerts_in_window);
		expect(d.alerts.tagged === null).toBe(d.alerts.with_host_field === 0);
	});
});

describe('drill-down fixture routes', () => {
	it('answers the LAN policy and both pages in every mode', () => {
		for (const path of ['/api/network/lan', '/api/addresses/198.51.100.10', '/api/addresses/192.0.2.80', '/api/domains/x.example', '/api/domains/quiet.example.org']) {
			expect(DRILLDOWN_ROUTES.some((r) => (typeof r.path === 'string' ? r.path === path : r.path.test(path)))).toBe(true);
		}
	});
});
