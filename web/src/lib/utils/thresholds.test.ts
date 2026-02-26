import { describe, it, expect } from 'vitest';
import {
	thresholdColor,
	thresholdBadgeClass,
	resolveLevel,
	ALERT_SEVERITY_THRESHOLDS,
	DISK_USAGE_THRESHOLDS,
	CPU_USAGE_THRESHOLDS,
	RISK_SCORE_THRESHOLDS,
	DEVICE_ALERT_THRESHOLDS,
} from './thresholds';
import type { Threshold, ThresholdLevel } from './thresholds';

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('threshold utilities', () => {
	// -- resolveLevel --------------------------------------------------------

	describe('resolveLevel', () => {
		it('returns the correct level when value matches the highest threshold', () => {
			const thresholds: Threshold[] = [
				{ value: 0, level: 'success' },
				{ value: 50, level: 'warning' },
				{ value: 80, level: 'danger' },
			];

			expect(resolveLevel(95, thresholds)).toBe('danger');
		});

		it('returns the correct level when value is exactly on a threshold boundary', () => {
			const thresholds: Threshold[] = [
				{ value: 0, level: 'success' },
				{ value: 50, level: 'warning' },
				{ value: 80, level: 'danger' },
			];

			expect(resolveLevel(80, thresholds)).toBe('danger');
			expect(resolveLevel(50, thresholds)).toBe('warning');
			expect(resolveLevel(0, thresholds)).toBe('success');
		});

		it('returns muted when value is below all thresholds', () => {
			const thresholds: Threshold[] = [
				{ value: 10, level: 'success' },
				{ value: 50, level: 'warning' },
			];

			expect(resolveLevel(5, thresholds)).toBe('muted');
		});

		it('returns muted for an empty thresholds array', () => {
			expect(resolveLevel(50, [])).toBe('muted');
		});

		it('sorts thresholds descending regardless of input order', () => {
			// Provide thresholds in ascending order -- resolveLevel should sort internally
			const thresholds: Threshold[] = [
				{ value: 0, level: 'success' },
				{ value: 80, level: 'danger' },
				{ value: 50, level: 'warning' },
			];

			expect(resolveLevel(60, thresholds)).toBe('warning');
			expect(resolveLevel(85, thresholds)).toBe('danger');
			expect(resolveLevel(10, thresholds)).toBe('success');
		});

		it('returns the first matching level when value equals lowest threshold', () => {
			const thresholds: Threshold[] = [
				{ value: 0, level: 'success' },
				{ value: 25, level: 'accent' },
			];

			expect(resolveLevel(0, thresholds)).toBe('success');
		});

		it('handles negative values correctly', () => {
			const thresholds: Threshold[] = [
				{ value: 0, level: 'success' },
				{ value: 50, level: 'warning' },
			];

			expect(resolveLevel(-10, thresholds)).toBe('muted');
		});
	});

	// -- thresholdColor ------------------------------------------------------

	describe('thresholdColor', () => {
		it('returns var(--success) for success level', () => {
			const thresholds: Threshold[] = [{ value: 0, level: 'success' }];
			expect(thresholdColor(10, thresholds)).toBe('var(--success)');
		});

		it('returns var(--warning) for warning level', () => {
			const thresholds: Threshold[] = [{ value: 0, level: 'warning' }];
			expect(thresholdColor(10, thresholds)).toBe('var(--warning)');
		});

		it('returns var(--danger) for danger level', () => {
			const thresholds: Threshold[] = [{ value: 0, level: 'danger' }];
			expect(thresholdColor(10, thresholds)).toBe('var(--danger)');
		});

		it('returns var(--accent) for accent level', () => {
			const thresholds: Threshold[] = [{ value: 0, level: 'accent' }];
			expect(thresholdColor(10, thresholds)).toBe('var(--accent)');
		});

		it('returns var(--text-muted) for muted level (below all thresholds)', () => {
			const thresholds: Threshold[] = [{ value: 50, level: 'warning' }];
			expect(thresholdColor(10, thresholds)).toBe('var(--text-muted)');
		});

		it('returns correct CSS variable for DISK_USAGE at 85%', () => {
			expect(thresholdColor(85, DISK_USAGE_THRESHOLDS)).toBe('var(--danger)');
		});

		it('returns correct CSS variable for DISK_USAGE at 70%', () => {
			expect(thresholdColor(70, DISK_USAGE_THRESHOLDS)).toBe('var(--warning)');
		});

		it('returns correct CSS variable for DISK_USAGE at 30%', () => {
			expect(thresholdColor(30, DISK_USAGE_THRESHOLDS)).toBe('var(--success)');
		});
	});

	// -- thresholdBadgeClass -------------------------------------------------

	describe('thresholdBadgeClass', () => {
		it('returns "badge badge-success" for success level', () => {
			const thresholds: Threshold[] = [{ value: 0, level: 'success' }];
			expect(thresholdBadgeClass(10, thresholds)).toBe('badge badge-success');
		});

		it('returns "badge badge-warning" for warning level', () => {
			const thresholds: Threshold[] = [{ value: 0, level: 'warning' }];
			expect(thresholdBadgeClass(10, thresholds)).toBe('badge badge-warning');
		});

		it('returns "badge badge-danger" for danger level', () => {
			const thresholds: Threshold[] = [{ value: 0, level: 'danger' }];
			expect(thresholdBadgeClass(10, thresholds)).toBe('badge badge-danger');
		});

		it('returns "badge badge-accent" for accent level', () => {
			const thresholds: Threshold[] = [{ value: 0, level: 'accent' }];
			expect(thresholdBadgeClass(10, thresholds)).toBe('badge badge-accent');
		});

		it('returns "badge" for muted level', () => {
			const thresholds: Threshold[] = [{ value: 50, level: 'warning' }];
			expect(thresholdBadgeClass(10, thresholds)).toBe('badge');
		});

		it('returns correct badge for ALERT_SEVERITY severity 1 (high)', () => {
			expect(thresholdBadgeClass(1, ALERT_SEVERITY_THRESHOLDS)).toBe('badge badge-danger');
		});

		it('returns correct badge for ALERT_SEVERITY severity 2 (medium)', () => {
			expect(thresholdBadgeClass(2, ALERT_SEVERITY_THRESHOLDS)).toBe('badge badge-warning');
		});

		it('returns correct badge for ALERT_SEVERITY severity 3 (low)', () => {
			expect(thresholdBadgeClass(3, ALERT_SEVERITY_THRESHOLDS)).toBe('badge badge-accent');
		});
	});

	// -- Preset Threshold Configs -------------------------------------------

	describe('ALERT_SEVERITY_THRESHOLDS', () => {
		it('maps severity 1 to danger', () => {
			expect(resolveLevel(1, ALERT_SEVERITY_THRESHOLDS)).toBe('danger');
		});

		it('maps severity 2 to warning', () => {
			expect(resolveLevel(2, ALERT_SEVERITY_THRESHOLDS)).toBe('warning');
		});

		it('maps severity 3 to accent', () => {
			expect(resolveLevel(3, ALERT_SEVERITY_THRESHOLDS)).toBe('accent');
		});

		it('maps severity 0 to muted (below all thresholds)', () => {
			expect(resolveLevel(0, ALERT_SEVERITY_THRESHOLDS)).toBe('muted');
		});
	});

	describe('DISK_USAGE_THRESHOLDS', () => {
		it('maps 0% to success', () => {
			expect(resolveLevel(0, DISK_USAGE_THRESHOLDS)).toBe('success');
		});

		it('maps 59% to success', () => {
			expect(resolveLevel(59, DISK_USAGE_THRESHOLDS)).toBe('success');
		});

		it('maps 60% to warning (boundary)', () => {
			expect(resolveLevel(60, DISK_USAGE_THRESHOLDS)).toBe('warning');
		});

		it('maps 79% to warning', () => {
			expect(resolveLevel(79, DISK_USAGE_THRESHOLDS)).toBe('warning');
		});

		it('maps 80% to danger (boundary)', () => {
			expect(resolveLevel(80, DISK_USAGE_THRESHOLDS)).toBe('danger');
		});

		it('maps 100% to danger', () => {
			expect(resolveLevel(100, DISK_USAGE_THRESHOLDS)).toBe('danger');
		});
	});

	describe('CPU_USAGE_THRESHOLDS', () => {
		it('maps 0% to success', () => {
			expect(resolveLevel(0, CPU_USAGE_THRESHOLDS)).toBe('success');
		});

		it('maps 49% to success', () => {
			expect(resolveLevel(49, CPU_USAGE_THRESHOLDS)).toBe('success');
		});

		it('maps 50% to warning (boundary)', () => {
			expect(resolveLevel(50, CPU_USAGE_THRESHOLDS)).toBe('warning');
		});

		it('maps 80% to danger (boundary)', () => {
			expect(resolveLevel(80, CPU_USAGE_THRESHOLDS)).toBe('danger');
		});
	});

	describe('RISK_SCORE_THRESHOLDS', () => {
		it('maps 0 to success', () => {
			expect(resolveLevel(0, RISK_SCORE_THRESHOLDS)).toBe('success');
		});

		it('maps 24 to success', () => {
			expect(resolveLevel(24, RISK_SCORE_THRESHOLDS)).toBe('success');
		});

		it('maps 25 to accent (boundary)', () => {
			expect(resolveLevel(25, RISK_SCORE_THRESHOLDS)).toBe('accent');
		});

		it('maps 50 to warning (boundary)', () => {
			expect(resolveLevel(50, RISK_SCORE_THRESHOLDS)).toBe('warning');
		});

		it('maps 75 to danger (boundary)', () => {
			expect(resolveLevel(75, RISK_SCORE_THRESHOLDS)).toBe('danger');
		});

		it('maps 100 to danger', () => {
			expect(resolveLevel(100, RISK_SCORE_THRESHOLDS)).toBe('danger');
		});
	});

	describe('DEVICE_ALERT_THRESHOLDS', () => {
		it('maps 0 to success', () => {
			expect(resolveLevel(0, DEVICE_ALERT_THRESHOLDS)).toBe('success');
		});

		it('maps 1 to warning (boundary)', () => {
			expect(resolveLevel(1, DEVICE_ALERT_THRESHOLDS)).toBe('warning');
		});

		it('maps 4 to warning', () => {
			expect(resolveLevel(4, DEVICE_ALERT_THRESHOLDS)).toBe('warning');
		});

		it('maps 5 to danger (boundary)', () => {
			expect(resolveLevel(5, DEVICE_ALERT_THRESHOLDS)).toBe('danger');
		});

		it('maps 20 to danger', () => {
			expect(resolveLevel(20, DEVICE_ALERT_THRESHOLDS)).toBe('danger');
		});
	});
});
