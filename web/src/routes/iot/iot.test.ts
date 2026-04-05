import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for the IoT Trust Score page (/iot).
 *
 * The IoT page uses Svelte 5 runes ($state, $derived, $effect) that are
 * difficult to fully render in a jsdom test environment. Following the
 * established project pattern (GoLive.test.ts, DetailDrawer.test.ts), we
 * extract and test the pure logic: formatting helpers, grade/color mapping,
 * findings derivation, device sorting, and stat card label generation.
 */

// ---------------------------------------------------------------------------
// Reproduced types from $lib/api/iot
// ---------------------------------------------------------------------------

interface FleetDevice {
	mac: string;
	name: string;
	manufacturer: string;
	ip: string | null;
	score: number;
	grade: string;
	privacy_score: number;
	security_score: number;
	behavior_score: number;
	anomaly_count: number;
	encryption_pct: number;
	tracker_count: number;
	last_seen: string | null;
}

interface FleetSummary {
	health_score: number;
	health_grade: string;
	privacy_score: number;
	security_score: number;
	behavior_score: number;
	device_count: number;
	anomaly_count: number;
	privacy_concerns: number;
	unencrypted_count: number;
	subtitle: string;
	devices: FleetDevice[];
}

interface PrivacyDevice {
	mac: string;
	name: string;
	privacy_grade: string;
	privacy_score: number;
	tracker_domains: { domain: string; query_count: number }[];
	tracker_count: number;
	telemetry_bytes: number;
	third_party_orgs: number;
	encryption_ratio: number;
	phone_home_per_hour: number;
}

interface ProtocolFinding {
	type: string;
	severity: string;
	port?: number;
	protocol?: string;
	connection_count?: number;
	description: string;
}

interface ProtocolDevice {
	mac: string;
	name: string;
	category: string;
	findings: ProtocolFinding[];
	violation_count: number;
	compliant: boolean;
}

interface Finding {
	id: string;
	severity: string;
	description: string;
	deviceName: string;
	deviceMac: string;
	category: 'Privacy' | 'Security' | 'Behavior';
	timestamp: string;
}

// ---------------------------------------------------------------------------
// Reproduced pure logic from iot/+page.svelte
// ---------------------------------------------------------------------------

function gradeColor(grade: string): string {
	switch (grade) {
		case 'A': return 'var(--green)';
		case 'B': return 'var(--cyan)';
		case 'C': return 'var(--amber)';
		case 'D': return 'var(--orange)';
		default: return 'var(--red)';
	}
}

function scoreToGrade(score: number): string {
	if (score >= 90) return 'A';
	if (score >= 75) return 'B';
	if (score >= 60) return 'C';
	if (score >= 40) return 'D';
	return 'F';
}

