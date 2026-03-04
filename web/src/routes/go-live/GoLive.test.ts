import { describe, it, expect } from 'vitest';

/**
 * Tests for Go Live page logic.
 *
 * The GoLive page uses Svelte 5 runes ($state, $effect, $derived) that are
 * difficult to fully render in a jsdom test environment. Instead we extract
 * and test the pure logic: phase determination, formatting helpers, and
 * status badge mapping.
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from go-live/+page.svelte
// ---------------------------------------------------------------------------

interface ReadinessCheck {
	name: string;
	passed: boolean;
	detail: string;
}

interface Readiness {
	ready: boolean;
	checks: ReadinessCheck[];
	message: string;
}

/** Determines the current Go Live phase from readiness data */
function determinePhase(r: Readiness): 1 | 2 | 3 {
	const bridge = r.checks?.some((c) => c.name === 'bridge_exists' && c.passed);
	const wan = r.checks?.some((c) => c.name === 'wan_carrier' && c.passed);
	const lan = r.checks?.some((c) => c.name === 'lan_carrier' && c.passed);

	if (!bridge) return 1;
	if (!wan || !lan) return 2;
	return 3;
}

/** Formats uptime in seconds to a human-readable string */
function formatUptime(seconds: number): string {
	if (seconds < 60) return `${seconds}s`;
	if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
	const h = Math.floor(seconds / 3600);
	const m = Math.floor((seconds % 3600) / 60);
	return `${h}h ${m}m`;
}

/** Formats a packet count to a human-readable abbreviated string */
function formatPackets(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	return String(n);
}

/** Maps a health_status string to a CSS badge class */
function statusBadgeClass(status: string): string {
	switch (status) {
		case 'normal':
			return 'badge-success';
		case 'degraded':
			return 'badge-warning';
		case 'bypass':
			return 'badge-warning';
		case 'down':
		case 'not_configured':
			return 'badge-danger';
		default:
			return 'badge-muted';
	}
}

// ---------------------------------------------------------------------------
// Helper: make a readiness object with specified checks
// ---------------------------------------------------------------------------

