/**
 * The Security posture scores (moved verbatim from routes/compliance/+page.svelte so the overview
 * and the category pages score the same way). Six categories from five requests; a category whose
 * request failed has no score, and one with nothing to score is "Not measured".
 */
import type { ProtocolsResponse } from '$api/traffic';
import type { AlertCountResponse } from '$api/alerts';
import type { DeviceCountResponse } from '$api/devices';
import type { RiskScoresResponse } from '$api/risk';
import type { InvestigationStats } from '$api/investigations';
import { nothingFound } from '$api/system';
import type { HealthCheck } from '$lib/utils/read-health';
import { fmt } from '$lib/utils/drilldown';

export const POSTURE_SLUGS = [
	'encryption',
	'dns-security',
	'network-segmentation',
	'patch-currency',
	'alert-response',
	'monitoring-coverage',
] as const;
export type PostureSlug = (typeof POSTURE_SLUGS)[number];
export const isPostureSlug = (value: string): value is PostureSlug => (POSTURE_SLUGS as readonly string[]).includes(value);

/** The page's five requests; a category built on one that failed has no score. */
export type Input = 'protocols' | 'alerts' | 'devices' | 'risk' | 'investigations';

export type CategoryStatus = 'Good' | 'Needs attention' | 'Poor' | "Couldn't compute" | 'Not measured';

export interface CategoryScore {
	slug: PostureSlug;
	name: string;
	icon: string;
	score: number | null;
	status: CategoryStatus;
	statusClass: string;
	/** The card's subtitle: what the score measures. */
	sub: string;
	description: string;
	findings: string[];
	needs: Input[];
	/** F5: its request worked but there was nothing to score; `score` then means nothing. */
	empty: boolean;
	/** Its share of the overall score (WEIGHTS). */
	weight: number;
}

export const INPUT_NAMES: Record<Input, string> = {
	protocols: 'traffic protocols',
	alerts: 'alert counts',
	devices: 'the device count',
	risk: 'risk scores',
	investigations: 'investigation stats',
};

export const WEIGHTS = {
	encryption: 0.25,
	dns: 0.15,
	network: 0.15,
	patch: 0.15,
	alerts: 0.15,
	monitoring: 0.15,
};

/** Patch currency's legacy services; keep in step with daemon/api/posture.py LEGACY_PROTOCOLS. */
export const LEGACY_PROTOCOLS = ['http', 'ftp', 'telnet', 'pop3', 'imap'] as const;

export interface PostureData {
	protocols: ProtocolsResponse;
	alertCounts: AlertCountResponse;
	deviceCount: DeviceCountResponse;
	riskScores: RiskScoresResponse;
	investigationStats: InvestigationStats;
}

export interface PostureInputs extends PostureData {
	/** Requests that failed; the stand-in defaults fill in for them only so the other scores compute. */
	failed: Input[];
	/** NET-228: the system health, for the pipeline state beside a zero */
	health: HealthCheck;
}

/** The overview's stand-ins before the first load (and for a request that failed). */
export const EMPTY_DATA: PostureData = {
	protocols: { from: '', to: '', protocols: [], services: [] },
	alertCounts: { from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } },
	deviceCount: { from: '', to: '', count: 0 },
	riskScores: { scores: [] },
	investigationStats: { total: 0, by_status: {}, by_severity: {} },
};

export function getStatus(score: number): 'Good' | 'Needs attention' | 'Poor' {
	if (score >= 80) return 'Good';
	if (score >= 50) return 'Needs attention';
	return 'Poor';
}

/** The status chip: the word always shows; the tint only backs it up. */
export function getStatusClass(score: number): string {
	if (score >= 80) return 'is-ok';
	if (score >= 50) return 'is-warn';
	return 'is-bad';
}

/** Patch currency's numerator and denominator, as the score counts them: service labels, so a
 * connection Zeek gave two labels counts once per label. `byName` holds each legacy name's count. */
export function legacyCounts(services: readonly { name: string; count: number }[]): {
	legacy: number;
	total: number;
	byName: Record<string, number>;
} {
	const byName: Record<string, number> = {};
	for (const lp of LEGACY_PROTOCOLS) {
		byName[lp] = services.filter((s) => s.name.toLowerCase() === lp).reduce((sum, s) => sum + s.count, 0);
	}
	return {
		legacy: Object.values(byName).reduce((sum, n) => sum + n, 0),
		total: services.reduce((sum, s) => sum + s.count, 0),
		byName,
	};
}

