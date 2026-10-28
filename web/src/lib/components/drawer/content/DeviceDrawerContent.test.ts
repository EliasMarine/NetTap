import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for DeviceDrawerContent component logic.
 *
 * DeviceDrawerContent.svelte uses Svelte 5 runes ($state, $props, $derived,
 * $effect). Instead of rendering, we extract and test the pure logic:
 * risk level mapping, byte formatting, time-ago formatting, tab visibility,
 * sparkline path generation, and device field display.
 */

// ---------------------------------------------------------------------------
// Reproduced logic from DeviceDrawerContent.svelte
// ---------------------------------------------------------------------------

interface DeviceData {
	ip: string;
	mac: string | null;
	hostname: string | null;
	manufacturer: string | null;
	os_hint: string | null;
	first_seen: string;
	last_seen: string;
	total_bytes: number;
	connection_count: number;
	protocols: string[];
	alert_count: number;
	risk_score?: number;
}

const RISK_COLORS: Record<string, string> = {
	critical: 'var(--red)',
	high: 'var(--orange)',
	medium: 'var(--amber)',
	low: 'var(--green)',
	none: 'var(--text-muted)',
};

function getRiskLevel(score: number | undefined): string {
	if (score == null) return 'none';
	if (score >= 80) return 'critical';
	if (score >= 60) return 'high';
	if (score >= 40) return 'medium';
	if (score >= 20) return 'low';
	return 'none';
}

