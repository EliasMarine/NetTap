import { describe, it, expect } from 'vitest';

/**
 * Tests for UpdateSystem page logic.
 *
 * The updates page uses Svelte 5 runes ($state, $derived, $effect)
 * that are difficult to fully render in a jsdom test environment. Instead we
 * extract and test the pure logic that lives inside the component: version
 * status determination, badge class mapping, category grouping, update type
 * badges, size formatting, time-ago formatting, progress calculation,
 * component sorting, and changelog truncation.
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from system/updates/+page.svelte
// ---------------------------------------------------------------------------

/** Determines the status label for a component based on available updates */
function versionStatusLabel(
	component: string,
	updates: Map<string, { latest_version: string }>
): string {
	if (updates.has(component)) return 'Update Available';
	return 'Up to Date';
}

/** Maps component status + update availability to a CSS badge class */
function versionStatusClass(
	component: string,
	updates: Map<string, { latest_version: string }>,
	status: string
): string {
	if (status === 'error') return 'badge badge-danger';
	if (status === 'unknown') return 'badge badge-muted';
	if (updates.has(component)) return 'badge badge-warning';
	return 'badge badge-success';
}

/** Maps update_type to a CSS badge class (major=red, minor=yellow, patch=green) */
function updateTypeBadgeClass(type: string): string {
	switch (type) {
		case 'major':
			return 'badge badge-danger';
		case 'minor':
			return 'badge badge-warning';
		case 'patch':
			return 'badge badge-success';
		default:
			return 'badge badge-muted';
	}
}

/** Formats a size in MB to a human-readable string (MB or GB) */
function formatSizeMB(mb: number): string {
	if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
	return `${mb.toFixed(1)} MB`;
}

/** Returns a human-readable "time ago" string from an ISO date string */
function timeAgo(isoString: string): string {
	if (!isoString) return 'Never';
	const now = Date.now();
	const then = new Date(isoString).getTime();
	const diff = now - then;

	if (diff < 0) return 'Just now';

	const minutes = Math.floor(diff / 60000);
	if (minutes < 1) return 'Just now';
	if (minutes < 60) return `${minutes}m ago`;

	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;

	const days = Math.floor(hours / 24);
	if (days < 30) return `${days}d ago`;

	const months = Math.floor(days / 30);
	return `${months}mo ago`;
}

/** Truncates a changelog string to a max length with ellipsis */
function truncateChangelog(text: string, maxLength = 200): string {
	if (!text) return '';
	if (text.length <= maxLength) return text;
	return text.slice(0, maxLength) + '...';
}

/**
 * Determines the icon/status for a component during an update process.
 * Returns 'pending', 'updating', 'success', or 'failed'.
 */
function componentStatusIcon(
	component: string,
	status: {
		current_component: string | null;
		results: Array<{ component: string; success: boolean }>;
	} | null
): 'pending' | 'updating' | 'success' | 'failed' {
	if (!status) return 'pending';
	const result = status.results.find((r) => r.component === component);
	if (result) {
		return result.success ? 'success' : 'failed';
	}
	if (status.current_component === component) return 'updating';
	return 'pending';
}

/** Groups version entries by category */
function groupByCategory(
	entries: Array<{ key: string; category: string }>
): Record<string, typeof entries> {
	const groups: Record<string, typeof entries> = {
		core: [],
		docker: [],
		system: [],
		database: [],
		os: [],
	};

	for (const entry of entries) {
		const category = entry.category || 'system';
		if (!groups[category]) groups[category] = [];
		groups[category].push(entry);
	}

	return groups;
}

/** Sorts component entries by name */
function sortByName(entries: Array<{ name: string }>): Array<{ name: string }> {
	return [...entries].sort((a, b) => a.name.localeCompare(b.name));
}

