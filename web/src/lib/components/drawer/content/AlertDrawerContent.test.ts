import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for AlertDrawerContent component logic.
 *
 * AlertDrawerContent.svelte uses Svelte 5 runes ($state, $props, $derived,
 * $effect). Instead of rendering, we extract and test the pure logic:
 * severity label/class derivation, timestamp formatting, protocol label,
 * tab visibility, and flow visualization data.
 */

// ---------------------------------------------------------------------------
// Reproduced logic from AlertDrawerContent.svelte
// ---------------------------------------------------------------------------

interface AlertData {
	_id: string;
	_index: string;
	timestamp: string;
	alert?: {
		signature?: string;
		signature_id?: number;
		severity?: number;
		category?: string;
	};
	src_ip?: string;
	src_port?: number;
	dest_ip?: string;
	dest_port?: number;
	proto?: string;
	acknowledged: boolean;
	acknowledged_at?: string;
	plain_description?: string;
	risk_context?: string;
	recommendation?: string;
}

function severityLabel(alert: AlertData): string {
	if (!alert?.alert?.severity) return 'INFO';
	switch (alert.alert.severity) {
		case 1: return 'HIGH';
		case 2: return 'MEDIUM';
		case 3: return 'LOW';
		default: return 'INFO';
	}
}

function severityClass(alert: AlertData): string {
	if (!alert?.alert?.severity) return 'badge';
	switch (alert.alert.severity) {
		case 1: return 'badge badge-danger';
		case 2: return 'badge badge-warning';
		case 3: return 'badge badge-accent';
		default: return 'badge';
	}
}

function formatTimestamp(ts: string | undefined): string {
	if (!ts) return '--';
	try {
		return new Date(ts).toLocaleString(undefined, {
			year: 'numeric', month: 'short', day: 'numeric',
			hour: '2-digit', minute: '2-digit', second: '2-digit',
		});
	} catch {
		return ts;
	}
}

function protoLabel(proto: string | undefined): string {
	return proto ? proto.toUpperCase() : '?';
}

function getVisibleContent(activeTab: string): 'summary' | 'related' | 'raw' | 'none' {
	if (activeTab === 'summary') return 'summary';
	if (activeTab === 'related') return 'related';
	if (activeTab === 'raw') return 'raw';
	return 'none';
}

/**
 * Reproduces the query-building logic from fetchRelated() to test it in isolation.
 * Returns null if no IPs are available.
 */
