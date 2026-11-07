import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import SessionTimeline from './SessionTimeline.svelte';
import type { ConnectionTimelineBucket } from '$api/traffic';

// The restyle gives the chart role="img" and a headline label naming the busiest bucket.
describe('SessionTimeline — chart headline', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('names the busiest bucket and its session count', () => {
		const buckets: ConnectionTimelineBucket[] = [
			{ timestamp: '2026-11-03T10:00:00Z', total: 12, protocols: { tcp: 12 } },
			{ timestamp: '2026-11-03T11:00:00Z', total: 30, protocols: { tcp: 20, udp: 10 } },
			{ timestamp: '2026-11-03T12:00:00Z', total: 7, protocols: { udp: 7 } },
		];
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		render(SessionTimeline, { buckets });
		expect(screen.getByRole('img', { name: /^Session volume, busiest at .+ with 30 sessions$/ })).toBeInTheDocument();
	});

	it('prints axis counts with separators and keeps the last time label inside the chart (NET-192)', () => {
		const buckets: ConnectionTimelineBucket[] = [
			{ timestamp: '2026-11-03T10:00:00Z', total: 1200, protocols: { tcp: 1200 } },
			{ timestamp: '2026-11-03T11:00:00Z', total: 48_000, protocols: { tcp: 40_000, udp: 8_000 } },
		];
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		const { container } = render(SessionTimeline, { buckets });
		const labels = [...container.querySelectorAll('text.ax')];
		expect(labels.map((t) => t.textContent?.trim())).toContain('48,000');
		expect(labels.at(-1)?.getAttribute('text-anchor')).toBe('end');
	});
});
