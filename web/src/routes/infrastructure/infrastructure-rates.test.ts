import { describe, it, expect, vi, afterEach } from 'vitest';
import { render } from '@testing-library/svelte';
import InfrastructurePage from './+page.svelte';

// On the G11 Zeek showed 1,601 evt/s for ~5 connections/s: the page asked for "now-5m", the
// daemon answered for 24 h, and the page divided a day by 300 s. Suricata always said 0: it read
// d.total, which the count reply nests under counts.

describe('Infrastructure — Zeek and Suricata rates', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('asks for the last 5 minutes as real times and divides those counts by 300 s', async () => {
		const asked: string[] = [];
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const path = url.split('?')[0];
				if (path === '/api/traffic/summary' || path === '/api/alerts/count') asked.push(url);
				if (path === '/api/traffic/summary') return { ok: true, status: 200, json: async () => ({ connection_count: 1564 }) };
				if (path === '/api/alerts/count') return { ok: true, status: 200, json: async () => ({ counts: { total: 232, high: 1, medium: 39, low: 192 } }) };
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);

		render(InfrastructurePage);

		// the stage's status line in the capture pipeline strip
		const metric = (label: string) =>
			[...document.querySelectorAll('.pipe-item')]
				.find((el) => el.querySelector('.pipe-k')?.textContent?.trim() === label)
				?.querySelector('.pipe-v')?.textContent?.trim();
		await vi.waitFor(() => expect(metric('Zeek')).toBe('5.2 conn/s'));
		expect(metric('Suricata')).toBe('0.8 alerts/s');
		for (const url of asked) {
			const params = new URL(url, 'https://nettap.test').searchParams;
			const span = Date.parse(params.get('to') ?? '') - Date.parse(params.get('from') ?? '');
			expect(span).toBe(300_000);
		}
	});
});