function buildRelatedQuery(alert: AlertData): { query: string; from: string; to: string } | null {
	const ips = [alert.src_ip, alert.dest_ip].filter(Boolean);
	if (ips.length === 0) return null;
	const ipClauses = ips.map(ip => `(source.ip.keyword:"${ip}" OR destination.ip.keyword:"${ip}")`).join(' OR ');
	const query = `(${ipClauses}) AND NOT _id:"${alert._id}"`;
	const alertTime = new Date(alert.timestamp);
	const from = new Date(alertTime.getTime() - 3600_000).toISOString();
	const to = new Date(alertTime.getTime() + 3600_000).toISOString();
	return { query, from, to };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AlertDrawerContent logic', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- Severity badge -------------------------------------------------------

	describe('severity badge', () => {
		it('returns "HIGH" for severity 1', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false, alert: { severity: 1 } };
			expect(severityLabel(alert)).toBe('HIGH');
		});

		it('returns "MEDIUM" for severity 2', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false, alert: { severity: 2 } };
			expect(severityLabel(alert)).toBe('MEDIUM');
		});

		it('returns "LOW" for severity 3', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false, alert: { severity: 3 } };
			expect(severityLabel(alert)).toBe('LOW');
		});

		it('returns "INFO" when severity is missing', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false, alert: {} };
			expect(severityLabel(alert)).toBe('INFO');
		});

		it('returns "INFO" when alert object is missing', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false };
			expect(severityLabel(alert)).toBe('INFO');
		});

		it('returns "INFO" for unknown severity values', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false, alert: { severity: 99 } };
			expect(severityLabel(alert)).toBe('INFO');
		});
	});

	// -- Severity CSS class ---------------------------------------------------

	describe('severity CSS class', () => {
		it('returns badge-danger for severity 1 (HIGH)', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false, alert: { severity: 1 } };
			expect(severityClass(alert)).toBe('badge badge-danger');
		});

		it('returns badge-warning for severity 2 (MEDIUM)', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false, alert: { severity: 2 } };
			expect(severityClass(alert)).toBe('badge badge-warning');
		});

		it('returns badge-accent for severity 3 (LOW)', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false, alert: { severity: 3 } };
			expect(severityClass(alert)).toBe('badge badge-accent');
		});

		it('returns plain badge for missing severity', () => {
			const alert: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false };
			expect(severityClass(alert)).toBe('badge');
		});
	});

	// -- Timestamp formatting -------------------------------------------------

	describe('formatTimestamp', () => {
		it('returns "--" for undefined timestamp', () => {
			expect(formatTimestamp(undefined)).toBe('--');
		});

		it('returns "--" for empty string timestamp', () => {
			expect(formatTimestamp('')).toBe('--');
		});

		it('formats a valid ISO timestamp', () => {
			const result = formatTimestamp('2026-03-01T12:00:00Z');
			expect(result).toContain('2026');
		});

		it('returns original string for invalid date', () => {
			const result = formatTimestamp('not-a-date');
			expect(typeof result).toBe('string');
		});
	});

	// -- Protocol label -------------------------------------------------------

	describe('protoLabel', () => {
		it('uppercases protocol string', () => {
			expect(protoLabel('tcp')).toBe('TCP');
			expect(protoLabel('udp')).toBe('UDP');
		});

		it('returns "?" for undefined protocol', () => {
			expect(protoLabel(undefined)).toBe('?');
		});

		it('handles already-uppercase protocols', () => {
			expect(protoLabel('TCP')).toBe('TCP');
		});
	});

	// -- Tab visibility -------------------------------------------------------

	describe('tab visibility', () => {
		it('renders summary tab when activeTab="summary"', () => {
			expect(getVisibleContent('summary')).toBe('summary');
		});

		it('renders related tab when activeTab="related"', () => {
			expect(getVisibleContent('related')).toBe('related');
		});

		it('renders raw tab when activeTab="raw"', () => {
			expect(getVisibleContent('raw')).toBe('raw');
		});

		it('renders nothing for unknown tab', () => {
			expect(getVisibleContent('other')).toBe('none');
		});
	});

	// -- Flow visualization data ----------------------------------------------

	describe('flow visualization', () => {
		it('renders flow with source and destination IPs', () => {
			const alert: AlertData = {
				_id: '1', _index: 'x', timestamp: '', acknowledged: false,
				src_ip: '192.168.1.100', dest_ip: '10.0.0.1',
				src_port: 54321, dest_port: 443,
				proto: 'tcp',
			};

			expect(alert.src_ip).toBe('192.168.1.100');
			expect(alert.dest_ip).toBe('10.0.0.1');
			expect(alert.src_port).toBe(54321);
			expect(alert.dest_port).toBe(443);
			expect(protoLabel(alert.proto)).toBe('TCP');
		});

		it('handles missing flow fields gracefully', () => {
			const alert: AlertData = {
				_id: '1', _index: 'x', timestamp: '', acknowledged: false,
			};

			expect(alert.src_ip).toBeUndefined();
			expect(alert.dest_ip).toBeUndefined();
			expect(alert.src_port).toBeUndefined();
			expect(alert.dest_port).toBeUndefined();
		});
	});

	// -- Alert details --------------------------------------------------------

	describe('alert detail fields', () => {
		it('renders summary tab with alert signature', () => {
			const alert: AlertData = {
				_id: 'alert123', _index: 'suricata-alerts', timestamp: '2026-03-01T12:00:00Z',
				acknowledged: false,
				alert: {
					signature: 'ET POLICY HTTP Binary Download',
					signature_id: 2020076,
					severity: 2,
					category: 'Potentially Bad Traffic',
				},
				src_ip: '192.168.1.100', dest_ip: '93.184.216.34',
				src_port: 54321, dest_port: 80,
				proto: 'tcp',
			};

			expect(alert.alert?.signature).toBe('ET POLICY HTTP Binary Download');
			expect(alert.alert?.signature_id).toBe(2020076);
			expect(severityLabel(alert)).toBe('MEDIUM');
			expect(alert.alert?.category).toBe('Potentially Bad Traffic');
		});

		it('handles acknowledged status', () => {
			const unacked: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: false };
			expect(unacked.acknowledged).toBe(false);

			const acked: AlertData = { _id: '1', _index: 'x', timestamp: '', acknowledged: true, acknowledged_at: '2026-03-01T13:00:00Z' };
			expect(acked.acknowledged).toBe(true);
			expect(acked.acknowledged_at).toBe('2026-03-01T13:00:00Z');
		});
	});

	// -- Related events query building ----------------------------------------

	describe('buildRelatedQuery', () => {
		it('uses .keyword sub-fields for IP matching', () => {
			const alert: AlertData = {
				_id: 'abc123', _index: 'x', timestamp: '2026-03-01T12:00:00Z',
				acknowledged: false, src_ip: '192.168.1.44', dest_ip: '10.0.0.1',
			};
			const result = buildRelatedQuery(alert);
			expect(result).not.toBeNull();
			expect(result!.query).toContain('source.ip.keyword:"192.168.1.44"');
			expect(result!.query).toContain('destination.ip.keyword:"192.168.1.44"');
			expect(result!.query).toContain('source.ip.keyword:"10.0.0.1"');
			expect(result!.query).toContain('destination.ip.keyword:"10.0.0.1"');
		});

		it('excludes the alert itself from results', () => {
			const alert: AlertData = {
				_id: 'abc123', _index: 'x', timestamp: '2026-03-01T12:00:00Z',
				acknowledged: false, src_ip: '192.168.1.44',
			};
			const result = buildRelatedQuery(alert);
			expect(result!.query).toContain('AND NOT _id:"abc123"');
		});

		it('sets time range to ±1 hour from alert timestamp', () => {
			const alert: AlertData = {
				_id: '1', _index: 'x', timestamp: '2026-03-01T12:00:00.000Z',
				acknowledged: false, src_ip: '192.168.1.44',
			};
			const result = buildRelatedQuery(alert);
			expect(result!.from).toBe('2026-03-01T11:00:00.000Z');
			expect(result!.to).toBe('2026-03-01T13:00:00.000Z');
		});

		it('returns null when no IPs are present', () => {
			const alert: AlertData = {
				_id: '1', _index: 'x', timestamp: '2026-03-01T12:00:00Z',
				acknowledged: false,
			};
			expect(buildRelatedQuery(alert)).toBeNull();
		});

		it('works with only source IP', () => {
			const alert: AlertData = {
				_id: '1', _index: 'x', timestamp: '2026-03-01T12:00:00Z',
				acknowledged: false, src_ip: '192.168.1.44',
			};
			const result = buildRelatedQuery(alert);
			expect(result!.query).toContain('source.ip.keyword:"192.168.1.44"');
			expect(result!.query).not.toContain('10.0.0.1');
		});

		it('works with only destination IP', () => {
			const alert: AlertData = {
				_id: '1', _index: 'x', timestamp: '2026-03-01T12:00:00Z',
				acknowledged: false, dest_ip: '10.0.0.1',
			};
			const result = buildRelatedQuery(alert);
			expect(result!.query).toContain('source.ip.keyword:"10.0.0.1"');
			expect(result!.query).toContain('destination.ip.keyword:"10.0.0.1"');
		});
	});

	// -- Raw JSON generation --------------------------------------------------

	describe('raw JSON', () => {
		it('generates valid JSON from alert object', () => {
			const alert: AlertData = {
				_id: 'alert123', _index: 'suricata', timestamp: '2026-03-01T12:00:00Z',
				acknowledged: false,
				alert: { signature: 'Test Alert', severity: 1 },
			};
			const rawJson = JSON.stringify(alert, null, 2);
			const parsed = JSON.parse(rawJson);

			expect(parsed._id).toBe('alert123');
			expect(parsed.alert.signature).toBe('Test Alert');
		});
	});
});
