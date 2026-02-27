import { describe, it, expect } from 'vitest';

/**
 * Tests for Compliance page scoring logic.
 *
 * The compliance/+page.svelte component uses Svelte 5 runes ($derived, $state)
 * and several API imports that are difficult to fully render in a jsdom test
 * environment.  Instead we extract and test the pure scoring logic that lives
 * inside the component: encryption score, DNS score, alert response score,
 * overall weighted grade computation, category status badges, and grade
 * letter assignment.
 */

// ---------------------------------------------------------------------------
// Reproduced types and constants from compliance/+page.svelte
// ---------------------------------------------------------------------------

interface ServiceEntry {
	name: string;
	count: number;
}

const WEIGHTS = {
	encryption: 0.25,
	dns: 0.15,
	network: 0.15,
	patch: 0.15,
	alerts: 0.15,
	monitoring: 0.15,
};

// ---------------------------------------------------------------------------
// Reproduced pure scoring logic from compliance/+page.svelte
// ---------------------------------------------------------------------------

/** Compute encryption score — mirrors encryptionScore $derived */
function computeEncryptionScore(services: ServiceEntry[]): number {
	if (services.length === 0) return 100;

	const totalConnections = services.reduce((sum, s) => sum + s.count, 0);
	if (totalConnections === 0) return 100;

	const encryptedNames = [
		'ssl', 'tls', 'https', 'imaps', 'smtps', 'ldaps', 'ftps', 'ssh',
		'dns_over_tls', 'dns_over_https',
	];
	const encryptedCount = services
		.filter((s) => encryptedNames.some((n) => s.name.toLowerCase().includes(n)))
		.reduce((sum, s) => sum + s.count, 0);

	return Math.round((encryptedCount / totalConnections) * 100);
}

/** Compute DNS score — mirrors dnsScore $derived */
function computeDnsScore(services: ServiceEntry[]): number {
	if (services.length === 0) return 100;

	const totalDns = services
		.filter((s) => s.name.toLowerCase().includes('dns'))
		.reduce((sum, s) => sum + s.count, 0);
	if (totalDns === 0) return 100;

	const plainDns = services
		.filter((s) => s.name.toLowerCase() === 'dns')
		.reduce((sum, s) => sum + s.count, 0);

	return Math.round(100 - (plainDns / totalDns) * 100);
}

/** Compute network segmentation score — mirrors networkScore $derived */
function computeNetworkScore(totalDevices: number, devicesWithRisk: number): number {
	if (totalDevices === 0) return 100;
	const unbaselined = totalDevices - devicesWithRisk;
	const penalty = unbaselined * 10;
	return Math.max(0, 100 - penalty);
}

/** Compute patch/currency score — mirrors patchScore $derived */
function computePatchScore(services: ServiceEntry[]): number {
	if (services.length === 0) return 100;

	const legacyProtocols = ['http', 'ftp', 'telnet', 'pop3', 'imap'];
	const totalConnections = services.reduce((sum, s) => sum + s.count, 0);
	if (totalConnections === 0) return 100;

	const legacyCount = services
		.filter((s) => legacyProtocols.some((lp) => s.name.toLowerCase() === lp))
		.reduce((sum, s) => sum + s.count, 0);

	return Math.round(100 - (legacyCount / totalConnections) * 100);
}

/** Compute alert response score — mirrors alertScore $derived */
function computeAlertScore(
	totalAlerts: number,
	resolvedInvestigations: number,
	totalInvestigations: number
): number {
	if (totalAlerts === 0) return 100;
	if (totalInvestigations === 0) return 0;
	return Math.min(100, Math.round((resolvedInvestigations / totalInvestigations) * 100));
}

/** Compute monitoring coverage score — mirrors monitoringScore $derived */
function computeMonitoringScore(totalDevices: number, devicesWithRisk: number): number {
	if (totalDevices === 0) return 100;
	return Math.round((devicesWithRisk / totalDevices) * 100);
}

