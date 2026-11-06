import { describe, it, expect } from 'vitest';
import { NAV_GROUPS, isActive, pageTitle, isBare } from './nav';

describe('navigation', () => {
	// OLD CODE START — NET-160: 17 pages; Investigations and Security posture were left out
	// it('keeps the same 17 pages, grouped as the design system shows', () => { … });
	// OLD CODE END
	it('lists 19 pages, Investigations and Security posture included, grouped as the design system shows', () => {
		expect(NAV_GROUPS.map((g) => g.label)).toEqual(['Overview', 'Investigate', 'Devices', 'System']);
		const hrefs = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.href));
		expect(hrefs.sort()).toEqual(
			[
				'/', '/alerts', '/bandwidth', '/certificates', '/changelog', '/compliance', '/connections', '/devices', '/dns',
				'/infrastructure', '/investigations', '/iot', '/live', '/logs', '/pcap', '/settings', '/system', '/threats', '/tools',
			].sort(),
		);
		const item = (href: string) => NAV_GROUPS.flatMap((g) => g.items.map((i) => ({ group: g.label, ...i }))).find((i) => i.href === href);
		expect(item('/investigations')).toMatchObject({ group: 'Investigate', label: 'Investigations' });
		expect(item('/compliance')).toMatchObject({ group: 'System', label: 'Security posture' });
	});

	it.each([
		['/', '/', true],
		['/', '/alerts', false],
		['/alerts', '/alerts', true],
		['/alerts', '/alerts/malware-c2', true],
		['/system', '/system/updates', true],
		['/system', '/systemfoo', false],
	])('isActive(%s, %s) is %s', (href, path, expected) => {
		expect(isActive(href, path)).toBe(expected);
	});

	it('names the section for nested pages', () => {
		expect(pageTitle('/devices/192.168.1.4')).toBe('Devices');
		expect(pageTitle('/lookup/whois')).toBe('NetTap');
	});

	it('shows no shell on sign-in and setup only (Go Live keeps it, as before)', () => {
		expect(isBare('/login')).toBe(true);
		expect(isBare('/setup')).toBe(true);
		expect(isBare('/go-live')).toBe(false);
		expect(isBare('/')).toBe(false);
	});
});
