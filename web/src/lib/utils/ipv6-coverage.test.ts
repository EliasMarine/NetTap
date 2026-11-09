import { describe, it, expect } from 'vitest';
import { ipv6LeftOutText, ipv6ListNotes } from './ipv6-coverage';

describe('ipv6LeftOutText (NET-226)', () => {
	it('says why IPv6 was left out, by reason', () => {
		expect(ipv6LeftOutText('no_gateway')).toBe(
			"IPv6 traffic other than link-local isn't counted for this period: no internet traffic showed which device is the router.",
		);
		expect(ipv6LeftOutText('router')).toBe(
			"This device forwards other devices' traffic (it's the router), so only its link-local IPv6 is counted.",
		);
		expect(ipv6LeftOutText('router', 'The device at 192.0.2.1')).toMatch(/^The device at 192\.0\.2\.1 forwards/);
	});

	it('says nothing without a reason', () => {
		expect(ipv6LeftOutText(null)).toBeNull();
		expect(ipv6LeftOutText(undefined)).toBeNull();
	});
});

describe('ipv6ListNotes (NET-226)', () => {
	it('names each router, gives the no-gateway note once and skips rows with nothing left out', () => {
		const notes = ipv6ListNotes([
			{ ip: '192.0.2.1', ipv6_left_out: 9, ipv6_left_out_reason: 'router' },
			{ ip: '192.0.2.7', ipv6_left_out: 3, ipv6_left_out_reason: 'no_gateway' },
			{ ip: '192.0.2.8', ipv6_left_out: 2, ipv6_left_out_reason: 'no_gateway' },
			{ ip: '192.0.2.9', ipv6_left_out: 0, ipv6_left_out_reason: 'router' },
			{ ip: '192.0.2.10' },
		]);
		expect(notes).toHaveLength(2);
		expect(notes[0]).toMatch(/^The device at 192\.0\.2\.1 forwards/);
		expect(notes[1]).toMatch(/^IPv6 traffic other than link-local/);
	});
});