/** Compute overall weighted score — mirrors overallScore $derived */
function computeOverallScore(
	encryption: number,
	dns: number,
	network: number,
	patch: number,
	alerts: number,
	monitoring: number
): number {
	return Math.round(
		encryption * WEIGHTS.encryption +
		dns * WEIGHTS.dns +
		network * WEIGHTS.network +
		patch * WEIGHTS.patch +
		alerts * WEIGHTS.alerts +
		monitoring * WEIGHTS.monitoring
	);
}

/** Map score to letter grade — mirrors overallGrade $derived */
function computeGrade(score: number): string {
	if (score >= 90) return 'A';
	if (score >= 80) return 'B';
	if (score >= 70) return 'C';
	if (score >= 60) return 'D';
	return 'F';
}

/** Map score to grade color class — mirrors gradeColorClass $derived */
function computeGradeColorClass(score: number): string {
	if (score >= 90) return 'grade-a';
	if (score >= 80) return 'grade-b';
	if (score >= 70) return 'grade-c';
	return 'grade-df';
}

/** Map category score to status label — mirrors getStatus() */
function getStatus(score: number): 'Good' | 'Needs Attention' | 'Poor' {
	if (score >= 80) return 'Good';
	if (score >= 50) return 'Needs Attention';
	return 'Poor';
}

