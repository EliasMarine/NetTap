import { describe, it, expect } from 'vitest';
import { growthSummary } from './storage-estimate';
import type { GrowthEstimate } from '$api/system';

const MEASURED: GrowthEstimate = {
	index_bytes_per_day: 2.1e9,
	index_days_measured: 7,
	pcap_bytes_per_day: 66.3e9,
	pcap_days_measured: 7.4,
	pcap_days_kept: 7.4,
};

describe('growthSummary (B-m)', () => {
	it('states both measured rates, the hot tier they need and the PCAP actually kept', () => {
		expect(growthSummary(MEASURED, 90)).toBe(
			'Estimate from the last 7 days: indices grow about 2.1 GB a day, so 90 days of them need about 189.0 GB. ' +
				'PCAP grows about 66.3 GB a day (measured over 7.4 days), so about 7.4 days of it is kept.',
		);
	});

	it('says there is no estimate yet rather than assume a rate', () => {
		const none = { ...MEASURED, index_bytes_per_day: null, pcap_bytes_per_day: null };
		for (const estimate of [none, null, undefined]) {
			expect(growthSummary(estimate, 90)).toMatch(/^No estimate yet: .* needs a full day of data first\.$/);
		}
	});

	it('gives the one rate it has, and leaves out days kept it could not work out', () => {
		const pcapOnly = { ...MEASURED, index_bytes_per_day: null, index_days_measured: 0, pcap_days_kept: null };
		expect(growthSummary(pcapOnly, 90)).toBe('PCAP grows about 66.3 GB a day (measured over 7.4 days).');
		expect(growthSummary({ ...MEASURED, index_days_measured: 1, pcap_bytes_per_day: null }, 1)).toBe(
			'Estimate from the last 1 day: indices grow about 2.1 GB a day, so 1 day of them need about 2.1 GB.',
		);
	});
});