/** Sorts component entries by status (error first, then unknown, then ok) */
function sortByStatus(
	entries: Array<{ name: string; status: string }>
): Array<{ name: string; status: string }> {
	const statusOrder: Record<string, number> = { error: 0, unknown: 1, ok: 2 };
	return [...entries].sort(
		(a, b) => (statusOrder[a.status] ?? 1) - (statusOrder[b.status] ?? 1)
	);
}

/** Calculates progress percentage from completed/total counts */
function calculateProgress(completed: number, total: number): number {
	if (total <= 0) return 0;
	return Math.min(100, Math.round((completed / total) * 100));
}

/** Formats duration between two ISO date strings */
function formatDuration(startIso: string, endIso: string): string {
	if (!startIso || !endIso) return '--';
	const start = new Date(startIso).getTime();
	const end = new Date(endIso).getTime();
	const diff = Math.max(0, end - start);
	const seconds = Math.floor(diff / 1000);
	if (seconds < 60) return `${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	const remainingSeconds = seconds % 60;
	return `${minutes}m ${remainingSeconds}s`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('UpdateSystem logic', () => {
	// -- Version status determination -----------------------------------------

	describe('versionStatusLabel', () => {
		it('returns "Update Available" when component has an update', () => {
			const updates = new Map([['zeek', { latest_version: '6.3.0' }]]);
			expect(versionStatusLabel('zeek', updates)).toBe('Update Available');
		});

		it('returns "Up to Date" when component has no update', () => {
			const updates = new Map<string, { latest_version: string }>();
			expect(versionStatusLabel('zeek', updates)).toBe('Up to Date');
		});

		it('returns "Up to Date" when a different component has an update', () => {
			const updates = new Map([['suricata', { latest_version: '7.1.0' }]]);
			expect(versionStatusLabel('zeek', updates)).toBe('Up to Date');
		});
	});

	// -- Version badge class mapping ------------------------------------------

	describe('versionStatusClass', () => {
		it('returns danger badge for error status', () => {
			const updates = new Map<string, { latest_version: string }>();
			expect(versionStatusClass('zeek', updates, 'error')).toBe('badge badge-danger');
		});

		it('returns muted badge for unknown status', () => {
			const updates = new Map<string, { latest_version: string }>();
			expect(versionStatusClass('zeek', updates, 'unknown')).toBe('badge badge-muted');
		});

		it('returns warning badge when update is available', () => {
			const updates = new Map([['zeek', { latest_version: '6.3.0' }]]);
			expect(versionStatusClass('zeek', updates, 'ok')).toBe('badge badge-warning');
		});

		it('returns success badge when up to date', () => {
			const updates = new Map<string, { latest_version: string }>();
			expect(versionStatusClass('zeek', updates, 'ok')).toBe('badge badge-success');
		});

		it('returns danger badge for error even when update is available', () => {
			const updates = new Map([['zeek', { latest_version: '6.3.0' }]]);
			expect(versionStatusClass('zeek', updates, 'error')).toBe('badge badge-danger');
		});
	});

	// -- Category grouping ----------------------------------------------------

	describe('groupByCategory', () => {
		it('groups entries by category', () => {
			const entries = [
				{ key: 'zeek', category: 'core' },
				{ key: 'suricata', category: 'core' },
				{ key: 'opensearch', category: 'database' },
				{ key: 'ubuntu', category: 'os' },
			];

			const groups = groupByCategory(entries);

			expect(groups.core).toHaveLength(2);
			expect(groups.database).toHaveLength(1);
			expect(groups.os).toHaveLength(1);
			expect(groups.docker).toHaveLength(0);
			expect(groups.system).toHaveLength(0);
		});

		it('defaults to system category for missing category', () => {
			const entries = [{ key: 'unknown', category: '' }];
			const groups = groupByCategory(entries);
			expect(groups.system).toHaveLength(1);
		});
	});

	// -- Update type badge mapping --------------------------------------------

	describe('updateTypeBadgeClass', () => {
		it('returns danger badge for major updates', () => {
			expect(updateTypeBadgeClass('major')).toBe('badge badge-danger');
		});

		it('returns warning badge for minor updates', () => {
			expect(updateTypeBadgeClass('minor')).toBe('badge badge-warning');
		});

		it('returns success badge for patch updates', () => {
			expect(updateTypeBadgeClass('patch')).toBe('badge badge-success');
		});

		it('returns muted badge for unknown update type', () => {
			expect(updateTypeBadgeClass('unknown')).toBe('badge badge-muted');
		});

		it('returns muted badge for unrecognized update type', () => {
			expect(updateTypeBadgeClass('something-else')).toBe('badge badge-muted');
		});
	});

	// -- Size formatting ------------------------------------------------------

	describe('formatSizeMB', () => {
		it('formats small sizes in MB', () => {
			expect(formatSizeMB(120)).toBe('120.0 MB');
		});

		it('formats fractional MB', () => {
			expect(formatSizeMB(0.5)).toBe('0.5 MB');
		});

		it('formats sizes >= 1024 MB in GB', () => {
			expect(formatSizeMB(1024)).toBe('1.0 GB');
		});

		it('formats large GB values', () => {
			expect(formatSizeMB(2560)).toBe('2.5 GB');
		});

		it('formats zero MB', () => {
			expect(formatSizeMB(0)).toBe('0.0 MB');
		});
	});

	// -- Time ago formatting --------------------------------------------------

	describe('timeAgo', () => {
		it('returns "Never" for empty string', () => {
			expect(timeAgo('')).toBe('Never');
		});

		it('returns "Just now" for recent timestamps', () => {
			const now = new Date().toISOString();
			expect(timeAgo(now)).toBe('Just now');
		});

		it('returns "Just now" for future timestamps', () => {
			const future = new Date(Date.now() + 60000).toISOString();
			expect(timeAgo(future)).toBe('Just now');
		});

		it('returns minutes ago for timestamps within the hour', () => {
			const fiveMinAgo = new Date(Date.now() - 5 * 60000).toISOString();
			expect(timeAgo(fiveMinAgo)).toBe('5m ago');
		});

		it('returns hours ago for timestamps within the day', () => {
			const threeHoursAgo = new Date(Date.now() - 3 * 3600000).toISOString();
			expect(timeAgo(threeHoursAgo)).toBe('3h ago');
		});

		it('returns days ago for timestamps within the month', () => {
			const fiveDaysAgo = new Date(Date.now() - 5 * 86400000).toISOString();
			expect(timeAgo(fiveDaysAgo)).toBe('5d ago');
		});

		it('returns months ago for old timestamps', () => {
			const twoMonthsAgo = new Date(Date.now() - 60 * 86400000).toISOString();
			expect(timeAgo(twoMonthsAgo)).toBe('2mo ago');
		});
	});

	// -- Progress percentage calculation --------------------------------------

	describe('calculateProgress', () => {
		it('returns 0 for zero total', () => {
			expect(calculateProgress(0, 0)).toBe(0);
		});

		it('returns 0 for negative total', () => {
			expect(calculateProgress(0, -1)).toBe(0);
		});

		it('returns correct percentage', () => {
			expect(calculateProgress(1, 4)).toBe(25);
		});

		it('returns 50 for half done', () => {
			expect(calculateProgress(2, 4)).toBe(50);
		});

		it('returns 100 for fully complete', () => {
			expect(calculateProgress(4, 4)).toBe(100);
		});

		it('caps at 100 for over-completion', () => {
			expect(calculateProgress(5, 4)).toBe(100);
		});
	});

	// -- Component sorting ----------------------------------------------------

	describe('sortByName', () => {
		it('sorts components alphabetically', () => {
			const entries = [
				{ name: 'Zeek' },
				{ name: 'Arkime' },
				{ name: 'Suricata' },
			];
			const sorted = sortByName(entries);
			expect(sorted[0].name).toBe('Arkime');
			expect(sorted[1].name).toBe('Suricata');
			expect(sorted[2].name).toBe('Zeek');
		});

		it('handles empty array', () => {
			expect(sortByName([])).toEqual([]);
		});

		it('handles single element', () => {
			const entries = [{ name: 'Zeek' }];
			expect(sortByName(entries)).toEqual([{ name: 'Zeek' }]);
		});
	});

	describe('sortByStatus', () => {
		it('sorts error status first', () => {
			const entries = [
				{ name: 'A', status: 'ok' },
				{ name: 'B', status: 'error' },
				{ name: 'C', status: 'unknown' },
			];
			const sorted = sortByStatus(entries);
			expect(sorted[0].status).toBe('error');
			expect(sorted[1].status).toBe('unknown');
			expect(sorted[2].status).toBe('ok');
		});

		it('handles all same status', () => {
			const entries = [
				{ name: 'A', status: 'ok' },
				{ name: 'B', status: 'ok' },
			];
			const sorted = sortByStatus(entries);
			expect(sorted).toHaveLength(2);
		});
	});

	// -- Changelog truncation -------------------------------------------------

	describe('truncateChangelog', () => {
		it('returns empty string for empty input', () => {
			expect(truncateChangelog('')).toBe('');
		});

		it('returns full text when shorter than max length', () => {
			expect(truncateChangelog('Short text')).toBe('Short text');
		});

		it('truncates long text with ellipsis', () => {
			const longText = 'A'.repeat(250);
			const result = truncateChangelog(longText, 200);
			expect(result.length).toBe(203); // 200 + '...'
			expect(result.endsWith('...')).toBe(true);
		});

		it('respects custom max length', () => {
			const text = 'Hello World';
			expect(truncateChangelog(text, 5)).toBe('Hello...');
		});

		it('returns exact length text without ellipsis', () => {
			const text = 'A'.repeat(200);
			expect(truncateChangelog(text, 200)).toBe(text);
		});
	});

	// -- Component status icon ------------------------------------------------

	describe('componentStatusIcon', () => {
		it('returns "pending" when status is null', () => {
			expect(componentStatusIcon('zeek', null)).toBe('pending');
		});

		it('returns "updating" when component is current', () => {
			const status = {
				current_component: 'zeek',
				results: [],
			};
			expect(componentStatusIcon('zeek', status)).toBe('updating');
		});

		it('returns "success" for successful result', () => {
			const status = {
				current_component: null,
				results: [{ component: 'zeek', success: true }],
			};
			expect(componentStatusIcon('zeek', status)).toBe('success');
		});

		it('returns "failed" for failed result', () => {
			const status = {
				current_component: null,
				results: [{ component: 'zeek', success: false }],
			};
			expect(componentStatusIcon('zeek', status)).toBe('failed');
		});

		it('returns "pending" when component is not in results or current', () => {
			const status = {
				current_component: 'suricata',
				results: [],
			};
			expect(componentStatusIcon('zeek', status)).toBe('pending');
		});

		it('prioritizes result over current_component', () => {
			const status = {
				current_component: 'zeek',
				results: [{ component: 'zeek', success: true }],
			};
			expect(componentStatusIcon('zeek', status)).toBe('success');
		});
	});

	// -- Duration formatting --------------------------------------------------

	describe('formatDuration', () => {
		it('returns "--" for empty start', () => {
			expect(formatDuration('', '2026-02-26T12:00:00Z')).toBe('--');
		});

		it('returns "--" for empty end', () => {
			expect(formatDuration('2026-02-26T12:00:00Z', '')).toBe('--');
		});

		it('formats seconds-only duration', () => {
			expect(formatDuration('2026-02-26T12:00:00Z', '2026-02-26T12:00:30Z')).toBe('30s');
		});

		it('formats minutes and seconds duration', () => {
			expect(formatDuration('2026-02-26T12:00:00Z', '2026-02-26T12:02:15Z')).toBe('2m 15s');
		});

		it('handles zero duration', () => {
			expect(formatDuration('2026-02-26T12:00:00Z', '2026-02-26T12:00:00Z')).toBe('0s');
		});
	});
});