/** Map category score to badge CSS class — mirrors getStatusClass() */
function getStatusClass(score: number): string {
	if (score >= 80) return 'badge-success';
	if (score >= 50) return 'badge-warning';
	return 'badge-danger';
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Compliance scoring logic', () => {
	// -- computeEncryptionScore -----------------------------------------------

	describe('computeEncryptionScore', () => {
		it('returns 100 for empty services list', () => {
			expect(computeEncryptionScore([])).toBe(100);
		});

		it('returns 100 when all services are zero count', () => {
			expect(computeEncryptionScore([{ name: 'http', count: 0 }])).toBe(100);
		});

		it('returns 100 when all traffic is encrypted', () => {
			const services = [
				{ name: 'https', count: 500 },
				{ name: 'ssh', count: 100 },
			];
			expect(computeEncryptionScore(services)).toBe(100);
		});

		it('returns 0 when no traffic is encrypted', () => {
			const services = [
				{ name: 'http', count: 500 },
				{ name: 'ftp', count: 100 },
			];
			expect(computeEncryptionScore(services)).toBe(0);
		});

		it('returns correct percentage for mixed traffic', () => {
			const services = [
				{ name: 'https', count: 75 },
				{ name: 'http', count: 25 },
			];
			expect(computeEncryptionScore(services)).toBe(75);
		});

		it('recognizes ssl as encrypted', () => {
			const services = [{ name: 'ssl', count: 100 }];
			expect(computeEncryptionScore(services)).toBe(100);
		});

		it('recognizes dns_over_tls as encrypted', () => {
			const services = [
				{ name: 'dns_over_tls', count: 50 },
				{ name: 'dns', count: 50 },
			];
			expect(computeEncryptionScore(services)).toBe(50);
		});

		it('is case-insensitive for service name matching', () => {
			const services = [
				{ name: 'HTTPS', count: 100 },
				{ name: 'HTTP', count: 100 },
			];
			expect(computeEncryptionScore(services)).toBe(50);
		});
	});

	// -- computeDnsScore ------------------------------------------------------

	describe('computeDnsScore', () => {
		it('returns 100 for empty services list', () => {
			expect(computeDnsScore([])).toBe(100);
		});

		it('returns 100 when no DNS traffic exists', () => {
			const services = [
				{ name: 'http', count: 200 },
				{ name: 'https', count: 300 },
			];
			expect(computeDnsScore(services)).toBe(100);
		});

		it('returns 0 when all DNS is plain text', () => {
			const services = [{ name: 'dns', count: 1000 }];
			expect(computeDnsScore(services)).toBe(0);
		});

		it('returns 100 when all DNS is encrypted', () => {
			const services = [{ name: 'dns_over_https', count: 500 }];
			expect(computeDnsScore(services)).toBe(100);
		});

		it('returns correct percentage for mixed DNS traffic', () => {
			const services = [
				{ name: 'dns', count: 40 },
				{ name: 'dns_over_tls', count: 60 },
			];
			// totalDns = 100, plainDns = 40, score = 100 - 40% = 60
			expect(computeDnsScore(services)).toBe(60);
		});

		it('handles DNS traffic alongside non-DNS services', () => {
			const services = [
				{ name: 'http', count: 1000 },
				{ name: 'dns', count: 50 },
				{ name: 'dns_over_https', count: 50 },
			];
			// Only DNS services count: totalDns = 100, plainDns = 50, score = 50
			expect(computeDnsScore(services)).toBe(50);
		});
	});

	// -- computeNetworkScore --------------------------------------------------

	describe('computeNetworkScore', () => {
		it('returns 100 when no devices exist', () => {
			expect(computeNetworkScore(0, 0)).toBe(100);
		});

		it('returns 100 when all devices are baselined', () => {
			expect(computeNetworkScore(5, 5)).toBe(100);
		});

		it('penalizes 10 points per unbaselined device', () => {
			expect(computeNetworkScore(5, 3)).toBe(80);
		});

		it('clamps to minimum of 0', () => {
			expect(computeNetworkScore(20, 0)).toBe(0);
		});

		it('handles one unbaselined device', () => {
			expect(computeNetworkScore(10, 9)).toBe(90);
		});
	});

	// -- computeAlertScore ----------------------------------------------------

	describe('computeAlertScore', () => {
		it('returns 100 when there are no alerts', () => {
			expect(computeAlertScore(0, 0, 0)).toBe(100);
		});

		it('returns 0 when alerts exist but no investigations', () => {
			expect(computeAlertScore(50, 0, 0)).toBe(0);
		});

		it('returns 100 when all investigations are resolved', () => {
			expect(computeAlertScore(20, 10, 10)).toBe(100);
		});

		it('returns correct percentage for partial resolution', () => {
			expect(computeAlertScore(50, 3, 10)).toBe(30);
		});

		it('caps at 100 even if resolved exceeds total', () => {
			expect(computeAlertScore(10, 15, 10)).toBe(100);
		});
	});

	// -- computePatchScore ----------------------------------------------------

	describe('computePatchScore', () => {
		it('returns 100 for empty services', () => {
			expect(computePatchScore([])).toBe(100);
		});

		it('returns 100 when no legacy protocols are used', () => {
			const services = [
				{ name: 'https', count: 500 },
				{ name: 'ssh', count: 200 },
			];
			expect(computePatchScore(services)).toBe(100);
		});

		it('returns 0 when all traffic uses legacy protocols', () => {
			const services = [
				{ name: 'http', count: 50 },
				{ name: 'ftp', count: 50 },
			];
			expect(computePatchScore(services)).toBe(0);
		});

		it('detects telnet as a legacy protocol', () => {
			const services = [
				{ name: 'telnet', count: 10 },
				{ name: 'ssh', count: 90 },
			];
			expect(computePatchScore(services)).toBe(90);
		});
	});

	// -- computeMonitoringScore -----------------------------------------------

	describe('computeMonitoringScore', () => {
		it('returns 100 when no devices exist', () => {
			expect(computeMonitoringScore(0, 0)).toBe(100);
		});

		it('returns 100 when all devices have risk scores', () => {
			expect(computeMonitoringScore(10, 10)).toBe(100);
		});

		it('returns 0 when no devices have risk scores', () => {
			expect(computeMonitoringScore(10, 0)).toBe(0);
		});

		it('returns correct percentage for partial coverage', () => {
			expect(computeMonitoringScore(10, 7)).toBe(70);
		});
	});

	// -- computeOverallScore --------------------------------------------------

	describe('computeOverallScore', () => {
		it('returns 100 when all categories score 100', () => {
			expect(computeOverallScore(100, 100, 100, 100, 100, 100)).toBe(100);
		});

		it('returns 0 when all categories score 0', () => {
			expect(computeOverallScore(0, 0, 0, 0, 0, 0)).toBe(0);
		});

		it('correctly applies weights', () => {
			// encryption=100*0.25 + dns=0*0.15 + network=0*0.15 + patch=0*0.15 + alerts=0*0.15 + monitoring=0*0.15
			expect(computeOverallScore(100, 0, 0, 0, 0, 0)).toBe(25);
		});

		it('computes weighted average correctly for mixed scores', () => {
			// 80*0.25 + 60*0.15 + 90*0.15 + 70*0.15 + 50*0.15 + 100*0.15
			// = 20 + 9 + 13.5 + 10.5 + 7.5 + 15 = 75.5 => 76
			expect(computeOverallScore(80, 60, 90, 70, 50, 100)).toBe(76);
		});
	});

	// -- computeGrade ---------------------------------------------------------

	describe('computeGrade', () => {
		it('returns A for score 90', () => {
			expect(computeGrade(90)).toBe('A');
		});

		it('returns A for score 100', () => {
			expect(computeGrade(100)).toBe('A');
		});

		it('returns B for score 80', () => {
			expect(computeGrade(80)).toBe('B');
		});

		it('returns B for score 89', () => {
			expect(computeGrade(89)).toBe('B');
		});

		it('returns C for score 70', () => {
			expect(computeGrade(70)).toBe('C');
		});

		it('returns D for score 60', () => {
			expect(computeGrade(60)).toBe('D');
		});

		it('returns F for score 59', () => {
			expect(computeGrade(59)).toBe('F');
		});

		it('returns F for score 0', () => {
			expect(computeGrade(0)).toBe('F');
		});
	});

	// -- computeGradeColorClass -----------------------------------------------

	describe('computeGradeColorClass', () => {
		it('returns grade-a for scores >= 90', () => {
			expect(computeGradeColorClass(95)).toBe('grade-a');
		});

		it('returns grade-b for scores 80-89', () => {
			expect(computeGradeColorClass(85)).toBe('grade-b');
		});

		it('returns grade-c for scores 70-79', () => {
			expect(computeGradeColorClass(75)).toBe('grade-c');
		});

		it('returns grade-df for scores below 70', () => {
			expect(computeGradeColorClass(65)).toBe('grade-df');
		});

		it('returns grade-df for score 0', () => {
			expect(computeGradeColorClass(0)).toBe('grade-df');
		});
	});

	// -- getStatus ------------------------------------------------------------

	describe('getStatus', () => {
		it('returns Good for score 80', () => {
			expect(getStatus(80)).toBe('Good');
		});

		it('returns Good for score 100', () => {
			expect(getStatus(100)).toBe('Good');
		});

		it('returns Needs Attention for score 50', () => {
			expect(getStatus(50)).toBe('Needs Attention');
		});

		it('returns Needs Attention for score 79', () => {
			expect(getStatus(79)).toBe('Needs Attention');
		});

		it('returns Poor for score 49', () => {
			expect(getStatus(49)).toBe('Poor');
		});

		it('returns Poor for score 0', () => {
			expect(getStatus(0)).toBe('Poor');
		});
	});

	// -- getStatusClass -------------------------------------------------------

	describe('getStatusClass', () => {
		it('returns badge-success for score >= 80', () => {
			expect(getStatusClass(90)).toBe('badge-success');
		});

		it('returns badge-warning for score 50-79', () => {
			expect(getStatusClass(65)).toBe('badge-warning');
		});

		it('returns badge-danger for score < 50', () => {
			expect(getStatusClass(30)).toBe('badge-danger');
		});

		it('returns badge-success at the boundary (80)', () => {
			expect(getStatusClass(80)).toBe('badge-success');
		});

		it('returns badge-warning at the boundary (50)', () => {
			expect(getStatusClass(50)).toBe('badge-warning');
		});
	});
});
