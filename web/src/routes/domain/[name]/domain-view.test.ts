import { describe, it, expect } from 'vitest';
import { alertCoverage, taggedFigure, unmatchedNote } from './domain-view';

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

// NET-178: a host field stored as text makes the tagged count partial, and the card says so
const TLS = 'tls.client.server_name';
const counted = { alerts_in_window: 57, with_host_field: 12, matched_fields: ['related.hosts', 'url.domain'] };

describe('taggedFigure', () => {
	it('is a lower bound when a host field can\'t be matched, and no count when none can', () => {
		expect(taggedFigure({ ...counted, tagged: 1234, tagged_partial: true, unmatched_fields: [TLS] })).toBe('At least 1,234');
		expect(taggedFigure({ ...counted, tagged: 0, tagged_partial: true, unmatched_fields: [TLS] })).toBe('At least 0');
		expect(taggedFigure({ ...counted, tagged: null, tagged_partial: true, matched_fields: [], unmatched_fields: [TLS] })).toBe("Can't be counted on this NetTap");
	});

	it('is the exact count or Not recorded otherwise, from an older daemon too', () => {
		expect(taggedFigure({ ...counted, tagged: 1234, tagged_partial: false, unmatched_fields: [] })).toBe('1,234');
		expect(taggedFigure({ ...counted, tagged: null, tagged_partial: false, unmatched_fields: [TLS] })).toBe('Not recorded');
		expect(taggedFigure({ tagged: 3, alerts_in_window: 5, with_host_field: 4 })).toBe('3');
		expect(taggedFigure({ tagged: null, alerts_in_window: 5, with_host_field: 0 })).toBe('Not recorded');
	});
});

describe('unmatchedNote', () => {
	it('names the fields it can\'t search in words', () => {
		expect(unmatchedNote({ ...counted, tagged: 1, tagged_partial: true, unmatched_fields: [TLS] })).toBe(
			"TLS names are stored on this NetTap in a way that can't be matched exactly, so alerts that name this domain only there aren't counted.",
		);
		expect(unmatchedNote({ ...counted, tagged: null, tagged_partial: true, unmatched_fields: ['related.hosts', TLS, 'url.domain'] })).toBe(
			"Related hosts, TLS names and URL domains are stored on this NetTap in a way that can't be matched exactly, so alerts that name this domain only there aren't counted.",
		);
	});

	it('says nothing when the count is whole', () => {
		expect(unmatchedNote({ ...counted, tagged: 1, tagged_partial: false, unmatched_fields: [] })).toBeNull();
		expect(unmatchedNote({ ...counted, tagged: null, tagged_partial: false, unmatched_fields: [TLS] })).toBeNull();
		expect(unmatchedNote({ tagged: 1, alerts_in_window: 1, with_host_field: 1 })).toBeNull();
	});
});
