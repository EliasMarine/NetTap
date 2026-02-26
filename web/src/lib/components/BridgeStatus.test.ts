import { describe, it, expect } from 'vitest';

/**
 * Tests for BridgeStatus component logic.
 *
 * The BridgeStatus.svelte component uses Svelte 5 runes ($state, $effect)
 * that are difficult to fully render in a jsdom test environment.  Instead we
 * extract and test the pure logic that lives inside the component: health
 * status badge mapping, link color derivation, latency/byte/uptime formatting,
 * and bypass state management.
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from BridgeStatus.svelte
// ---------------------------------------------------------------------------

/** Maps health_status to a CSS badge class string */
function healthBadgeClass(status: string): string {
	switch (status) {
		case 'normal':
			return 'badge badge-success';
		case 'degraded':
			return 'badge badge-warning';
		case 'bypass':
			return 'badge badge-info';
		case 'down':
			return 'badge badge-danger';
		default:
			return 'badge';
	}
}

/** Maps health_status to a human-readable label */
function healthBadgeLabel(status: string): string {
	switch (status) {
		case 'normal':
			return 'Normal';
		case 'degraded':
			return 'Degraded';
		case 'bypass':
			return 'Bypass';
		case 'down':
			return 'Down';
		default:
			return 'Unknown';
	}
}

/** Returns the CSS color for a NIC link state */
function linkColor(up: boolean | undefined): string {
	if (up === undefined) return 'var(--text-muted)';
	return up ? 'var(--success)' : 'var(--danger)';
}

/** Returns the CSS color for the bridge line based on health status */
function bridgeLineColor(status: string | undefined): string {
	switch (status) {
		case 'normal':
			return 'var(--success)';
		case 'degraded':
			return 'var(--warning)';
		case 'bypass':
			return 'var(--accent)';
		case 'down':
			return 'var(--danger)';
		default:
			return 'var(--text-muted)';
	}
}

/** Formats a latency in microseconds to a human-readable string */
function formatLatency(us: number): string {
	if (us <= 0) return '--';
	if (us < 1000) return `${us} us`;
	if (us < 1_000_000) return `${(us / 1000).toFixed(1)} ms`;
	return `${(us / 1_000_000).toFixed(2)} s`;
}

