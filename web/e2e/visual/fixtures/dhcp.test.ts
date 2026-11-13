import { describe, it, expect } from 'vitest';
import { packetsHref, soleServer } from '../../../src/routes/tools/dhcp-timeline/dhcp-summary.ts';
import { ROUTES } from './index.ts';
import { DHCP_MAC, DHCP_TIMELINE } from './dhcp.ts';

// NET-263: the populated pass must draw a named sender and the packets link, so both layouts are checked
describe('DHCP timeline fixture', () => {
	it('is served, and holds a row with a named server and one with two', () => {
		expect(ROUTES.some((r) => r.path === '/api/dhcp/timeline')).toBe(true);
		const rows = DHCP_TIMELINE.transactions;
		expect(rows.some((t) => soleServer(t) !== null)).toBe(true);
		expect(rows.some((t) => t.server_endpoints.length > 1)).toBe(true);
		expect(rows.every((t) => packetsHref(t, DHCP_MAC) !== null)).toBe(true);
		expect(rows.map((t) => Date.parse(t.ts))).toEqual([...rows.map((t) => Date.parse(t.ts))].sort((a, b) => b - a));
	});
});
