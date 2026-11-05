import { describe, it, expect } from 'vitest';
import type { AlertCountResponse, AlertTimelineResponse } from '../../../src/lib/api/alerts.ts';
import { ALERT_ROUTES } from './alerts.ts';

const populated = <T>(path: string) => ALERT_ROUTES.find((r) => r.path === path)!.populated as T;

describe('alert fixtures', () => {
	// The Alerts page shows both, so a mismatch would be a fixture bug, not an app bug
	it('the hourly timeline sums to the severity counts', () => {
		const { counts } = populated<AlertCountResponse>('/api/alerts/count');
		const { buckets } = populated<AlertTimelineResponse>('/api/alerts/timeline');
		const sum = (key: 'high' | 'medium' | 'low') => buckets.reduce((a, b) => a + b[key], 0);
		expect({ high: sum('high'), medium: sum('medium'), low: sum('low') }).toEqual({
			high: counts.high,
			medium: counts.medium,
			low: counts.low,
		});
		expect(counts.high + counts.medium + counts.low).toBe(counts.total);
	});

	it('uses a real-sized total, so the severity tiles are tested with six-digit counts', () => {
		expect(populated<AlertCountResponse>('/api/alerts/count').counts.total).toBeGreaterThanOrEqual(100_000);
	});
});
