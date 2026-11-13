import { describe, it, expect } from 'vitest';
import type { PathMtuResult } from '$api/tools';
import { mtuSummary, probeLabel } from './mtu-summary';

const BASE: PathMtuResult = {
	target: '10.8.0.1',
	resolved_ip: '10.8.0.1',
	family: 4,
	interface: 'eno1',
	interface_mtu: 1500,
	largest_confirmed: 1500,
	payload: 1472,
	upper_known: true,
	icmp_reported_mtu: null,
	local_mtu: null,
	first_unanswered: null,
	probes: [],
	status: 'interface',
	error: null,
};
const r = (over: Partial<PathMtuResult>): PathMtuResult => ({ ...BASE, ...over });

describe('path MTU wording (NET-267)', () => {
	it('says full-size packets get through when the interface MTU replied', () => {
		expect(mtuSummary(BASE)).toBe('Full-size packets (1500 bytes) reach 10.8.0.1 from NetTap.');
	});

	it('names the router report when it bounds the path', () => {
		expect(mtuSummary(r({ status: 'icmp_bound', largest_confirmed: 1420, icmp_reported_mtu: 1420 }))).toBe(
			'The path to 10.8.0.1 carries packets up to 1420 bytes. A router reported an MTU of 1420.'
		);
	});

	it('never calls silence a known limit', () => {
		const line = mtuSummary(r({ status: 'unanswered_above', largest_confirmed: 1400, first_unanswered: 1401, upper_known: false }));
		expect(line).toBe(
			'Largest confirmed: 1400 bytes. Probes of 1401 bytes and up got no reply, so the upper limit is unknown. This can be an MTU problem (common over VPNs: small pings work, big transfers stall), or the destination may drop larger pings.'
		);
	});

	it('says when a router report contradicts the probes', () => {
		const line = mtuSummary(r({ status: 'unanswered_above', largest_confirmed: 1400, first_unanswered: 1401, icmp_reported_mtu: 1420, upper_known: false }));
		expect(line).toMatch(/upper limit is unknown\./);
		expect(line).toMatch(/A router reported an MTU of 1420, which the probes did not confirm\.$/);
		expect(mtuSummary(r({ status: 'unanswered_above', largest_confirmed: 1400, first_unanswered: null }))).toMatch(/^Largest confirmed: 1400 bytes\. Larger probes did not get through,/);
	});

	it("presents NetTap's own limit as its own, not a router's", () => {
		const line = mtuSummary(r({ status: 'local_limit', largest_confirmed: 1400, local_mtu: 1400, upper_known: false }))!;
		expect(line).toMatch(/^Largest confirmed: 1400 bytes\. NetTap would not send larger packets: it still holds a 1400-byte limit/);
		expect(line).toMatch(/so the upper limit is unknown\.$/);
		expect(line).not.toMatch(/A router reported/);
		expect(mtuSummary(r({ status: 'local_limit', largest_confirmed: 1400, local_mtu: null, upper_known: false }))).toBe(
			'Largest confirmed: 1400 bytes. NetTap would not send larger packets (ping reported an error), so the upper limit is unknown.'
		);
	});

	it('covers the statuses with no confirmed limit', () => {
		expect(mtuSummary(r({ status: 'floor_unanswered', largest_confirmed: 84, first_unanswered: 576 }))).toBe(
			'10.8.0.1 answers small pings but not 576-byte ones. That points to a possible MTU problem.'
		);
		expect(mtuSummary(r({ status: 'no_ping_reply', largest_confirmed: null }))).toBe('10.8.0.1 did not answer ping, so the MTU cannot be tested from NetTap.');
		expect(mtuSummary(r({ status: 'unreliable' }))).toBe('Replies from 10.8.0.1 were inconsistent, so no size can be confirmed.');
		expect(mtuSummary(r({ status: 'stopped', largest_confirmed: 1300 }))).toBe(
			'The check stopped before it finished. Largest confirmed so far: 1300 bytes, so the upper limit is unknown.'
		);
		expect(mtuSummary(r({ status: 'stopped', largest_confirmed: null }))).toBe('The check stopped before it finished, so no size was confirmed.');
		expect(mtuSummary(r({ status: null, error: 'NetTap has no route to fd00::1.' }))).toBeNull();
	});

	it('names each probe result in words', () => {
		expect(probeLabel({ size: 1500, result: 'reply', mtu: null })).toBe('Reply');
		expect(probeLabel({ size: 1500, result: 'no_reply', mtu: null })).toBe('No reply (2 tries)');
		expect(probeLabel({ size: 1500, result: 'icmp_too_big', mtu: 1420 })).toBe('Router: too big, MTU 1420');
		expect(probeLabel({ size: 1500, result: 'icmp_too_big', mtu: null })).toBe('Router: too big');
		expect(probeLabel({ size: 1500, result: 'local_error', mtu: 1400 })).toBe("Not sent: NetTap's limit is 1400");
		expect(probeLabel({ size: 84, result: 'local_error', mtu: null })).toBe('Not sent: ping error');
	});
});
