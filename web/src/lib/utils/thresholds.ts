/**
 * Threshold color utilities for applying color thresholds to numeric values.
 *
 * Used across the dashboard to consistently color-code metrics such as
 * alert severity, disk usage, CPU load, risk scores, and device alert counts.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ThresholdLevel = 'success' | 'warning' | 'danger' | 'accent' | 'muted';

export interface Threshold {
	value: number;
	level: ThresholdLevel;
}

// ---------------------------------------------------------------------------
// Core Functions
// ---------------------------------------------------------------------------

/**
 * Returns the CSS variable name for a threshold level based on where the
 * provided numeric value falls within the sorted threshold list.
 *
 * Thresholds are evaluated in descending order: the first threshold whose
 * `value` is less than or equal to the input `value` wins.
 *
 * @example
 *   thresholdColor(85, DISK_USAGE_THRESHOLDS)
 *   // => 'var(--danger)'
 */
export function thresholdColor(value: number, thresholds: Threshold[]): string {
	const level = resolveLevel(value, thresholds);
	return levelToCssVar(level);
}

/**
 * Returns the badge CSS class for a threshold level.
 *
 * @example
 *   thresholdBadgeClass(2, ALERT_SEVERITY_THRESHOLDS)
 *   // => 'badge badge-warning'
 */
export function thresholdBadgeClass(value: number, thresholds: Threshold[]): string {
	const level = resolveLevel(value, thresholds);
	return levelToBadgeClass(level);
}

/**
 * Resolve the ThresholdLevel for a given numeric value.
 * Exported for advanced use cases where callers need the raw level.
 */
export function resolveLevel(value: number, thresholds: Threshold[]): ThresholdLevel {
	// Sort descending so we match the highest applicable threshold first.
	const sorted = [...thresholds].sort((a, b) => b.value - a.value);

	for (const t of sorted) {
		if (value >= t.value) {
			return t.level;
		}
	}

	// If the value is below all thresholds, fall back to 'muted'.
	return 'muted';
}

// ---------------------------------------------------------------------------
// Mapping helpers
// ---------------------------------------------------------------------------

function levelToCssVar(level: ThresholdLevel): string {
	switch (level) {
		case 'success':
			return 'var(--success)';
		case 'warning':
			return 'var(--warning)';
		case 'danger':
			return 'var(--danger)';
		case 'accent':
			return 'var(--accent)';
		case 'muted':
			return 'var(--text-muted)';
	}
}

function levelToBadgeClass(level: ThresholdLevel): string {
	switch (level) {
		case 'success':
			return 'badge badge-success';
		case 'warning':
			return 'badge badge-warning';
		case 'danger':
			return 'badge badge-danger';
		case 'accent':
			return 'badge badge-accent';
		case 'muted':
			return 'badge';
	}
}

// ---------------------------------------------------------------------------
// Preset Threshold Configs
// ---------------------------------------------------------------------------

/**
 * Alert severity thresholds.
 * Suricata severity values: 1=high, 2=medium, 3=low.
 * Lower number = more severe.
 */
export const ALERT_SEVERITY_THRESHOLDS: Threshold[] = [
	{ value: 3, level: 'accent' },   // low severity (3)
	{ value: 2, level: 'warning' },  // medium severity (2)
	{ value: 1, level: 'danger' },   // high severity (1)
];

/**
 * Disk usage thresholds (percentage 0-100).
 *  0-59  => success (healthy)
 * 60-79  => warning (attention needed)
 * 80-100 => danger  (critical, matches daemon 80% safeguard)
 */
export const DISK_USAGE_THRESHOLDS: Threshold[] = [
	{ value: 0, level: 'success' },
	{ value: 60, level: 'warning' },
	{ value: 80, level: 'danger' },
];

/**
 * CPU usage thresholds (percentage 0-100).
 *  0-49  => success
 * 50-79  => warning
 * 80-100 => danger
 */
export const CPU_USAGE_THRESHOLDS: Threshold[] = [
	{ value: 0, level: 'success' },
	{ value: 50, level: 'warning' },
	{ value: 80, level: 'danger' },
];

/**
 * Risk score thresholds (0-100 scale).
 *   0-24 => success (low risk)
 *  25-49 => accent  (moderate)
 *  50-74 => warning (elevated)
 *  75+   => danger  (high risk)
 */
export const RISK_SCORE_THRESHOLDS: Threshold[] = [
	{ value: 0, level: 'success' },
	{ value: 25, level: 'accent' },
	{ value: 50, level: 'warning' },
	{ value: 75, level: 'danger' },
];

/**
 * Device alert count thresholds.
 *   0     => success (clean)
 *   1-4   => warning (some alerts)
 *   5+    => danger  (many alerts)
 */
export const DEVICE_ALERT_THRESHOLDS: Threshold[] = [
	{ value: 0, level: 'success' },
	{ value: 1, level: 'warning' },
	{ value: 5, level: 'danger' },
];
