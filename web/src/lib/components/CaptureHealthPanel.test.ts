import { describe, it, expect } from 'vitest';

/**
 * Tests for CaptureHealthPanel component logic.
 *
 * Extracts and tests the pure formatting/mapping functions from the component.
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from CaptureHealthPanel.svelte
// ---------------------------------------------------------------------------

function statusBadgeClass(status: string): string {
	switch (status) {
		case 'normal': return 'badge badge-success';
		case 'degraded': return 'badge badge-warning';
		case 'down': return 'badge badge-danger';
		case 'not_configured': return 'badge badge-muted';
		default: return 'badge';
	}
}

function statusLabel(status: string): string {
	switch (status) {
		case 'normal': return 'Normal';
		case 'degraded': return 'Degraded';
		case 'down': return 'Down';
		case 'not_configured': return 'Not Configured';
		default: return 'Unknown';
	}
}

function modeBadgeClass(mode: string): string {
	return mode === 'mirror' ? 'badge badge-info' : 'badge badge-accent';
}

function modeLabel(mode: string): string {
	return mode === 'mirror' ? 'Mirror / SPAN' : 'Inline Bridge';
}

function formatBytes(bytes: number): string {
	if (bytes === 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	const value = bytes / Math.pow(1024, i);
	return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
}

function formatNumber(n: number): string {
	return n.toLocaleString();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CaptureHealthPanel logic', () => {
	describe('statusBadgeClass', () => {
		it('returns success for normal', () => {
			expect(statusBadgeClass('normal')).toBe('badge badge-success');
		});

		it('returns warning for degraded', () => {
			expect(statusBadgeClass('degraded')).toBe('badge badge-warning');
		});

		it('returns danger for down', () => {
			expect(statusBadgeClass('down')).toBe('badge badge-danger');
		});

		it('returns muted for not_configured', () => {
			expect(statusBadgeClass('not_configured')).toBe('badge badge-muted');
		});

		it('returns plain badge for unknown status', () => {
			expect(statusBadgeClass('something')).toBe('badge');
		});
	});

	describe('statusLabel', () => {
		it('returns Normal for normal', () => {
			expect(statusLabel('normal')).toBe('Normal');
		});

		it('returns Degraded for degraded', () => {
			expect(statusLabel('degraded')).toBe('Degraded');
		});

		it('returns Down for down', () => {
			expect(statusLabel('down')).toBe('Down');
		});

		it('returns Not Configured for not_configured', () => {
			expect(statusLabel('not_configured')).toBe('Not Configured');
		});

		it('returns Unknown for unrecognized status', () => {
			expect(statusLabel('xyz')).toBe('Unknown');
		});
	});

	describe('modeBadgeClass', () => {
		it('returns info for mirror', () => {
			expect(modeBadgeClass('mirror')).toBe('badge badge-info');
		});

		it('returns accent for bridge', () => {
			expect(modeBadgeClass('bridge')).toBe('badge badge-accent');
		});

		it('returns accent for any non-mirror mode', () => {
			expect(modeBadgeClass('unknown')).toBe('badge badge-accent');
		});
	});

	describe('modeLabel', () => {
		it('returns Mirror / SPAN for mirror', () => {
			expect(modeLabel('mirror')).toBe('Mirror / SPAN');
		});

		it('returns Inline Bridge for bridge', () => {
			expect(modeLabel('bridge')).toBe('Inline Bridge');
		});
	});

	describe('formatBytes', () => {
		it('returns 0 B for zero', () => {
			expect(formatBytes(0)).toBe('0 B');
		});

		it('formats bytes', () => {
			expect(formatBytes(500)).toBe('500 B');
		});

		it('formats KB', () => {
			expect(formatBytes(1024)).toBe('1.0 KB');
		});

		it('formats MB', () => {
			expect(formatBytes(1048576)).toBe('1.0 MB');
		});

		it('formats GB', () => {
			expect(formatBytes(1073741824)).toBe('1.0 GB');
		});

		it('formats large values without decimal', () => {
			expect(formatBytes(107374182400)).toBe('100 GB');
		});
	});

	describe('formatNumber', () => {
		it('formats numbers with locale separators', () => {
			const result = formatNumber(1234567);
			// toLocaleString output varies by locale, just check it returns a string
			expect(typeof result).toBe('string');
			expect(result.length).toBeGreaterThan(0);
		});
	});
});
