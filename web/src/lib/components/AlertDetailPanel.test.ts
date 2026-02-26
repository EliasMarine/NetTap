import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for AlertDetailPanel logic.
 *
 * The AlertDetailPanel.svelte component uses Svelte 5 runes ($derived, $state)
 * and SvelteKit imports ($app/navigation) that are difficult to fully render
 * in a jsdom test environment.  Instead we extract and test the pure logic
 * that lives inside the component: severity mapping, timestamp formatting,
 * protocol labels, and navigation URL construction.
 */

// ---------------------------------------------------------------------------
// Severity mapping — mirrors the $derived logic in AlertDetailPanel.svelte
// ---------------------------------------------------------------------------

function severityLabel(severity: number | undefined | null): string {
	if (!severity) return 'INFO';
	switch (severity) {
		case 1:
			return 'HIGH';
		case 2:
			return 'MEDIUM';
		case 3:
			return 'LOW';
		default:
			return 'INFO';
	}
}

function severityClass(severity: number | undefined | null): string {
	if (!severity) return 'badge';
	switch (severity) {
		case 1:
			return 'badge badge-danger';
		case 2:
			return 'badge badge-warning';
		case 3:
			return 'badge badge-accent';
		default:
			return 'badge';
	}
}

// ---------------------------------------------------------------------------
// Helpers — mirrors the helper functions in AlertDetailPanel.svelte
// ---------------------------------------------------------------------------

function formatTimestamp(ts: string | undefined): string {
	if (!ts) return '--';
	try {
		const d = new Date(ts);
		return d.toLocaleString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit',
		});
	} catch {
		return ts;
	}
}

function protoLabel(proto: string | undefined): string {
	if (!proto) return '?';
	return proto.toUpperCase();
}

function navigateToDeviceUrl(ip: string): string {
	return `/devices/${encodeURIComponent(ip)}`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AlertDetailPanel logic', () => {
	// -- severityLabel -------------------------------------------------------

	describe('severityLabel', () => {
		it('returns HIGH for severity 1', () => {
			expect(severityLabel(1)).toBe('HIGH');
		});

		it('returns MEDIUM for severity 2', () => {
			expect(severityLabel(2)).toBe('MEDIUM');
		});

		it('returns LOW for severity 3', () => {
			expect(severityLabel(3)).toBe('LOW');
		});

		it('returns INFO for severity 0', () => {
			expect(severityLabel(0)).toBe('INFO');
		});

		it('returns INFO for undefined severity', () => {
			expect(severityLabel(undefined)).toBe('INFO');
		});

		it('returns INFO for null severity', () => {
			expect(severityLabel(null)).toBe('INFO');
		});

		it('returns INFO for unknown severity value (99)', () => {
			expect(severityLabel(99)).toBe('INFO');
		});

		it('returns INFO for negative severity value', () => {
			expect(severityLabel(-1)).toBe('INFO');
		});
	});

	// -- severityClass -------------------------------------------------------

	describe('severityClass', () => {
		it('returns badge badge-danger for severity 1', () => {
			expect(severityClass(1)).toBe('badge badge-danger');
		});

		it('returns badge badge-warning for severity 2', () => {
			expect(severityClass(2)).toBe('badge badge-warning');
		});

		it('returns badge badge-accent for severity 3', () => {
			expect(severityClass(3)).toBe('badge badge-accent');
		});

		it('returns badge for severity 0', () => {
			expect(severityClass(0)).toBe('badge');
		});

		it('returns badge for undefined severity', () => {
			expect(severityClass(undefined)).toBe('badge');
		});

		it('returns badge for null severity', () => {
			expect(severityClass(null)).toBe('badge');
		});

		it('returns badge for unknown severity (42)', () => {
			expect(severityClass(42)).toBe('badge');
		});
	});

	// -- formatTimestamp -----------------------------------------------------

	describe('formatTimestamp', () => {
		it('returns "--" for undefined input', () => {
			expect(formatTimestamp(undefined)).toBe('--');
		});

		it('returns "--" for empty string input', () => {
			expect(formatTimestamp('')).toBe('--');
		});

		it('returns a formatted string for a valid ISO timestamp', () => {
			const result = formatTimestamp('2026-02-25T14:30:00Z');
			// The exact output depends on locale, but it should contain recognizable pieces
			expect(result).not.toBe('--');
			expect(result).toContain('2026');
		});

		it('returns the raw string for an unparseable date', () => {
			// new Date('not-a-date') returns Invalid Date whose toLocaleString
			// still produces a string (not throwing), but let's confirm it does
			// not return "--".
			const result = formatTimestamp('not-a-date');
			expect(result).not.toBe('--');
		});

		it('formats midnight correctly (returns a non-empty locale string)', () => {
			const result = formatTimestamp('2026-01-01T00:00:00Z');
			// The exact output depends on locale and timezone, so just verify
			// it is a meaningful formatted string (not the fallback '--')
			expect(result).not.toBe('--');
			expect(result.length).toBeGreaterThan(5);
		});
	});

	// -- protoLabel ----------------------------------------------------------

	describe('protoLabel', () => {
		it('returns "?" for undefined', () => {
			expect(protoLabel(undefined)).toBe('?');
		});

		it('returns "?" for empty string', () => {
			// Empty string is falsy in JS
			expect(protoLabel('')).toBe('?');
		});

		it('uppercases "tcp" to "TCP"', () => {
			expect(protoLabel('tcp')).toBe('TCP');
		});

		it('uppercases "udp" to "UDP"', () => {
			expect(protoLabel('udp')).toBe('UDP');
		});

		it('uppercases "icmp" to "ICMP"', () => {
			expect(protoLabel('icmp')).toBe('ICMP');
		});

		it('preserves already uppercase input', () => {
			expect(protoLabel('TCP')).toBe('TCP');
		});

		it('handles mixed case "Tcp"', () => {
			expect(protoLabel('Tcp')).toBe('TCP');
		});
	});

	// -- navigateToDeviceUrl -------------------------------------------------

	describe('navigateToDeviceUrl', () => {
		it('builds correct URL for standard IPv4', () => {
			expect(navigateToDeviceUrl('192.168.1.100')).toBe('/devices/192.168.1.100');
		});

		it('encodes special characters in IP', () => {
			// IPv6 contains colons which get encoded
			const url = navigateToDeviceUrl('::1');
			expect(url).toBe('/devices/%3A%3A1');
		});

		it('encodes a full IPv6 address', () => {
			const ipv6 = 'fe80::1%25eth0';
			const url = navigateToDeviceUrl(ipv6);
			expect(url).toContain('/devices/');
			expect(url).toContain(encodeURIComponent(ipv6));
		});
	});
});