/** The six categories, scored from the five inputs, in the overview's order. */
export function scoreCategories(inputs: PostureInputs): CategoryScore[] {
	const { protocols, alertCounts, deviceCount, riskScores, investigationStats, failed, health } = inputs;
	const services = protocols.services;

	// The daemon applies the IoT pages' encryption rule (#42) to the whole network
	const encrypted = protocols.encryption?.encrypted ?? 0;
	const encryptionEligible = protocols.encryption?.eligible ?? 0;
	const encryptionScore = encryptionEligible === 0 ? 100 : Math.round((encrypted / encryptionEligible) * 100);

	const plainDns = protocols.dns?.plain ?? 0;
	const dnsOverTls = protocols.dns?.over_tls ?? 0;
	const dnsScore = plainDns + dnsOverTls === 0 ? 100 : Math.round((dnsOverTls / (plainDns + dnsOverTls)) * 100);

	// Both are every device, by the same rules: the daemon scores each device /api/devices/count
	// counts. min() keeps coverage at most 100% if one crosses the threshold between the two requests.
	const totalDevices = deviceCount.count;
	const scoredDevices = Math.min(riskScores.scores.length, totalDevices);

	const networkScore = totalDevices === 0 ? 100 : Math.max(0, 100 - (totalDevices - scoredDevices) * 10);

	const legacy = legacyCounts(services);
	// Lower legacy usage => higher patch/currency score
	const patchScore = services.length === 0 || legacy.total === 0 ? 100 : Math.round(100 - (legacy.legacy / legacy.total) * 100);

	const resolvedOrClosed = (investigationStats.by_status['resolved'] ?? 0) + (investigationStats.by_status['closed'] ?? 0);
	const alertScore =
		alertCounts.counts.total === 0
			? 100
			: investigationStats.total === 0
				? 0
				: Math.min(100, Math.round((resolvedOrClosed / investigationStats.total) * 100));

	const monitoringScore = totalDevices === 0 ? 100 : Math.round((scoredDevices / totalDevices) * 100);

	function encryptionFindings(): string[] {
		const findings: string[] = [];
		const totalConnections = services.reduce((sum, s) => sum + s.count, 0);
		const httpCount = services.filter((s) => s.name.toLowerCase() === 'http').reduce((sum, s) => sum + s.count, 0);
		if (httpCount > 0) findings.push(`${fmt(httpCount)} unencrypted HTTP connections detected`);
		if (totalConnections > 0 && encryptionEligible > 0) {
			findings.push(`${fmt(encrypted)} of ${fmt(encryptionEligible)} connections encrypted (${encryptionScore}%)`);
		} else {
			findings.push('No traffic data available yet');
		}
		return findings;
	}

	function dnsFindings(): string[] {
		const findings: string[] = [];
		if (plainDns > 0) findings.push(`${fmt(plainDns)} plain-text DNS lookups observed`);
		if (dnsOverTls > 0) findings.push(`${fmt(dnsOverTls)} DNS-over-TLS connections`);
		if (plainDns === 0 && dnsOverTls === 0) {
			findings.push('No DNS traffic data available yet');
		} else if (dnsScore < 50) {
			findings.push('Consider enabling DNS-over-HTTPS or DNS-over-TLS on your router');
		}
		return findings;
	}

	function networkFindings(): string[] {
		const findings: string[] = [];
		const unbaselined = totalDevices - scoredDevices;
		findings.push(`${totalDevices} device(s) discovered on your network`);
		if (unbaselined > 0) {
			findings.push(`${unbaselined} device(s) not yet baselined`);
		} else if (totalDevices > 0) {
			findings.push('All devices have been baselined');
		}
		return findings;
	}

	function patchFindings(): string[] {
		const findings: string[] = [];
		for (const lp of LEGACY_PROTOCOLS) {
			const count = legacy.byName[lp];
			if (count > 0) findings.push(`${fmt(count)} ${lp.toUpperCase()} connections (consider upgrading to encrypted variant)`);
		}
		if (legacy.total === 0) {
			findings.push('No traffic data available yet');
		} else if (findings.length === 0) {
			findings.push('No legacy unencrypted protocols detected');
		}
		return findings;
	}

	function alertFindings(): string[] {
		const findings: string[] = [];
		const total = alertCounts.counts.total;
		if (total === 0) {
			const zero = nothingFound('No counted rule matches in this period', health.health, health.failed);
			findings.push(`${zero.title}, so there is nothing to score · ${zero.detail}`);
		} else {
			findings.push(`${fmt(total)} total alert(s) in the current period`);
			if (alertCounts.counts.high > 0) findings.push(`${alertCounts.counts.high} high-severity alert(s) require attention`);
			if (investigationStats.total > 0) findings.push(`${resolvedOrClosed} of ${investigationStats.total} investigation(s) resolved`);
		}
		return findings;
	}

	function monitoringFindings(): string[] {
		const findings: string[] = [];
		if (totalDevices === 0) {
			findings.push('No devices discovered yet');
		} else {
			findings.push(`${scoredDevices} of ${totalDevices} device(s) have risk scores computed`);
			const unscored = totalDevices - scoredDevices;
			if (unscored > 0) {
				findings.push(`${unscored} device(s) awaiting risk scoring`);
			} else {
				findings.push('All devices have been assessed for risk');
			}
		}
		return findings;
	}

	/** #96: a category whose input failed says so instead of scoring the stand-in defaults. */
	function withFailures(cats: CategoryScore[]): CategoryScore[] {
		return cats.map((cat) => {
			const missing = cat.needs.filter((n) => failed.includes(n));
			if (missing.length === 0) return cat;
			return {
				...cat,
				score: null,
				status: "Couldn't compute",
				statusClass: '',
				findings: [`Couldn't load ${missing.map((n) => INPUT_NAMES[n]).join(' or ')}: the request failed.`],
				// F5: the stand-in defaults look empty; a failed input is failed, not empty
				empty: false,
			};
		});
	}

	/** F5: a category with nothing to score is "Not measured", not a 100. */
	function withEmpty(cats: CategoryScore[]): CategoryScore[] {
		return cats.map((cat) => (cat.empty ? { ...cat, status: 'Not measured', statusClass: '' } : cat));
	}

	return withFailures(
		withEmpty([
			{
				slug: 'encryption',
				name: 'Encryption',
				sub: 'Percent of connections that can be encrypted · current period',
				icon: 'lock',
				score: encryptionScore,
				status: getStatus(encryptionScore),
				statusClass: getStatusClass(encryptionScore),
				description:
					'Share of connections that use encryption (TLS/HTTPS, QUIC, SSH, VPN). Local chatter that is never encrypted (DNS, DHCP, NTP, discovery, pings) is left out.',
				findings: encryptionFindings(),
				needs: ['protocols'],
				empty: encryptionEligible === 0,
				weight: WEIGHTS.encryption,
			},
			{
				slug: 'dns-security',
				name: 'DNS security',
				sub: 'Percent of DNS lookups sent over TLS · current period',
				icon: 'globe',
				score: dnsScore,
				status: getStatus(dnsScore),
				statusClass: getStatusClass(dnsScore),
				description:
					'Share of DNS lookups sent over DNS-over-TLS instead of plain text. DNS-over-HTTPS looks like any other HTTPS, so it is not counted.',
				findings: dnsFindings(),
				needs: ['protocols'],
				empty: plainDns + dnsOverTls === 0,
				weight: WEIGHTS.dns,
			},
			{
				slug: 'network-segmentation',
				name: 'Network segmentation',
				sub: '100, less 10 for each device not yet baselined',
				icon: 'layers',
				score: networkScore,
				status: getStatus(networkScore),
				statusClass: getStatusClass(networkScore),
				description: 'Whether all devices have been baselined and communicate with expected destinations.',
				findings: networkFindings(),
				needs: ['devices', 'risk'],
				empty: totalDevices === 0,
				weight: WEIGHTS.network,
			},
			{
				slug: 'patch-currency',
				name: 'Patch currency',
				sub: 'Percent of connections not on legacy protocols · current period',
				icon: 'refresh',
				score: patchScore,
				status: getStatus(patchScore),
				statusClass: getStatusClass(patchScore),
				description: 'Usage of modern protocol versions (TLS 1.3, HTTP/2+) vs legacy unencrypted protocols.',
				findings: patchFindings(),
				needs: ['protocols'],
				empty: legacy.total === 0,
				weight: WEIGHTS.patch,
			},
			{
				slug: 'alert-response',
				name: 'Alert response',
				sub: 'Percent of investigations resolved or closed',
				icon: 'bell-ring',
				score: alertScore,
				status: getStatus(alertScore),
				statusClass: getStatusClass(alertScore),
				description: 'How effectively alerts are being acknowledged and investigated.',
				findings: alertFindings(),
				// with no alerts the score is 100 whatever the investigations; with some it needs them
				needs: alertCounts.counts.total > 0 ? ['alerts', 'investigations'] : ['alerts'],
				empty: alertCounts.counts.total === 0,
				weight: WEIGHTS.alerts,
			},
			{
				slug: 'monitoring-coverage',
				name: 'Monitoring coverage',
				sub: 'Percent of devices with a risk score',
				icon: 'eye',
				score: monitoringScore,
				status: getStatus(monitoringScore),
				statusClass: getStatusClass(monitoringScore),
				description: 'Proportion of discovered devices that have been risk-scored and are actively monitored.',
				findings: monitoringFindings(),
				needs: ['devices', 'risk'],
				empty: totalDevices === 0,
				weight: WEIGHTS.monitoring,
			},
		]),
	);
}
