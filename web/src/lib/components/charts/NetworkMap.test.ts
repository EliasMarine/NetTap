import { describe, it, expect } from 'vitest';

/**
 * Tests for NetworkMap logic.
 *
 * The NetworkMap.svelte component uses Svelte 5 runes ($derived, $state)
 * and a force-directed simulation that is difficult to fully render in a
 * jsdom test environment.  Instead we extract and test the pure logic
 * functions: risk level colors, protocol colors, connection width scaling,
 * device type labels, hexagon point generation, and layout utilities.
 */

// ---------------------------------------------------------------------------
// Reproduced types and constants from NetworkMap.svelte
// ---------------------------------------------------------------------------

interface MapDevice {
	ip: string;
	label: string;
	type: 'router' | 'server' | 'desktop' | 'mobile' | 'iot' | 'unknown';
	risk_level: 'low' | 'medium' | 'high' | 'critical';
	connection_count: number;
	total_bytes: number;
}

interface MapConnection {
	source_ip: string;
	target_ip: string;
	bytes: number;
	protocol: string;
}

const NODE_RADIUS = 16;
const GRID_SPACING = 40;

const RISK_COLORS: Record<string, string> = {
	low: '#3fb950',
	medium: '#d29922',
	high: '#f85149',
	critical: '#da3633',
};

const PROTOCOL_COLORS: Record<string, string> = {
	TCP: '#58a6ff',
	tcp: '#58a6ff',
	UDP: '#bc8cff',
	udp: '#bc8cff',
	HTTP: '#3fb950',
	http: '#3fb950',
	HTTPS: '#3fb950',
	https: '#3fb950',
	DNS: '#d29922',
	dns: '#d29922',
};
const DEFAULT_PROTOCOL_COLOR = '#8b949e';

const DEVICE_TYPE_LABELS: Record<string, string> = {
	router: 'Router',
	server: 'Server',
	desktop: 'Desktop',
	mobile: 'Mobile',
	iot: 'IoT Device',
	unknown: 'Unknown',
};

// ---------------------------------------------------------------------------
// Reproduced pure logic from NetworkMap.svelte
// ---------------------------------------------------------------------------

/** Connection line width: scale bytes to 1-4px stroke */
function connectionWidth(bytes: number, maxBytes: number): number {
	return 1 + (bytes / maxBytes) * 3;
}

/** Protocol color lookup */
function protocolColor(protocol: string): string {
	return PROTOCOL_COLORS[protocol] || DEFAULT_PROTOCOL_COLOR;
}

/** Risk level color lookup */
function riskColor(level: string): string {
	return RISK_COLORS[level] || '#8b949e';
}

/** Device type label lookup */
function deviceTypeLabel(type: string): string {
	return DEVICE_TYPE_LABELS[type] || type;
}

/** Generate hexagon SVG polygon points — mirrors the exported hexagonPoints() */
function hexagonPoints(radius: number): string {
	const pts: string[] = [];
	for (let i = 0; i < 6; i++) {
		const angle = (Math.PI / 3) * i - Math.PI / 6;
		pts.push(`${(radius * Math.cos(angle)).toFixed(2)},${(radius * Math.sin(angle)).toFixed(2)}`);
	}
	return pts.join(' ');
}

/** Compute grid lines for a given dimension — mirrors gridLinesX/gridLinesY */
function computeGridLines(dimension: number, spacing: number): number[] {
	const lines: number[] = [];
	for (let x = spacing; x < dimension; x += spacing) {
		lines.push(x);
	}
	return lines;
}

/** Sort risk levels in severity order — mirrors presentRiskLevels logic */
function sortRiskLevels(levels: string[]): string[] {
	const order = ['low', 'medium', 'high', 'critical'];
	const levelSet = new Set(levels);
	return order.filter((l) => levelSet.has(l));
}

/** Truncate device label — mirrors the inline truncation in the template */
function truncateDeviceLabel(label: string): string {
	if (label.length > 14) return label.slice(0, 13) + '\u2026';
	return label;
}