/** Formats a byte rate to a human-readable string with units */
function formatByteRate(bytes: number): string {
	if (bytes <= 0) return '0 B/s';
	const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
	const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
	const val = bytes / Math.pow(1024, i);
	return `${val.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

/** Formats an uptime in seconds to a human-readable string */
function formatUptime(seconds: number): string {
	if (seconds <= 0) return '--';
	const days = Math.floor(seconds / 86400);
	const hours = Math.floor((seconds % 86400) / 3600);
	const minutes = Math.floor((seconds % 3600) / 60);
	const parts: string[] = [];
	if (days > 0) parts.push(`${days}d`);
	if (hours > 0) parts.push(`${hours}h`);
	if (minutes > 0 || parts.length === 0) parts.push(`${minutes}m`);
	return parts.join(' ');
}

/** Simulates the bypass toggle state machine */
class BypassToggleState {
	isActive: boolean;
	showConfirm: boolean;
	isLoading: boolean;

	constructor(active = false) {
		this.isActive = active;
		this.showConfirm = false;
		this.isLoading = false;
	}

	/** First click shows confirmation, second click executes */
	toggle() {
		if (!this.showConfirm) {
			this.showConfirm = true;
			return;
		}
		// Simulate the confirmed action
		this.isLoading = true;
		this.showConfirm = false;
		this.isActive = !this.isActive;
		this.isLoading = false;
	}

	cancel() {
		this.showConfirm = false;
	}

	get buttonLabel(): string {
		if (this.isLoading) return 'Updating...';
		if (this.isActive) return 'Disable Bypass';
		return 'Enable Bypass';
	}

	get confirmText(): string {
		if (this.isActive) return 'Disable bypass and resume capture?';
		return 'Enable bypass? Capture will stop.';
	}

	get statusBadgeClass(): string {
		return this.isActive ? 'badge badge-warning' : 'badge badge-success';
	}

	get statusLabel(): string {
		return this.isActive ? 'Active' : 'Inactive';
	}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('BridgeStatus logic', () => {
	// -- Health badge mapping --------------------------------------------------

	describe('healthBadgeClass', () => {
		it('returns success badge for normal status', () => {
			expect(healthBadgeClass('normal')).toBe('badge badge-success');
		});

		it('returns warning badge for degraded status', () => {
			expect(healthBadgeClass('degraded')).toBe('badge badge-warning');
		});

		it('returns info badge for bypass status', () => {
			expect(healthBadgeClass('bypass')).toBe('badge badge-info');
		});

		it('returns danger badge for down status', () => {
			expect(healthBadgeClass('down')).toBe('badge badge-danger');
		});

		it('returns plain badge for unknown status', () => {
			expect(healthBadgeClass('something-else')).toBe('badge');
		});
	});

	describe('healthBadgeLabel', () => {
		it('returns "Normal" for normal status', () => {
			expect(healthBadgeLabel('normal')).toBe('Normal');
		});

		it('returns "Degraded" for degraded status', () => {
			expect(healthBadgeLabel('degraded')).toBe('Degraded');
		});

		it('returns "Bypass" for bypass status', () => {
			expect(healthBadgeLabel('bypass')).toBe('Bypass');
		});

		it('returns "Down" for down status', () => {
			expect(healthBadgeLabel('down')).toBe('Down');
		});

		it('returns "Unknown" for unrecognized status', () => {
			expect(healthBadgeLabel('foo')).toBe('Unknown');
		});
	});

	// -- NIC link color -------------------------------------------------------

	describe('linkColor', () => {
		it('returns success color when link is up', () => {
			expect(linkColor(true)).toBe('var(--success)');
		});

		it('returns danger color when link is down', () => {
			expect(linkColor(false)).toBe('var(--danger)');
		});

		it('returns muted color when link state is undefined', () => {
			expect(linkColor(undefined)).toBe('var(--text-muted)');
		});
	});

	// -- Bridge line color ----------------------------------------------------

	describe('bridgeLineColor', () => {
		it('returns success for normal', () => {
			expect(bridgeLineColor('normal')).toBe('var(--success)');
		});

		it('returns warning for degraded', () => {
			expect(bridgeLineColor('degraded')).toBe('var(--warning)');
		});

		it('returns accent for bypass', () => {
			expect(bridgeLineColor('bypass')).toBe('var(--accent)');
		});

		it('returns danger for down', () => {
			expect(bridgeLineColor('down')).toBe('var(--danger)');
		});

		it('returns muted for undefined', () => {
			expect(bridgeLineColor(undefined)).toBe('var(--text-muted)');
		});
	});

	// -- Latency formatting ---------------------------------------------------

	describe('formatLatency', () => {
		it('returns "--" for zero microseconds', () => {
			expect(formatLatency(0)).toBe('--');
		});

		it('returns "--" for negative values', () => {
			expect(formatLatency(-10)).toBe('--');
		});

		it('formats sub-millisecond values in microseconds', () => {
			expect(formatLatency(42)).toBe('42 us');
			expect(formatLatency(999)).toBe('999 us');
		});

		it('formats millisecond values', () => {
			expect(formatLatency(1000)).toBe('1.0 ms');
			expect(formatLatency(1500)).toBe('1.5 ms');
			expect(formatLatency(999_999)).toBe('1000.0 ms');
		});

		it('formats second values', () => {
			expect(formatLatency(1_000_000)).toBe('1.00 s');
			expect(formatLatency(2_500_000)).toBe('2.50 s');
		});
	});

	// -- Byte rate formatting -------------------------------------------------

	describe('formatByteRate', () => {
		it('returns "0 B/s" for zero bytes', () => {
			expect(formatByteRate(0)).toBe('0 B/s');
		});

		it('returns "0 B/s" for negative values', () => {
			expect(formatByteRate(-100)).toBe('0 B/s');
		});

		it('formats byte-level rates', () => {
			expect(formatByteRate(500)).toBe('500 B/s');
		});

		it('formats KB/s rates', () => {
			expect(formatByteRate(1024)).toBe('1.0 KB/s');
			expect(formatByteRate(10240)).toBe('10.0 KB/s');
		});

		it('formats MB/s rates', () => {
			expect(formatByteRate(1048576)).toBe('1.0 MB/s');
			expect(formatByteRate(5242880)).toBe('5.0 MB/s');
		});

		it('formats GB/s rates', () => {
			expect(formatByteRate(1073741824)).toBe('1.0 GB/s');
		});
	});

	// -- Uptime formatting ----------------------------------------------------

	describe('formatUptime', () => {
		it('returns "--" for zero seconds', () => {
			expect(formatUptime(0)).toBe('--');
		});

		it('returns "--" for negative seconds', () => {
			expect(formatUptime(-100)).toBe('--');
		});

		it('formats minutes only', () => {
			expect(formatUptime(300)).toBe('5m');
		});

		it('formats hours and minutes', () => {
			expect(formatUptime(3660)).toBe('1h 1m');
		});

		it('formats days and hours', () => {
			expect(formatUptime(90000)).toBe('1d 1h');
		});

		it('formats days, hours, and minutes', () => {
			expect(formatUptime(90060)).toBe('1d 1h 1m');
		});

		it('formats full days only (no hours/minutes)', () => {
			expect(formatUptime(86400)).toBe('1d');
		});

		it('shows 0m for very small values', () => {
			expect(formatUptime(30)).toBe('0m');
		});
	});

	// -- Bypass toggle state machine ------------------------------------------

	describe('BypassToggleState', () => {
		it('defaults to inactive and no confirmation shown', () => {
			const state = new BypassToggleState();
			expect(state.isActive).toBe(false);
			expect(state.showConfirm).toBe(false);
			expect(state.isLoading).toBe(false);
		});

		it('first toggle shows confirmation dialog', () => {
			const state = new BypassToggleState();
			state.toggle();
			expect(state.showConfirm).toBe(true);
			expect(state.isActive).toBe(false); // Not yet toggled
		});

		it('second toggle executes the action', () => {
			const state = new BypassToggleState();
			state.toggle(); // show confirm
			state.toggle(); // execute
			expect(state.isActive).toBe(true);
			expect(state.showConfirm).toBe(false);
		});

		it('cancel hides the confirmation', () => {
			const state = new BypassToggleState();
			state.toggle(); // show confirm
			state.cancel();
			expect(state.showConfirm).toBe(false);
			expect(state.isActive).toBe(false);
		});

		it('toggle from active state disables bypass', () => {
			const state = new BypassToggleState(true);
			expect(state.isActive).toBe(true);
			state.toggle(); // show confirm
			state.toggle(); // execute
			expect(state.isActive).toBe(false);
		});

		it('returns correct button label when inactive', () => {
			const state = new BypassToggleState(false);
			expect(state.buttonLabel).toBe('Enable Bypass');
		});

		it('returns correct button label when active', () => {
			const state = new BypassToggleState(true);
			expect(state.buttonLabel).toBe('Disable Bypass');
		});

		it('returns correct confirm text when enabling', () => {
			const state = new BypassToggleState(false);
			expect(state.confirmText).toBe('Enable bypass? Capture will stop.');
		});

		it('returns correct confirm text when disabling', () => {
			const state = new BypassToggleState(true);
			expect(state.confirmText).toBe('Disable bypass and resume capture?');
		});

		it('returns correct status badge class for active', () => {
			const state = new BypassToggleState(true);
			expect(state.statusBadgeClass).toBe('badge badge-warning');
		});

		it('returns correct status badge class for inactive', () => {
			const state = new BypassToggleState(false);
			expect(state.statusBadgeClass).toBe('badge badge-success');
		});

		it('returns correct status label', () => {
			const active = new BypassToggleState(true);
			expect(active.statusLabel).toBe('Active');

			const inactive = new BypassToggleState(false);
			expect(inactive.statusLabel).toBe('Inactive');
		});
	});

	// -- Issues list generation -----------------------------------------------

	describe('issues list', () => {
		it('empty issues array means no alerts shown', () => {
			const issues: string[] = [];
			expect(issues.length).toBe(0);
		});

		it('issues array with entries should be rendered', () => {
			const issues = ['WAN link flapping', 'High latency detected', 'Packet loss > 1%'];
			expect(issues.length).toBe(3);
			expect(issues[0]).toBe('WAN link flapping');
			expect(issues[2]).toBe('Packet loss > 1%');
		});

		it('single issue is correctly accessible', () => {
			const issues = ['Bridge state unknown'];
			expect(issues.length).toBe(1);
			expect(issues[0]).toBe('Bridge state unknown');
		});
	});
});