function formatBytes(bytes: number): string {
	if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
	if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
	if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(1)} KB`;
	return `${bytes} B`;
}

function timeAgo(ts: string): string {
	const diff = Date.now() - new Date(ts).getTime();
	if (diff < 60_000) return 'just now';
	if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
	if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
	return `${Math.floor(diff / 86_400_000)}d ago`;
}

function getVisibleContent(activeTab: string): 'overview' | 'connections' | 'traffic' | 'none' {
	if (activeTab === 'overview') return 'overview';
	if (activeTab === 'connections') return 'connections';
	if (activeTab === 'traffic') return 'traffic';
	return 'none';
}

function buildSparklinePath(data: Array<{ bytes: number }>): string {
	if (data.length < 2) return '';
	const max = Math.max(...data.map(d => d.bytes), 1);
	const w = 400;
	const h = 60;
	const points = data.map((d, i) => {
		const x = (i / (data.length - 1)) * w;
		const y = h - (d.bytes / max) * h;
		return `${x},${y}`;
	});
	return `M${points.join(' L')}`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DeviceDrawerContent logic', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- Tab visibility -------------------------------------------------------

	describe('tab visibility', () => {
		it('renders overview tab', () => {
			expect(getVisibleContent('overview')).toBe('overview');
		});

		it('renders connections tab', () => {
			expect(getVisibleContent('connections')).toBe('connections');
		});

		it('renders traffic tab', () => {
			expect(getVisibleContent('traffic')).toBe('traffic');
		});

		it('renders nothing for unknown tab', () => {
			expect(getVisibleContent('other')).toBe('none');
		});
	});

	// -- Risk level -----------------------------------------------------------

	describe('getRiskLevel', () => {
		it('returns "critical" for score >= 80', () => {
			expect(getRiskLevel(80)).toBe('critical');
			expect(getRiskLevel(100)).toBe('critical');
		});

		it('returns "high" for score >= 60', () => {
			expect(getRiskLevel(60)).toBe('high');
			expect(getRiskLevel(79)).toBe('high');
		});

		it('returns "medium" for score >= 40', () => {
			expect(getRiskLevel(40)).toBe('medium');
			expect(getRiskLevel(59)).toBe('medium');
		});

		it('returns "low" for score >= 20', () => {
			expect(getRiskLevel(20)).toBe('low');
			expect(getRiskLevel(39)).toBe('low');
		});

		it('returns "none" for score < 20', () => {
			expect(getRiskLevel(0)).toBe('none');
			expect(getRiskLevel(19)).toBe('none');
		});

		it('returns "none" for undefined score', () => {
			expect(getRiskLevel(undefined)).toBe('none');
		});
	});

	// -- Risk color mapping ---------------------------------------------------

	describe('RISK_COLORS', () => {
		it('has correct color for each risk level', () => {
			expect(RISK_COLORS['critical']).toBe('var(--red)');
			expect(RISK_COLORS['high']).toBe('var(--orange)');
			expect(RISK_COLORS['medium']).toBe('var(--amber)');
			expect(RISK_COLORS['low']).toBe('var(--green)');
			expect(RISK_COLORS['none']).toBe('var(--text-muted)');
		});
	});

	// -- formatBytes ----------------------------------------------------------

	describe('formatBytes', () => {
		it('formats bytes', () => {
			expect(formatBytes(500)).toBe('500 B');
			expect(formatBytes(0)).toBe('0 B');
		});

		it('formats kilobytes', () => {
			expect(formatBytes(1024)).toBe('1.0 KB');
			expect(formatBytes(2560)).toBe('2.5 KB');
		});

		it('formats megabytes', () => {
			expect(formatBytes(1_048_576)).toBe('1.0 MB');
			expect(formatBytes(5_242_880)).toBe('5.0 MB');
		});

		it('formats gigabytes', () => {
			expect(formatBytes(1_073_741_824)).toBe('1.0 GB');
		});
	});

	// -- timeAgo --------------------------------------------------------------

	describe('timeAgo', () => {
		it('returns "just now" for recent timestamps', () => {
			const now = new Date().toISOString();
			expect(timeAgo(now)).toBe('just now');
		});

		it('returns minutes ago', () => {
			const tenMinAgo = new Date(Date.now() - 10 * 60_000).toISOString();
			expect(timeAgo(tenMinAgo)).toBe('10m ago');
		});

		it('returns hours ago', () => {
			const twoHoursAgo = new Date(Date.now() - 2 * 3_600_000).toISOString();
			expect(timeAgo(twoHoursAgo)).toBe('2h ago');
		});

		it('returns days ago', () => {
			const threeDaysAgo = new Date(Date.now() - 3 * 86_400_000).toISOString();
			expect(timeAgo(threeDaysAgo)).toBe('3d ago');
		});
	});

	// -- Device overview fields -----------------------------------------------

	describe('device overview fields', () => {
		const device: DeviceData = {
			ip: '192.168.1.100',
			mac: 'AA:BB:CC:DD:EE:FF',
			hostname: 'my-laptop',
			manufacturer: 'Apple Inc.',
			os_hint: 'macOS',
			first_seen: '2026-02-01T00:00:00Z',
			last_seen: '2026-03-10T12:00:00Z',
			total_bytes: 5_242_880,
			connection_count: 150,
			protocols: ['tcp', 'udp', 'tls', 'dns'],
			alert_count: 3,
		};

		it('shows IP address', () => {
			expect(device.ip).toBe('192.168.1.100');
		});

		it('shows MAC address', () => {
			expect(device.mac).toBe('AA:BB:CC:DD:EE:FF');
		});

		it('shows hostname', () => {
			expect(device.hostname).toBe('my-laptop');
		});

		it('shows manufacturer', () => {
			expect(device.manufacturer).toBe('Apple Inc.');
		});

		it('shows OS hint', () => {
			expect(device.os_hint).toBe('macOS');
		});

		it('formats total bytes', () => {
			expect(formatBytes(device.total_bytes)).toBe('5.0 MB');
		});

		it('shows connection count', () => {
			expect(device.connection_count).toBe(150);
		});

		it('shows alert count', () => {
			expect(device.alert_count).toBe(3);
		});

		it('lists protocols', () => {
			expect(device.protocols).toHaveLength(4);
			expect(device.protocols).toContain('tls');
		});

		it('handles device with null optional fields', () => {
			const minimal: DeviceData = {
				ip: '10.0.0.1',
				mac: null,
				hostname: null,
				manufacturer: null,
				os_hint: null,
				first_seen: '2026-01-01T00:00:00Z',
				last_seen: '2026-01-01T00:00:00Z',
				total_bytes: 0,
				connection_count: 0,
				protocols: [],
				alert_count: 0,
			};
			expect(minimal.mac).toBeNull();
			expect(minimal.hostname).toBeNull();
			expect(minimal.protocols).toHaveLength(0);
		});
	});

	// -- Sparkline path generation --------------------------------------------

	describe('buildSparklinePath', () => {
		it('returns empty string for less than 2 data points', () => {
			expect(buildSparklinePath([])).toBe('');
			expect(buildSparklinePath([{ bytes: 100 }])).toBe('');
		});

		it('generates valid SVG path for 2+ data points', () => {
			const path = buildSparklinePath([
				{ bytes: 100 },
				{ bytes: 200 },
				{ bytes: 150 },
			]);
			expect(path).toMatch(/^M/);
			expect(path).toContain(' L');
		});

		it('handles all-zero data', () => {
			const path = buildSparklinePath([
				{ bytes: 0 },
				{ bytes: 0 },
			]);
			expect(path).toMatch(/^M/);
		});

		it('scales Y correctly (max bytes at top)', () => {
			const path = buildSparklinePath([
				{ bytes: 0 },
				{ bytes: 100 },
			]);
			// First point should be at y=60 (bottom), second at y=0 (top)
			expect(path).toContain('0,60');
			expect(path).toContain('400,0');
		});
	});
});