/** Compute initial radial position — mirrors the initialization in the force sim */
function initialRadialPosition(
	connectionCount: number,
	maxConnections: number,
	centerX: number,
	centerY: number,
	index: number
): { x: number; y: number } {
	const ratio = 1 - connectionCount / maxConnections;
	const maxRadius = Math.min(centerX, centerY) * 0.75;
	const r = ratio * maxRadius + 30;
	const goldenAngle = Math.PI * (3 - Math.sqrt(5));
	const angle = index * goldenAngle;

	return {
		x: centerX + r * Math.cos(angle),
		y: centerY + r * Math.sin(angle),
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NetworkMap logic', () => {
	// -- riskColor ------------------------------------------------------------

	describe('riskColor', () => {
		it('returns green for low risk', () => {
			expect(riskColor('low')).toBe('#3fb950');
		});

		it('returns yellow for medium risk', () => {
			expect(riskColor('medium')).toBe('#d29922');
		});

		it('returns red for high risk', () => {
			expect(riskColor('high')).toBe('#f85149');
		});

		it('returns dark red for critical risk', () => {
			expect(riskColor('critical')).toBe('#da3633');
		});

		it('returns fallback gray for unknown risk level', () => {
			expect(riskColor('none')).toBe('#8b949e');
		});

		it('returns fallback gray for empty string', () => {
			expect(riskColor('')).toBe('#8b949e');
		});
	});

	// -- protocolColor --------------------------------------------------------

	describe('protocolColor', () => {
		it('returns blue for TCP (uppercase)', () => {
			expect(protocolColor('TCP')).toBe('#58a6ff');
		});

		it('returns blue for tcp (lowercase)', () => {
			expect(protocolColor('tcp')).toBe('#58a6ff');
		});

		it('returns purple for UDP', () => {
			expect(protocolColor('UDP')).toBe('#bc8cff');
		});

		it('returns green for HTTP', () => {
			expect(protocolColor('HTTP')).toBe('#3fb950');
		});

		it('returns green for HTTPS', () => {
			expect(protocolColor('HTTPS')).toBe('#3fb950');
		});

		it('returns yellow for DNS', () => {
			expect(protocolColor('DNS')).toBe('#d29922');
		});

		it('returns default gray for unknown protocol', () => {
			expect(protocolColor('ICMP')).toBe(DEFAULT_PROTOCOL_COLOR);
		});

		it('returns default gray for empty protocol string', () => {
			expect(protocolColor('')).toBe(DEFAULT_PROTOCOL_COLOR);
		});
	});

	// -- connectionWidth ------------------------------------------------------

	describe('connectionWidth', () => {
		it('returns 1 for zero bytes', () => {
			expect(connectionWidth(0, 1000)).toBe(1);
		});

		it('returns 4 when bytes equals maxBytes', () => {
			expect(connectionWidth(1000, 1000)).toBe(4);
		});

		it('returns 2.5 for bytes at 50% of max', () => {
			expect(connectionWidth(500, 1000)).toBe(2.5);
		});

		it('scales linearly between 1 and 4', () => {
			const w25 = connectionWidth(250, 1000);
			const w75 = connectionWidth(750, 1000);
			expect(w25).toBeCloseTo(1.75, 4);
			expect(w75).toBeCloseTo(3.25, 4);
		});
	});

	// -- deviceTypeLabel ------------------------------------------------------

	describe('deviceTypeLabel', () => {
		it('returns "Router" for router type', () => {
			expect(deviceTypeLabel('router')).toBe('Router');
		});

		it('returns "Server" for server type', () => {
			expect(deviceTypeLabel('server')).toBe('Server');
		});

		it('returns "Desktop" for desktop type', () => {
			expect(deviceTypeLabel('desktop')).toBe('Desktop');
		});

		it('returns "Mobile" for mobile type', () => {
			expect(deviceTypeLabel('mobile')).toBe('Mobile');
		});

		it('returns "IoT Device" for iot type', () => {
			expect(deviceTypeLabel('iot')).toBe('IoT Device');
		});

		it('returns "Unknown" for unknown type', () => {
			expect(deviceTypeLabel('unknown')).toBe('Unknown');
		});

		it('returns the raw type string for unrecognized types', () => {
			expect(deviceTypeLabel('printer')).toBe('printer');
		});
	});

	// -- hexagonPoints --------------------------------------------------------

	describe('hexagonPoints', () => {
		it('generates exactly 6 coordinate pairs', () => {
			const pts = hexagonPoints(10);
			const pairs = pts.split(' ');
			expect(pairs).toHaveLength(6);
		});

		it('each pair contains comma-separated x,y values', () => {
			const pts = hexagonPoints(10);
			const pairs = pts.split(' ');
			for (const pair of pairs) {
				expect(pair).toMatch(/^-?\d+\.\d+,-?\d+\.\d+$/);
			}
		});

		it('all points are within the radius from origin', () => {
			const radius = 16;
			const pts = hexagonPoints(radius);
			const pairs = pts.split(' ');
			for (const pair of pairs) {
				const [x, y] = pair.split(',').map(Number);
				const dist = Math.sqrt(x * x + y * y);
				expect(dist).toBeCloseTo(radius, 1);
			}
		});

		it('returns different values for different radii', () => {
			const small = hexagonPoints(5);
			const large = hexagonPoints(20);
			expect(small).not.toBe(large);
		});
	});

	// -- computeGridLines -----------------------------------------------------

	describe('computeGridLines', () => {
		it('generates correct grid lines for a dimension', () => {
			const lines = computeGridLines(120, 40);
			expect(lines).toEqual([40, 80]);
		});

		it('returns empty array when dimension is smaller than spacing', () => {
			const lines = computeGridLines(30, 40);
			expect(lines).toEqual([]);
		});

		it('does not include the boundary value itself', () => {
			const lines = computeGridLines(80, 40);
			expect(lines).toEqual([40]);
			expect(lines).not.toContain(80);
		});
	});

	// -- sortRiskLevels -------------------------------------------------------

	describe('sortRiskLevels', () => {
		it('sorts levels in severity order: low, medium, high, critical', () => {
			const result = sortRiskLevels(['critical', 'low', 'high', 'medium']);
			expect(result).toEqual(['low', 'medium', 'high', 'critical']);
		});

		it('filters out unknown levels', () => {
			const result = sortRiskLevels(['low', 'extreme', 'high']);
			expect(result).toEqual(['low', 'high']);
		});

		it('returns empty array when no valid levels present', () => {
			expect(sortRiskLevels([])).toEqual([]);
			expect(sortRiskLevels(['unknown'])).toEqual([]);
		});

		it('handles duplicates correctly by deduplication', () => {
			const result = sortRiskLevels(['low', 'low', 'high', 'high']);
			expect(result).toEqual(['low', 'high']);
		});
	});

	// -- truncateDeviceLabel --------------------------------------------------

	describe('truncateDeviceLabel', () => {
		it('returns the label unchanged when 14 chars or fewer', () => {
			expect(truncateDeviceLabel('my-laptop')).toBe('my-laptop');
		});

		it('returns the label unchanged at exactly 14 chars', () => {
			expect(truncateDeviceLabel('12345678901234')).toBe('12345678901234');
		});

		it('truncates and appends ellipsis when longer than 14 chars', () => {
			const result = truncateDeviceLabel('my-very-long-device-name');
			expect(result).toBe('my-very-long-\u2026');
			expect(result.length).toBe(14);
		});

		it('handles empty string', () => {
			expect(truncateDeviceLabel('')).toBe('');
		});
	});

	// -- initialRadialPosition ------------------------------------------------

	describe('initialRadialPosition', () => {
		it('places a device with max connections close to center', () => {
			const pos = initialRadialPosition(100, 100, 400, 300, 0);
			// ratio = 0 => r = 0 * maxRadius + 30 = 30
			const distFromCenter = Math.sqrt(
				(pos.x - 400) ** 2 + (pos.y - 300) ** 2
			);
			expect(distFromCenter).toBeCloseTo(30, 0);
		});

		it('places a device with zero connections at the periphery', () => {
			const pos = initialRadialPosition(0, 100, 400, 300, 0);
			// ratio = 1 => r = 1 * 225 + 30 = 255
			const maxRadius = Math.min(400, 300) * 0.75; // 225
			const expectedR = 1 * maxRadius + 30;
			const distFromCenter = Math.sqrt(
				(pos.x - 400) ** 2 + (pos.y - 300) ** 2
			);
			expect(distFromCenter).toBeCloseTo(expectedR, 0);
		});

		it('spreads multiple devices using golden angle', () => {
			const pos0 = initialRadialPosition(50, 100, 400, 300, 0);
			const pos1 = initialRadialPosition(50, 100, 400, 300, 1);
			const pos2 = initialRadialPosition(50, 100, 400, 300, 2);

			// All three positions should be distinct
			expect(pos0.x).not.toBeCloseTo(pos1.x, 1);
			expect(pos1.x).not.toBeCloseTo(pos2.x, 1);
		});
	});
});