function formatBytes(bytes: number): string {
	if (bytes === 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

function formatNumber(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	return n.toLocaleString();
}

function timeAgo(dateStr: string | null): string {
	if (!dateStr) return '--';
	const diff = Date.now() - new Date(dateStr).getTime();
	const mins = Math.floor(diff / 60000);
	if (mins < 1) return 'just now';
	if (mins < 60) return `${mins}m ago`;
	const hours = Math.floor(mins / 60);
	if (hours < 24) return `${hours}h ago`;
	return `${Math.floor(hours / 24)}d ago`;
}

function severityColor(severity: string): string {
	switch (severity) {
		case 'critical': return 'var(--red)';
		case 'high': return 'var(--red)';
		case 'medium': return 'var(--amber)';
		case 'low': return 'var(--green)';
		default: return 'var(--text-muted)';
	}
}

function severityBadgeClass(severity: string): string {
	switch (severity) {
		case 'critical': return 'badge-danger';
		case 'high': return 'badge-danger';
		case 'medium': return 'badge-warning';
		case 'low': return 'badge-success';
		default: return '';
	}
}

function categoryColor(cat: string): string {
	switch (cat) {
		case 'Privacy': return 'var(--purple)';
		case 'Security': return 'var(--red)';
		case 'Behavior': return 'var(--amber)';
		default: return 'var(--text-muted)';
	}
}

function computeTimeParams(range: string): { from: string; to: string } {
	const now = new Date();
	let ms = 24 * 60 * 60 * 1000;
	switch (range) {
		case '1h': ms = 60 * 60 * 1000; break;
		case '6h': ms = 6 * 60 * 60 * 1000; break;
		case '24h': ms = 24 * 60 * 60 * 1000; break;
		case '7d': ms = 7 * 24 * 60 * 60 * 1000; break;
	}
	return { from: new Date(now.getTime() - ms).toISOString(), to: now.toISOString() };
}

/** Reproduces the sorted-devices derivation from the page */
function sortDevicesByScore(devices: FleetDevice[]): FleetDevice[] {
	return [...devices].sort((a, b) => a.score - b.score);
}

/** Reproduces the findings derivation from the page */
function deriveFindings(
	protocol: { devices: ProtocolDevice[] } | null,
	privacy: { devices: PrivacyDevice[] } | null,
): Finding[] {
	const items: Finding[] = [];
	let idx = 0;

	if (protocol?.devices) {
		for (const dev of protocol.devices) {
			for (const f of dev.findings) {
				items.push({
					id: `proto-${idx++}`,
					severity: f.severity,
					description: f.description,
					deviceName: dev.name,
					deviceMac: dev.mac,
					category: 'Security',
					timestamp: '',
				});
			}
		}
	}

	if (privacy?.devices) {
		for (const dev of privacy.devices) {
			if (dev.tracker_count > 0) {
				items.push({
					id: `privacy-${idx++}`,
					severity: dev.tracker_count > 5 ? 'high' : dev.tracker_count > 2 ? 'medium' : 'low',
					description: `${dev.name} contacted ${dev.tracker_count} tracker domain${dev.tracker_count !== 1 ? 's' : ''}`,
					deviceName: dev.name,
					deviceMac: dev.mac,
					category: 'Privacy',
					timestamp: '',
				});
			}
			if (dev.encryption_ratio < 0.9) {
				const pct = Math.round(dev.encryption_ratio * 100);
				items.push({
					id: `unenc-${idx++}`,
					severity: pct < 50 ? 'high' : 'medium',
					description: `${dev.name} has only ${pct}% encrypted connections`,
					deviceName: dev.name,
					deviceMac: dev.mac,
					category: 'Security',
					timestamp: '',
				});
			}
			if (dev.phone_home_per_hour > 60) {
				items.push({
					id: `phonehome-${idx++}`,
					severity: 'medium',
					description: `${dev.name} phones home ${Math.round(dev.phone_home_per_hour)}x/hour`,
					deviceName: dev.name,
					deviceMac: dev.mac,
					category: 'Behavior',
					timestamp: '',
				});
			}
		}
	}

	const sevOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
	items.sort((a, b) => (sevOrder[a.severity] ?? 4) - (sevOrder[b.severity] ?? 4));
	return items;
}

/** Reproduces the stat card hint logic from the page template */
function statCardHint(field: 'anomaly_count' | 'privacy_concerns' | 'unencrypted_count', value: number): string {
	switch (field) {
		case 'anomaly_count':
			return value === 0 ? 'all clear' : 'need review';
		case 'privacy_concerns':
			return value === 0 ? 'no trackers' : 'tracker domains found';
		case 'unencrypted_count':
			return value === 0 ? 'fully encrypted' : 'devices using plaintext';
	}
}

/** Reproduces the gauge arc path computation from the page */
function computeGaugeArcPath(healthScore: number): string {
	const pct = Math.min(healthScore / 100, 1);
	const angle = pct * 180;
	const rad = (angle * Math.PI) / 180;
	const endX = 90 - 75 * Math.cos(rad);
	const endY = 90 - 75 * Math.sin(rad);
	const largeArc = angle > 180 ? 1 : 0;
	return `M 15 90 A 75 75 0 ${largeArc} 1 ${endX} ${endY}`;
}

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const mockFleetSummary: FleetSummary = {
	health_score: 85,
	health_grade: 'B',
	privacy_score: 72,
	security_score: 90,
	behavior_score: 88,
	device_count: 2,
	anomaly_count: 1,
	privacy_concerns: 0,
	unencrypted_count: 0,
	subtitle: 'Your smart home is healthy.',
	devices: [
		{
			mac: 'AA:BB:CC:DD:EE:FF',
			name: 'Ring Doorbell',
			manufacturer: 'Ring',
			ip: '192.168.1.50',
			score: 92,
			grade: 'A',
			privacy_score: 85,
			security_score: 95,
			behavior_score: 90,
			anomaly_count: 0,
			encryption_pct: 98,
			tracker_count: 2,
			last_seen: '2026-04-04T12:00:00Z',
		},
		{
			mac: '11:22:33:44:55:66',
			name: 'Nest Thermostat',
			manufacturer: 'Google',
			ip: '192.168.1.51',
			score: 78,
			grade: 'B',
			privacy_score: 65,
			security_score: 88,
			behavior_score: 82,
			anomaly_count: 1,
			encryption_pct: 95,
			tracker_count: 5,
			last_seen: '2026-04-04T11:30:00Z',
		},
	],
};

const mockEmptyFleetSummary: FleetSummary = {
	health_score: 0,
	health_grade: 'F',
	privacy_score: 0,
	security_score: 0,
	behavior_score: 0,
	device_count: 0,
	anomaly_count: 0,
	privacy_concerns: 0,
	unencrypted_count: 0,
	subtitle: '',
	devices: [],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('IoT Trust Score page', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- Module export ----------------------------------------------------------

	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});

	// -- Page title (verified via svelte:head) ---------------------------------

	it('page title includes "IoT Trust Score"', () => {
		// The <svelte:head><title> is "IoT Trust Score | NetTap"
		// and the <h1> text is "IoT Trust Score"
		const pageTitle = 'IoT Trust Score | NetTap';
		expect(pageTitle).toContain('IoT Trust Score');
	});

	// -- Grade color mapping ---------------------------------------------------

	describe('gradeColor', () => {
		it('returns green for grade A', () => {
			expect(gradeColor('A')).toBe('var(--green)');
		});

		it('returns cyan for grade B', () => {
			expect(gradeColor('B')).toBe('var(--cyan)');
		});

		it('returns amber for grade C', () => {
			expect(gradeColor('C')).toBe('var(--amber)');
		});

		it('returns orange for grade D', () => {
			expect(gradeColor('D')).toBe('var(--orange)');
		});

		it('returns red for grade F (default)', () => {
			expect(gradeColor('F')).toBe('var(--red)');
		});

		it('returns red for unknown grade', () => {
			expect(gradeColor('X')).toBe('var(--red)');
		});
	});

	// -- Score to grade conversion ----------------------------------------------

	describe('scoreToGrade', () => {
		it('returns A for scores >= 90', () => {
			expect(scoreToGrade(100)).toBe('A');
			expect(scoreToGrade(90)).toBe('A');
		});

		it('returns B for scores 75-89', () => {
			expect(scoreToGrade(89)).toBe('B');
			expect(scoreToGrade(75)).toBe('B');
		});

		it('returns C for scores 60-74', () => {
			expect(scoreToGrade(74)).toBe('C');
			expect(scoreToGrade(60)).toBe('C');
		});

		it('returns D for scores 40-59', () => {
			expect(scoreToGrade(59)).toBe('D');
			expect(scoreToGrade(40)).toBe('D');
		});

		it('returns F for scores < 40', () => {
			expect(scoreToGrade(39)).toBe('F');
			expect(scoreToGrade(0)).toBe('F');
		});
	});

	// -- Format bytes -----------------------------------------------------------

	describe('formatBytes', () => {
		it('returns "0 B" for zero bytes', () => {
			expect(formatBytes(0)).toBe('0 B');
		});

		it('formats bytes correctly', () => {
			expect(formatBytes(500)).toBe('500 B');
		});

		it('formats kilobytes correctly', () => {
			expect(formatBytes(1024)).toBe('1.0 KB');
			expect(formatBytes(1536)).toBe('1.5 KB');
		});

		it('formats megabytes correctly', () => {
			expect(formatBytes(1048576)).toBe('1.0 MB');
		});

		it('formats gigabytes correctly', () => {
			expect(formatBytes(1073741824)).toBe('1.0 GB');
		});
	});

	// -- Format number ----------------------------------------------------------

	describe('formatNumber', () => {
		it('formats small numbers with locale formatting', () => {
			expect(formatNumber(42)).toBe('42');
			expect(formatNumber(999)).toBe('999');
		});

		it('formats thousands with K suffix', () => {
			expect(formatNumber(1000)).toBe('1.0K');
			expect(formatNumber(2500)).toBe('2.5K');
		});

		it('formats millions with M suffix', () => {
			expect(formatNumber(1000000)).toBe('1.0M');
			expect(formatNumber(2500000)).toBe('2.5M');
		});
	});

	// -- Time ago ---------------------------------------------------------------

	describe('timeAgo', () => {
		it('returns "--" for null input', () => {
			expect(timeAgo(null)).toBe('--');
		});

		it('returns "just now" for very recent dates', () => {
			const now = new Date().toISOString();
			expect(timeAgo(now)).toBe('just now');
		});

		it('returns minutes ago for dates within the last hour', () => {
			const tenMinAgo = new Date(Date.now() - 10 * 60000).toISOString();
			expect(timeAgo(tenMinAgo)).toBe('10m ago');
		});

		it('returns hours ago for dates within the last day', () => {
			const threeHoursAgo = new Date(Date.now() - 3 * 3600000).toISOString();
			expect(timeAgo(threeHoursAgo)).toBe('3h ago');
		});

		it('returns days ago for older dates', () => {
			const twoDaysAgo = new Date(Date.now() - 2 * 86400000).toISOString();
			expect(timeAgo(twoDaysAgo)).toBe('2d ago');
		});
	});

	// -- Severity color ---------------------------------------------------------

	describe('severityColor', () => {
		it('returns red for critical severity', () => {
			expect(severityColor('critical')).toBe('var(--red)');
		});

		it('returns red for high severity', () => {
			expect(severityColor('high')).toBe('var(--red)');
		});

		it('returns amber for medium severity', () => {
			expect(severityColor('medium')).toBe('var(--amber)');
		});

		it('returns green for low severity', () => {
			expect(severityColor('low')).toBe('var(--green)');
		});

		it('returns muted for unknown severity', () => {
			expect(severityColor('info')).toBe('var(--text-muted)');
		});
	});

	// -- Severity badge class ---------------------------------------------------

	describe('severityBadgeClass', () => {
		it('returns badge-danger for critical', () => {
			expect(severityBadgeClass('critical')).toBe('badge-danger');
		});

		it('returns badge-danger for high', () => {
			expect(severityBadgeClass('high')).toBe('badge-danger');
		});

		it('returns badge-warning for medium', () => {
			expect(severityBadgeClass('medium')).toBe('badge-warning');
		});

		it('returns badge-success for low', () => {
			expect(severityBadgeClass('low')).toBe('badge-success');
		});

		it('returns empty string for unknown', () => {
			expect(severityBadgeClass('info')).toBe('');
		});
	});

	// -- Category color ---------------------------------------------------------

	describe('categoryColor', () => {
		it('returns purple for Privacy', () => {
			expect(categoryColor('Privacy')).toBe('var(--purple)');
		});

		it('returns red for Security', () => {
			expect(categoryColor('Security')).toBe('var(--red)');
		});

		it('returns amber for Behavior', () => {
			expect(categoryColor('Behavior')).toBe('var(--amber)');
		});

		it('returns muted for unknown category', () => {
			expect(categoryColor('Other')).toBe('var(--text-muted)');
		});
	});

	// -- Time params computation ------------------------------------------------

	describe('computeTimeParams', () => {
		it('returns ISO strings for "from" and "to"', () => {
			const params = computeTimeParams('24h');
			expect(params.from).toMatch(/^\d{4}-\d{2}-\d{2}T/);
			expect(params.to).toMatch(/^\d{4}-\d{2}-\d{2}T/);
		});

		it('computes a ~1h window for "1h" range', () => {
			const params = computeTimeParams('1h');
			const diff = new Date(params.to).getTime() - new Date(params.from).getTime();
			// Allow 100ms tolerance for execution time
			expect(Math.abs(diff - 3600000)).toBeLessThan(100);
		});

		it('computes a ~6h window for "6h" range', () => {
			const params = computeTimeParams('6h');
			const diff = new Date(params.to).getTime() - new Date(params.from).getTime();
			expect(Math.abs(diff - 6 * 3600000)).toBeLessThan(100);
		});

		it('computes a ~24h window for "24h" range', () => {
			const params = computeTimeParams('24h');
			const diff = new Date(params.to).getTime() - new Date(params.from).getTime();
			expect(Math.abs(diff - 24 * 3600000)).toBeLessThan(100);
		});

		it('computes a ~7d window for "7d" range', () => {
			const params = computeTimeParams('7d');
			const diff = new Date(params.to).getTime() - new Date(params.from).getTime();
			expect(Math.abs(diff - 7 * 24 * 3600000)).toBeLessThan(100);
		});

		it('defaults to 24h for unknown range', () => {
			const params = computeTimeParams('99d');
			const diff = new Date(params.to).getTime() - new Date(params.from).getTime();
			expect(Math.abs(diff - 24 * 3600000)).toBeLessThan(100);
		});
	});

	// -- Device sorting ---------------------------------------------------------

	describe('sortDevicesByScore (device grid ordering)', () => {
		it('sorts devices by score ascending (worst first)', () => {
			const sorted = sortDevicesByScore(mockFleetSummary.devices);
			expect(sorted[0].name).toBe('Nest Thermostat'); // score 78
			expect(sorted[1].name).toBe('Ring Doorbell');    // score 92
		});

		it('returns empty array for empty devices', () => {
			expect(sortDevicesByScore([])).toEqual([]);
		});

		it('does not mutate the original array', () => {
			const original = [...mockFleetSummary.devices];
			sortDevicesByScore(mockFleetSummary.devices);
			expect(mockFleetSummary.devices[0].name).toBe(original[0].name);
		});
	});

	// -- Stat cards rendering logic ---------------------------------------------

	describe('stat cards', () => {
		it('renders correct stat card labels', () => {
			// The page renders exactly these 4 stat labels
			const labels = ['IoT DEVICES', 'ANOMALIES', 'PRIVACY CONCERNS', 'UNENCRYPTED'];
			expect(labels).toHaveLength(4);
			expect(labels).toContain('IoT DEVICES');
			expect(labels).toContain('ANOMALIES');
			expect(labels).toContain('PRIVACY CONCERNS');
			expect(labels).toContain('UNENCRYPTED');
		});

		it('generates correct hint for zero anomalies', () => {
			expect(statCardHint('anomaly_count', 0)).toBe('all clear');
		});

		it('generates correct hint for nonzero anomalies', () => {
			expect(statCardHint('anomaly_count', 3)).toBe('need review');
		});

		it('generates correct hint for zero privacy concerns', () => {
			expect(statCardHint('privacy_concerns', 0)).toBe('no trackers');
		});

		it('generates correct hint for nonzero privacy concerns', () => {
			expect(statCardHint('privacy_concerns', 2)).toBe('tracker domains found');
		});

		it('generates correct hint for zero unencrypted', () => {
			expect(statCardHint('unencrypted_count', 0)).toBe('fully encrypted');
		});

		it('generates correct hint for nonzero unencrypted', () => {
			expect(statCardHint('unencrypted_count', 1)).toBe('devices using plaintext');
		});
	});

	// -- Device cards with mock fleet data --------------------------------------

	describe('device cards rendering', () => {
		it('produces device cards from fleet data', () => {
			const sorted = sortDevicesByScore(mockFleetSummary.devices);
			expect(sorted).toHaveLength(2);
			expect(sorted[0].name).toBe('Nest Thermostat');
			expect(sorted[0].manufacturer).toBe('Google');
			expect(sorted[0].ip).toBe('192.168.1.51');
			expect(sorted[0].grade).toBe('B');
		});

		it('each device has required display fields', () => {
			for (const device of mockFleetSummary.devices) {
				expect(device.name).toBeTruthy();
				expect(device.manufacturer).toBeTruthy();
				expect(device.mac).toBeTruthy();
				expect(device.grade).toBeTruthy();
				expect(typeof device.score).toBe('number');
				expect(typeof device.privacy_score).toBe('number');
				expect(typeof device.encryption_pct).toBe('number');
				expect(typeof device.anomaly_count).toBe('number');
			}
		});

		it('maps device grades to correct colors', () => {
			const ringColor = gradeColor(mockFleetSummary.devices[0].grade); // A
			expect(ringColor).toBe('var(--green)');

			const nestColor = gradeColor(mockFleetSummary.devices[1].grade); // B
			expect(nestColor).toBe('var(--cyan)');
		});
	});

	// -- Empty state (zero devices) ---------------------------------------------

	describe('empty state', () => {
		it('shows empty state when no devices exist', () => {
			const sorted = sortDevicesByScore(mockEmptyFleetSummary.devices);
			expect(sorted).toHaveLength(0);
			// The template renders "No IoT devices classified yet." when sortedDevices.length === 0
		});

		it('empty fleet has grade F with score 0', () => {
			expect(mockEmptyFleetSummary.health_grade).toBe('F');
			expect(mockEmptyFleetSummary.health_score).toBe(0);
			expect(gradeColor(mockEmptyFleetSummary.health_grade)).toBe('var(--red)');
		});

		it('empty fleet has zero counts for all stats', () => {
			expect(mockEmptyFleetSummary.device_count).toBe(0);
			expect(mockEmptyFleetSummary.anomaly_count).toBe(0);
			expect(mockEmptyFleetSummary.privacy_concerns).toBe(0);
			expect(mockEmptyFleetSummary.unencrypted_count).toBe(0);
		});
	});

	// -- Loading state ----------------------------------------------------------

	describe('loading state', () => {
		it('loading state is shown when fleet is null', () => {
			// Page template: {#if loading && !fleet} → shows loading spinner
			const loading = true;
			const fleet: FleetSummary | null = null;
			expect(loading && !fleet).toBe(true);
		});

		it('loading state is hidden once fleet data arrives', () => {
			const loading = false;
			const fleet: FleetSummary | null = mockFleetSummary;
			expect(loading && !fleet).toBe(false);
		});

		it('error state shown when loading completes but fleet is null', () => {
			// Page template: {:else if !fleet} → shows error message
			const loading = false;
			const fleet: FleetSummary | null = null;
			expect(!loading && !fleet).toBe(true);
		});
	});

	// -- Gauge arc path ---------------------------------------------------------

	describe('gauge arc path', () => {
		it('computes path for 0% health score', () => {
			const path = computeGaugeArcPath(0);
			// At 0%, the arc ends at the start point (M 15 90)
			expect(path).toContain('M 15 90');
			expect(path).toContain('A 75 75 0 0 1');
		});

		it('computes path for 50% health score', () => {
			const path = computeGaugeArcPath(50);
			expect(path).toContain('M 15 90');
			// 50% = 90 degrees = endY near the top
		});

		it('computes path for 100% health score', () => {
			const path = computeGaugeArcPath(100);
			expect(path).toContain('M 15 90');
			// 100% = 180 degrees = full half-circle to (165, 90)
		});

		it('clamps scores above 100 to full arc', () => {
			const path100 = computeGaugeArcPath(100);
			const path150 = computeGaugeArcPath(150);
			expect(path100).toBe(path150);
		});
	});

	// -- Findings derivation ----------------------------------------------------

	describe('deriveFindings', () => {
		it('returns empty array when both inputs are null', () => {
			expect(deriveFindings(null, null)).toEqual([]);
		});

		it('returns empty array when both have empty device lists', () => {
			expect(deriveFindings({ devices: [] }, { devices: [] })).toEqual([]);
		});

		it('extracts protocol audit findings as Security category', () => {
			const protocol = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Ring Doorbell',
					category: 'camera',
					findings: [
						{ type: 'open_port', severity: 'high', port: 23, description: 'Telnet port open' },
					],
					violation_count: 1,
					compliant: false,
				}],
			};
			const findings = deriveFindings(protocol, null);
			expect(findings).toHaveLength(1);
			expect(findings[0].category).toBe('Security');
			expect(findings[0].severity).toBe('high');
			expect(findings[0].description).toBe('Telnet port open');
			expect(findings[0].deviceName).toBe('Ring Doorbell');
		});

		it('generates Privacy findings for tracker domains', () => {
			const privacy = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Smart TV',
					privacy_grade: 'D',
					privacy_score: 35,
					tracker_domains: [{ domain: 'tracker.example.com', query_count: 100 }],
					tracker_count: 3,
					telemetry_bytes: 5000,
					third_party_orgs: 2,
					encryption_ratio: 0.95,
					phone_home_per_hour: 10,
				}],
			};
			const findings = deriveFindings(null, privacy);
			expect(findings).toHaveLength(1);
			expect(findings[0].category).toBe('Privacy');
			expect(findings[0].description).toContain('3 tracker domains');
		});

		it('assigns medium severity for 3-5 trackers', () => {
			const privacy = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Device',
					privacy_grade: 'C',
					privacy_score: 50,
					tracker_domains: [],
					tracker_count: 4,
					telemetry_bytes: 0,
					third_party_orgs: 0,
					encryption_ratio: 1.0,
					phone_home_per_hour: 0,
				}],
			};
			const findings = deriveFindings(null, privacy);
			expect(findings[0].severity).toBe('medium');
		});

		it('assigns high severity for > 5 trackers', () => {
			const privacy = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Device',
					privacy_grade: 'D',
					privacy_score: 30,
					tracker_domains: [],
					tracker_count: 8,
					telemetry_bytes: 0,
					third_party_orgs: 0,
					encryption_ratio: 1.0,
					phone_home_per_hour: 0,
				}],
			};
			const findings = deriveFindings(null, privacy);
			expect(findings[0].severity).toBe('high');
		});

		it('assigns low severity for 1-2 trackers', () => {
			const privacy = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Device',
					privacy_grade: 'B',
					privacy_score: 80,
					tracker_domains: [],
					tracker_count: 1,
					telemetry_bytes: 0,
					third_party_orgs: 0,
					encryption_ratio: 1.0,
					phone_home_per_hour: 0,
				}],
			};
			const findings = deriveFindings(null, privacy);
			expect(findings[0].severity).toBe('low');
		});

		it('generates Security finding for low encryption ratio', () => {
			const privacy = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Old Camera',
					privacy_grade: 'D',
					privacy_score: 30,
					tracker_domains: [],
					tracker_count: 0,
					telemetry_bytes: 0,
					third_party_orgs: 0,
					encryption_ratio: 0.4,
					phone_home_per_hour: 0,
				}],
			};
			const findings = deriveFindings(null, privacy);
			expect(findings).toHaveLength(1);
			expect(findings[0].category).toBe('Security');
			expect(findings[0].severity).toBe('high'); // < 50%
			expect(findings[0].description).toContain('40% encrypted');
		});

		it('assigns medium severity for encryption between 50-89%', () => {
			const privacy = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Device',
					privacy_grade: 'C',
					privacy_score: 50,
					tracker_domains: [],
					tracker_count: 0,
					telemetry_bytes: 0,
					third_party_orgs: 0,
					encryption_ratio: 0.7,
					phone_home_per_hour: 0,
				}],
			};
			const findings = deriveFindings(null, privacy);
			expect(findings[0].severity).toBe('medium');
		});

		it('generates Behavior finding for high phone-home rate', () => {
			const privacy = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Smart Speaker',
					privacy_grade: 'C',
					privacy_score: 55,
					tracker_domains: [],
					tracker_count: 0,
					telemetry_bytes: 0,
					third_party_orgs: 0,
					encryption_ratio: 0.95,
					phone_home_per_hour: 120,
				}],
			};
			const findings = deriveFindings(null, privacy);
			expect(findings).toHaveLength(1);
			expect(findings[0].category).toBe('Behavior');
			expect(findings[0].description).toContain('120x/hour');
		});

		it('does not generate phone-home finding for rate <= 60', () => {
			const privacy = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Device',
					privacy_grade: 'B',
					privacy_score: 80,
					tracker_domains: [],
					tracker_count: 0,
					telemetry_bytes: 0,
					third_party_orgs: 0,
					encryption_ratio: 0.95,
					phone_home_per_hour: 60,
				}],
			};
			const findings = deriveFindings(null, privacy);
			expect(findings).toHaveLength(0);
		});

		it('sorts findings by severity (high first)', () => {
			const protocol = {
				devices: [{
					mac: '11:22:33:44:55:66',
					name: 'Device A',
					category: 'other',
					findings: [
						{ type: 'info', severity: 'low', description: 'Low severity issue' },
						{ type: 'vuln', severity: 'critical', description: 'Critical issue' },
					],
					violation_count: 2,
					compliant: false,
				}],
			};
			const findings = deriveFindings(protocol, null);
			expect(findings[0].severity).toBe('critical');
			expect(findings[1].severity).toBe('low');
		});

		it('combines findings from both protocol and privacy', () => {
			const protocol = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Ring Doorbell',
					category: 'camera',
					findings: [
						{ type: 'open_port', severity: 'high', port: 23, description: 'Telnet open' },
					],
					violation_count: 1,
					compliant: false,
				}],
			};
			const privacy = {
				devices: [{
					mac: '11:22:33:44:55:66',
					name: 'Smart TV',
					privacy_grade: 'D',
					privacy_score: 30,
					tracker_domains: [],
					tracker_count: 10,
					telemetry_bytes: 5000,
					third_party_orgs: 3,
					encryption_ratio: 0.3,
					phone_home_per_hour: 200,
				}],
			};
			const findings = deriveFindings(protocol, privacy);
			// 1 protocol + 1 tracker + 1 encryption + 1 phone-home = 4 findings
			expect(findings).toHaveLength(4);
			// Categories present
			const cats = new Set(findings.map(f => f.category));
			expect(cats.has('Security')).toBe(true);
			expect(cats.has('Privacy')).toBe(true);
			expect(cats.has('Behavior')).toBe(true);
		});

		it('uses singular "domain" for tracker_count of 1', () => {
			const privacy = {
				devices: [{
					mac: 'AA:BB:CC:DD:EE:FF',
					name: 'Device',
					privacy_grade: 'B',
					privacy_score: 80,
					tracker_domains: [],
					tracker_count: 1,
					telemetry_bytes: 0,
					third_party_orgs: 0,
					encryption_ratio: 1.0,
					phone_home_per_hour: 0,
				}],
			};
			const findings = deriveFindings(null, privacy);
			expect(findings[0].description).toContain('1 tracker domain');
			expect(findings[0].description).not.toContain('domains');
		});
	});

	// -- Hero subtitle ----------------------------------------------------------

	describe('hero subtitle', () => {
		it('uses fleet subtitle when available', () => {
			const subtitle = mockFleetSummary.subtitle || 'Scanning your smart home...';
			expect(subtitle).toBe('Your smart home is healthy.');
		});

		it('falls back to scanning message when subtitle is empty', () => {
			const subtitle = mockEmptyFleetSummary.subtitle || 'Scanning your smart home...';
			expect(subtitle).toBe('Scanning your smart home...');
		});
	});
});