function makeReadiness(
	checks: Array<{ name: string; passed: boolean }>,
	ready = false,
): Readiness {
	return {
		ready,
		checks: checks.map((c) => ({ ...c, detail: '' })),
		message: '',
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('GoLive page logic', () => {
	// -- Phase determination ---------------------------------------------------

	describe('determinePhase', () => {
		it('returns phase 1 when bridge does not exist', () => {
			const r = makeReadiness([
				{ name: 'bridge_exists', passed: false },
				{ name: 'wan_carrier', passed: false },
				{ name: 'lan_carrier', passed: false },
			]);
			expect(determinePhase(r)).toBe(1);
		});

		it('returns phase 1 when checks array is empty', () => {
			const r = makeReadiness([]);
			expect(determinePhase(r)).toBe(1);
		});

		it('returns phase 2 when bridge exists but no carriers', () => {
			const r = makeReadiness([
				{ name: 'bridge_exists', passed: true },
				{ name: 'wan_carrier', passed: false },
				{ name: 'lan_carrier', passed: false },
			]);
			expect(determinePhase(r)).toBe(2);
		});

		it('returns phase 2 when bridge exists and only WAN has carrier', () => {
			const r = makeReadiness([
				{ name: 'bridge_exists', passed: true },
				{ name: 'wan_carrier', passed: true },
				{ name: 'lan_carrier', passed: false },
			]);
			expect(determinePhase(r)).toBe(2);
		});

		it('returns phase 2 when bridge exists and only LAN has carrier', () => {
			const r = makeReadiness([
				{ name: 'bridge_exists', passed: true },
				{ name: 'wan_carrier', passed: false },
				{ name: 'lan_carrier', passed: true },
			]);
			expect(determinePhase(r)).toBe(2);
		});

		it('returns phase 3 when bridge exists and both carriers detected', () => {
			const r = makeReadiness([
				{ name: 'bridge_exists', passed: true },
				{ name: 'wan_carrier', passed: true },
				{ name: 'lan_carrier', passed: true },
			]);
			expect(determinePhase(r)).toBe(3);
		});

		it('returns phase 3 even with extra checks present', () => {
			const r = makeReadiness([
				{ name: 'bridge_exists', passed: true },
				{ name: 'wan_carrier', passed: true },
				{ name: 'lan_carrier', passed: true },
				{ name: 'promisc_mode', passed: true },
				{ name: 'netfilter_disabled', passed: false },
			]);
			expect(determinePhase(r)).toBe(3);
		});
	});

	// -- Uptime formatting ----------------------------------------------------

	describe('formatUptime', () => {
		it('formats seconds under a minute', () => {
			expect(formatUptime(0)).toBe('0s');
			expect(formatUptime(45)).toBe('45s');
			expect(formatUptime(59)).toBe('59s');
		});

		it('formats minutes and seconds', () => {
			expect(formatUptime(60)).toBe('1m 0s');
			expect(formatUptime(125)).toBe('2m 5s');
			expect(formatUptime(3599)).toBe('59m 59s');
		});

		it('formats hours and minutes', () => {
			expect(formatUptime(3600)).toBe('1h 0m');
			expect(formatUptime(7260)).toBe('2h 1m');
			expect(formatUptime(86400)).toBe('24h 0m');
		});
	});

	// -- Packet formatting ----------------------------------------------------

	describe('formatPackets', () => {
		it('returns raw number for values under 1000', () => {
			expect(formatPackets(0)).toBe('0');
			expect(formatPackets(42)).toBe('42');
			expect(formatPackets(999)).toBe('999');
		});

		it('formats thousands with K suffix', () => {
			expect(formatPackets(1000)).toBe('1.0K');
			expect(formatPackets(1500)).toBe('1.5K');
			expect(formatPackets(999_999)).toBe('1000.0K');
		});

		it('formats millions with M suffix', () => {
			expect(formatPackets(1_000_000)).toBe('1.0M');
			expect(formatPackets(2_500_000)).toBe('2.5M');
		});
	});

	// -- Status badge class ---------------------------------------------------

	describe('statusBadgeClass', () => {
		it('returns badge-success for normal', () => {
			expect(statusBadgeClass('normal')).toBe('badge-success');
		});

		it('returns badge-warning for degraded', () => {
			expect(statusBadgeClass('degraded')).toBe('badge-warning');
		});

		it('returns badge-warning for bypass', () => {
			expect(statusBadgeClass('bypass')).toBe('badge-warning');
		});

		it('returns badge-danger for down', () => {
			expect(statusBadgeClass('down')).toBe('badge-danger');
		});

		it('returns badge-danger for not_configured', () => {
			expect(statusBadgeClass('not_configured')).toBe('badge-danger');
		});

		it('returns badge-muted for unknown status', () => {
			expect(statusBadgeClass('something-else')).toBe('badge-muted');
		});
	});

	// -- Readiness check extraction -------------------------------------------

	describe('readiness check extraction', () => {
		it('extracts bridge_exists check correctly', () => {
			const r = makeReadiness([
				{ name: 'bridge_exists', passed: true },
				{ name: 'wan_carrier', passed: false },
			]);
			const bridgeCheck = r.checks.find((c) => c.name === 'bridge_exists');
			expect(bridgeCheck).toBeDefined();
			expect(bridgeCheck?.passed).toBe(true);
		});

		it('returns undefined when check is missing', () => {
			const r = makeReadiness([{ name: 'wan_carrier', passed: true }]);
			const bridgeCheck = r.checks.find((c) => c.name === 'bridge_exists');
			expect(bridgeCheck).toBeUndefined();
		});

		it('handles duplicate check names by finding first', () => {
			const r = makeReadiness([
				{ name: 'wan_carrier', passed: false },
				{ name: 'wan_carrier', passed: true },
			]);
			const wanCheck = r.checks.find((c) => c.name === 'wan_carrier');
			expect(wanCheck?.passed).toBe(false);
		});
	});
});
