import { describe, it, expect } from 'vitest';
import { byteFigure, certificatesHref, logsHrefForIp, measuredNote, rangeWindow } from './drilldown';

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

	it('searches Log Explorer for either side, quoted', () => {
		expect(decodeURIComponent(logsHrefForIp('2001:db8::1').split('=')[1])).toBe('(source.ip:"2001:db8::1" OR destination.ip:"2001:db8::1")');
	});
});
