import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import SessionTimeline from './SessionTimeline.svelte';

// The restyle gives the chart role="img" and a headline label naming the busiest bucket.
describe('SessionTimeline — chart headline', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('names the busiest bucket and its session count', () => {
		const buckets = [
			{ timestamp: '2026-11-03T10:00:00Z', total: 12, protocols: { tcp: 12 } },
			{ timestamp: '2026-11-03T11:00:00Z', total: 30, protocols: { tcp: 20, udp: 10 } },
			{ timestamp: '2026-11-03T12:00:00Z', total: 7, protocols: { udp: 7 } },
		];
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		render(SessionTimeline, { buckets });
		expect(screen.getByRole('img', { name: /^Session volume, busiest at .+ with 30 sessions$/ })).toBeInTheDocument();
	});
});
