import { describe, it, expect } from 'vitest';

/**
 * Tests for StorageTierPanel component logic.
 *
 * Extracts and tests the pure formatting/color functions from the component.
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from StorageTierPanel.svelte
// ---------------------------------------------------------------------------

function formatBytes(bytes: number): string {
	if (!bytes || bytes <= 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	const value = bytes / Math.pow(1024, i);
	return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
}

function diskUsageColor(percent: number): string {
	if (percent > 85) return 'var(--danger)';
	if (percent > 70) return 'var(--warning)';
	return 'var(--success)';
}

interface TierConfig {
	key: string;
	label: string;
	color: string;
	days: string;
}

const TIERS: TierConfig[] = [
	{ key: 'hot', label: 'Hot (Zeek Metadata)', color: 'var(--red)', days: '90d' },
	{ key: 'warm', label: 'Warm (Suricata Alerts)', color: 'var(--amber)', days: '180d' },
	{ key: 'cold', label: 'Cold (PCAP)', color: 'var(--blue)', days: '30d' },
];

function computeTierData(indexCounts: Record<string, number>): Array<TierConfig & { indexCount: number }> {
	return TIERS.map((tier) => ({
		...tier,
		indexCount: indexCounts[tier.key] ?? 0,
	}));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('StorageTierPanel logic', () => {
	describe('formatBytes', () => {
		it('returns 0 B for zero', () => {
			expect(formatBytes(0)).toBe('0 B');
		});

		it('returns 0 B for negative values', () => {
			expect(formatBytes(-100)).toBe('0 B');
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

		it('formats TB', () => {
			expect(formatBytes(1099511627776)).toBe('1.0 TB');
		});
	});

	describe('diskUsageColor', () => {
		it('returns success for low usage', () => {
			expect(diskUsageColor(50)).toBe('var(--success)');
		});

		it('returns success at 70%', () => {
			expect(diskUsageColor(70)).toBe('var(--success)');
		});

		it('returns warning above 70%', () => {
			expect(diskUsageColor(71)).toBe('var(--warning)');
		});

		it('returns warning at 85%', () => {
			expect(diskUsageColor(85)).toBe('var(--warning)');
		});

		it('returns danger above 85%', () => {
			expect(diskUsageColor(86)).toBe('var(--danger)');
		});

		it('returns danger at 100%', () => {
			expect(diskUsageColor(100)).toBe('var(--danger)');
		});
	});

	describe('TIERS configuration', () => {
		it('has exactly 3 tiers', () => {
			expect(TIERS).toHaveLength(3);
		});

		it('has hot, warm, cold keys', () => {
			expect(TIERS.map((t) => t.key)).toEqual(['hot', 'warm', 'cold']);
		});

		it('has retention periods', () => {
			expect(TIERS[0].days).toBe('90d');
			expect(TIERS[1].days).toBe('180d');
			expect(TIERS[2].days).toBe('30d');
		});
	});

	describe('computeTierData', () => {
		it('maps index counts to tiers', () => {
			const result = computeTierData({ hot: 90, warm: 45, cold: 10 });

			expect(result).toHaveLength(3);
			expect(result[0].indexCount).toBe(90);
			expect(result[1].indexCount).toBe(45);
			expect(result[2].indexCount).toBe(10);
		});

		it('defaults missing tiers to 0', () => {
			const result = computeTierData({ hot: 5 });

			expect(result[0].indexCount).toBe(5);
			expect(result[1].indexCount).toBe(0);
			expect(result[2].indexCount).toBe(0);
		});

		it('handles empty counts', () => {
			const result = computeTierData({});

			expect(result.every((t) => t.indexCount === 0)).toBe(true);
		});
	});
});
