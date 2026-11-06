import { describe, it, expect } from 'vitest';
import { byteFigure, canonicalName, certificatesHref, chartTime, isHostName, logsHrefForIp, measuredNote, rangeWindow } from './drilldown';

const MB = 1024 ** 2;

describe('drill-down wording', () => {
	it('says Not measured when no connection carried a byte count', () => {
		expect(byteFigure({ total: 0, measured: 0, connections: 120, partial: true })).toBe('Not measured');
		expect(measuredNote({ total: 0, measured: 0, connections: 120, partial: true })).toBeNull();
	});

	it('gives a partial total as a lower bound, with how many were measured', () => {
		const b = { total: 3 * MB, measured: 118, connections: 120, partial: true };
		expect(byteFigure(b)).toBe('at least 3.0 MB');
		expect(measuredNote(b)).toBe('118 of 120 connections measured');
	});

	it('gives a complete total as it is, with no note', () => {
		const b = { total: 3 * MB, measured: 120, connections: 120, partial: false };
		expect(byteFigure(b)).toBe('3.0 MB');
		expect(measuredNote(b)).toBeNull();
	});

	it('counts no connections as a measured 0 B', () => {
		expect(byteFigure({ total: 0, measured: 0, connections: 0, partial: false })).toBe('0 B');
	});

	it('builds the window ending now', () => {
		const now = new Date('2026-11-06T12:00:00Z');
		expect(rangeWindow(24, now)).toEqual({ from: '2026-11-05T12:00:00.000Z', to: '2026-11-06T12:00:00.000Z' });
	});

	it('links certificates with the site, server and window', () => {
		const href = certificatesHref({ site: 'example.com', server: '2001:db8::1', from: 'a', to: 'b' });
		const url = new URL(href, 'http://x');
		expect(url.pathname).toBe('/certificates');
		expect(Object.fromEntries(url.searchParams)).toEqual({ site: 'example.com', server: '2001:db8::1', from: 'a', to: 'b' });
		expect(certificatesHref({ site: null, server: '1.2.3.4', from: 'a', to: 'b' })).toBe('/certificates?server=1.2.3.4&from=a&to=b');
	});

	it('canonicalises the site name as recorded, so both spellings filter the same', () => {
		expect(certificatesHref({ site: 'Example.COM.', from: 'a', to: 'b' })).toBe('/certificates?site=example.com&from=a&to=b');
	});

	it('labels timeline points for the bucket size the daemon picks', () => {
		const t = '2026-11-06T18:00:00Z';
		expect(chartTime(t, 24)).toMatch(/^\d\d:\d\d$/);
		expect(chartTime(t, 168)).toMatch(/^6 Nov, \d\d:\d\d$/);
		expect(chartTime(t, 720)).toBe('6 Nov');
	});

	it('searches Log Explorer for either side, quoted', () => {
		// OLD CODE START: expect(decodeURIComponent(logsHrefForIp('2001:db8::1').split('=')[1])).toBe(…); OLD CODE END
		const url = new URL(logsHrefForIp('2001:db8::1', '7d'), 'http://x');
		expect(url.searchParams.get('query')).toBe('(source.ip:"2001:db8::1" OR destination.ip:"2001:db8::1")');
		// Log Explorer opens on the window the link came from, not its own 24 hours
		expect(url.searchParams.get('range')).toBe('7d');
	});

	it('canonicalises a name as the daemon matches it, and knows a host name by its rule', () => {
		expect(canonicalName(' Example.COM. ')).toBe('example.com');
		expect(canonicalName('example.com..')).toBe('example.com.');
		for (const ok of ['example.com', 'Stream.Example.NET.', '_dmarc.example.org', 'a-b.c']) expect(isHostName(ok)).toBe(true);
		for (const bad of ['', '(no name)', 'a..b', 'exa mple.com', 'x'.repeat(64) + '.com', 'example.com:443']) expect(isHostName(bad)).toBe(false);
	});
});
