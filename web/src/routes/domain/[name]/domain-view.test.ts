import { describe, it, expect } from 'vitest';
import { alertCoverage } from './domain-view';

describe('alertCoverage', () => {
	it('says how few alerts carry a host name', () => {
		expect(alertCoverage({ tagged: 1, alerts_in_window: 1057, with_host_field: 12 })).toBe('Only 12 of 1,057 alerts in this window carry a host name.');
	});

	it('says so when none do', () => {
		expect(alertCoverage({ tagged: null, alerts_in_window: 57, with_host_field: 0 })).toBe('Only 0 of 57 alerts in this window carry a host name.');
	});

	it('says so when all do, and when there were no alerts', () => {
		expect(alertCoverage({ tagged: 0, alerts_in_window: 1, with_host_field: 1 })).toBe('The only alert in this window carries a host name.');
		expect(alertCoverage({ tagged: 0, alerts_in_window: 3, with_host_field: 3 })).toBe('All 3 alerts in this window carry a host name.');
		expect(alertCoverage({ tagged: null, alerts_in_window: 0, with_host_field: 0 })).toBe('No alerts in this window, so none carry a host name.');
	});
});
