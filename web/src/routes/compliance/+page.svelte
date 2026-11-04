<script lang="ts">
	import { getProtocolDistribution } from '$api/traffic';
	import { getAlertCount } from '$api/alerts';
	// OLD CODE START — #96: the device list is its top 100 by bytes, not every device
	// import { getDevices } from '$api/devices';
	// OLD CODE END
	import { getDeviceCount } from '$api/devices';
	import { getRiskScores } from '$api/risk';
	import { getInvestigationStats } from '$api/investigations';
	import type { ProtocolsResponse } from '$api/traffic';
	import type { AlertCountResponse } from '$api/alerts';
	// OLD CODE START — #96: see the getDevices import
	// import type { DeviceListResponse } from '$api/devices';
	// OLD CODE END
	import type { DeviceCountResponse } from '$api/devices';
	import type { RiskScoresResponse } from '$api/risk';
	import type { InvestigationStats } from '$api/investigations';
	import { onDestroy, onMount } from 'svelte';
	import Collapsible from '$components/Collapsible.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import Radar from '$lib/components/ui/charts/Radar.svelte';
	import Ring from '$lib/components/ui/charts/Ring.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	// OLD CODE START — #96: every category had a number, even when its input never loaded
	// interface CategoryScore {
	// 	name: string;
	// 	icon: string;
	// 	score: number;
	// 	status: 'Good' | 'Needs Attention' | 'Poor';
	// 	statusClass: string;
	// 	description: string;
	// 	findings: string[];
	// }
	// OLD CODE END
	/** The page's five requests; a category built on one that failed has no score. */
	type Input = 'protocols' | 'alerts' | 'devices' | 'risk' | 'investigations';

	interface CategoryScore {
		name: string;
		icon: string;
		score: number | null;
		// OLD CODE START — 2026-11-03 redesign: title-case status word
		// status: 'Good' | 'Needs Attention' | 'Poor' | "Couldn't compute";
		// OLD CODE END
		status: 'Good' | 'Needs attention' | 'Poor' | "Couldn't compute";
		statusClass: string;
		/** The card's subtitle: what the score measures. */
		sub: string;
		description: string;
		findings: string[];
		needs: Input[];
	}

	const INPUT_NAMES: Record<Input, string> = {
		protocols: 'traffic protocols',
		alerts: 'alert counts',
		devices: 'the device count',
		risk: 'risk scores',
		investigations: 'investigation stats',
	};

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = $state(true);
	// The first load has finished: until then no card shows a figure computed from the stand-in defaults
	let loaded = $state(false);
	let protocols = $state<ProtocolsResponse>({ from: '', to: '', protocols: [], services: [] });
	let alertCounts = $state<AlertCountResponse>({ from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } });
	// OLD CODE START — #96: see the getDevices import
	// let deviceList = $state<DeviceListResponse>({ from: '', to: '', limit: 100, devices: [] });
	// OLD CODE END
	let deviceCount = $state<DeviceCountResponse>({ from: '', to: '', count: 0 });
	let riskScores = $state<RiskScoresResponse>({ scores: [] });
	let investigationStats = $state<InvestigationStats>({ total: 0, by_status: {}, by_severity: {} });
	// #96: requests that failed; the defaults above stand in for them only so the other scores compute
	let failed = $state<Input[]>([]);

	// ---------------------------------------------------------------------------
	// Scoring constants
	// ---------------------------------------------------------------------------

	const WEIGHTS = {
		encryption: 0.25,
		dns: 0.15,
		network: 0.15,
		patch: 0.15,
		alerts: 0.15,
		monitoring: 0.15,
	};

	// ---------------------------------------------------------------------------
	// Computed scores
	// ---------------------------------------------------------------------------

	// OLD CODE START — #86: Zeek service names only. QUIC and TLS Zeek didn't parse (G11: ~44k
	// connections on port 443) counted as plaintext, pings and discovery sat in the denominator
	// (G11: 19%), and DNS could never pass 0% (Zeek has no dns_over_tls service; DoT is ssl on 853)
	// let encryptionScore = $derived.by(() => {
	// 	const services = protocols.services;
	// 	if (services.length === 0) return 100;
	// 	const totalConnections = services.reduce((sum, s) => sum + s.count, 0);
	// 	if (totalConnections === 0) return 100;
	// 	const encryptedNames = ['ssl', 'tls', 'https', 'imaps', 'smtps', 'ldaps', 'ftps', 'ssh', 'dns_over_tls', 'dns_over_https'];
	// 	const encryptedCount = services
	// 		.filter((s) => encryptedNames.some((n) => s.name.toLowerCase().includes(n)))
	// 		.reduce((sum, s) => sum + s.count, 0);
	// 	return Math.round((encryptedCount / totalConnections) * 100);
	// });
	// let dnsScore = $derived.by(() => {
	// 	const services = protocols.services;
	// 	if (services.length === 0) return 100;
	// 	const totalDns = services
	// 		.filter((s) => s.name.toLowerCase().includes('dns'))
	// 		.reduce((sum, s) => sum + s.count, 0);
	// 	if (totalDns === 0) return 100;
	// 	const plainDns = services
	// 		.filter((s) => s.name.toLowerCase() === 'dns')
	// 		.reduce((sum, s) => sum + s.count, 0);
	// 	return Math.round(100 - (plainDns / totalDns) * 100);
	// });
	// OLD CODE END

	// The daemon applies the IoT pages' encryption rule (#42) to the whole network
	let encrypted = $derived(protocols.encryption?.encrypted ?? 0);
	let encryptionEligible = $derived(protocols.encryption?.eligible ?? 0);
	let encryptionScore = $derived(
		encryptionEligible === 0 ? 100 : Math.round((encrypted / encryptionEligible) * 100),
	);

	let plainDns = $derived(protocols.dns?.plain ?? 0);
	let dnsOverTls = $derived(protocols.dns?.over_tls ?? 0);
	let dnsScore = $derived(
		plainDns + dnsOverTls === 0 ? 100 : Math.round((dnsOverTls / (plainDns + dnsOverTls)) * 100),
	);

	// Devices on the list that have a score. OLD CODE: each figure used riskScores.scores.length,
	// which counts per IP: a second address of one device (G11: an AP's VLAN 40 IP) gave
	// "55 of 54 devices" and coverage above 100% (#81)
	// OLD CODE START — #96: the device list's top 100 by bytes against the risk list's top 100 by
	// connections; on a network with more devices each one in only one list cost 10 points
	// let scoredIps = $derived(new Set(riskScores.scores.map((s) => s.ip)));
	// let scoredDevices = $derived(deviceList.devices.filter((d) => scoredIps.has(d.ip)).length);
	// OLD CODE END
	// Both are every device, by the same rules: the daemon scores each device /api/devices/count
	// counts. min() keeps coverage at most 100% if one crosses the threshold between the two requests.
	let totalDevices = $derived(deviceCount.count);
	let scoredDevices = $derived(Math.min(riskScores.scores.length, totalDevices));

	let networkScore = $derived.by(() => {
		// OLD CODE START — #96: the device list's length, at most 100
		// const totalDevices = deviceList.devices.length;
		// OLD CODE END
		if (totalDevices === 0) return 100;

		const devicesWithRisk = scoredDevices;
		const unbaselined = totalDevices - devicesWithRisk;
		const penalty = unbaselined * 10;
		return Math.max(0, 100 - penalty);
	});

	let patchScore = $derived.by(() => {
		// Approximate from protocol distribution: look for TLS version hints
		// Since we do not have direct TLS version data, we use a heuristic based on
		// the presence of modern vs legacy protocols
		const services = protocols.services;
		if (services.length === 0) return 100;

		const legacyProtocols = ['http', 'ftp', 'telnet', 'pop3', 'imap'];
		const totalConnections = services.reduce((sum, s) => sum + s.count, 0);
		if (totalConnections === 0) return 100;

		const legacyCount = services
			.filter((s) => legacyProtocols.some((lp) => s.name.toLowerCase() === lp))
			.reduce((sum, s) => sum + s.count, 0);

		// Lower legacy usage => higher patch/currency score
		return Math.round(100 - (legacyCount / totalConnections) * 100);
	});

	let alertScore = $derived.by(() => {
		const total = alertCounts.counts.total;
		if (total === 0) return 100;

		// Use investigation stats to approximate acknowledged alerts
		const resolvedOrClosed = (investigationStats.by_status['resolved'] ?? 0) + (investigationStats.by_status['closed'] ?? 0);
		const totalInvestigations = investigationStats.total;
		if (totalInvestigations === 0) return 0;

		return Math.min(100, Math.round((resolvedOrClosed / totalInvestigations) * 100));
	});

	let monitoringScore = $derived.by(() => {
		// OLD CODE START — #96: the device list's length, at most 100
		// const totalDevices = deviceList.devices.length;
		// OLD CODE END
		if (totalDevices === 0) return 100;

		const devicesWithRisk = scoredDevices;
		return Math.round((devicesWithRisk / totalDevices) * 100);
	});

	let overallScore = $derived(
		Math.round(
			encryptionScore * WEIGHTS.encryption +
			dnsScore * WEIGHTS.dns +
			networkScore * WEIGHTS.network +
			patchScore * WEIGHTS.patch +
			alertScore * WEIGHTS.alerts +
			monitoringScore * WEIGHTS.monitoring
		)
	);

	let overallGrade = $derived.by(() => {
		if (overallScore >= 90) return 'A';
		if (overallScore >= 80) return 'B';
		if (overallScore >= 70) return 'C';
		if (overallScore >= 60) return 'D';
		return 'F';
	});

	// OLD CODE START — 2026-11-03 redesign: legacy grade colour classes; the grade is a Ring and a word now
	// let gradeColorClass = $derived.by(() => {
	// 	if (overallScore >= 90) return 'grade-a';
	// 	if (overallScore >= 80) return 'grade-b';
	// 	if (overallScore >= 70) return 'grade-c';
	// 	return 'grade-df';
	// });
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Category cards
	// ---------------------------------------------------------------------------

	function getStatus(score: number): 'Good' | 'Needs attention' | 'Poor' {
		if (score >= 80) return 'Good';
		if (score >= 50) return 'Needs attention';
		return 'Poor';
	}

	// OLD CODE START — 2026-11-03 redesign: legacy badge classes
	// function getStatusClass(score: number): string {
	// 	if (score >= 80) return 'badge-success';
	// 	if (score >= 50) return 'badge-warning';
	// 	return 'badge-danger';
	// }
	// OLD CODE END
	/** The status chip: the word always shows; the tint only backs it up. */
	function getStatusClass(score: number): string {
		if (score >= 80) return 'is-ok';
		if (score >= 50) return 'is-warn';
		return 'is-bad';
	}

	function getEncryptionFindings(): string[] {
		const findings: string[] = [];
		const services = protocols.services;
		const totalConnections = services.reduce((sum, s) => sum + s.count, 0);

		const httpCount = services
			.filter((s) => s.name.toLowerCase() === 'http')
			.reduce((sum, s) => sum + s.count, 0);
		// OLD CODE START — #86: TLS by service name only, and "% of total traffic" was a share of connections
		// const httpsCount = services
		// 	.filter((s) => s.name.toLowerCase() === 'ssl' || s.name.toLowerCase() === 'https')
		// 	.reduce((sum, s) => sum + s.count, 0);
		// if (httpsCount > 0) {
		// 	findings.push(`${httpsCount.toLocaleString()} encrypted HTTPS/TLS connections`);
		// }
		// if (totalConnections > 0) {
		// 	findings.push(`${encryptionScore}% of total traffic is encrypted`);
		// }
		// OLD CODE END

		if (httpCount > 0) {
			findings.push(`${httpCount.toLocaleString()} unencrypted HTTP connections detected`);
		}
		if (totalConnections > 0 && encryptionEligible > 0) {
			findings.push(
				`${encrypted.toLocaleString()} of ${encryptionEligible.toLocaleString()} connections encrypted (${encryptionScore}%)`,
			);
		} else {
			findings.push('No traffic data available yet');
		}
		return findings;
	}

	function getDnsFindings(): string[] {
		const findings: string[] = [];

		// OLD CODE START — #86: looked for service names Zeek never emits, so encrypted DNS was always 0
		// const plainDns = services
		// 	.filter((s) => s.name.toLowerCase() === 'dns')
		// 	.reduce((sum, s) => sum + s.count, 0);
		// const encryptedDns = services
		// 	.filter((s) => ['dns_over_tls', 'dns_over_https', 'doh', 'dot'].some((n) => s.name.toLowerCase().includes(n)))
		// 	.reduce((sum, s) => sum + s.count, 0);
		// OLD CODE END
		const encryptedDns = dnsOverTls;

		if (plainDns > 0) {
			findings.push(`${plainDns.toLocaleString()} plain-text DNS lookups observed`);
		}
		if (encryptedDns > 0) {
			findings.push(`${encryptedDns.toLocaleString()} DNS-over-TLS connections`);
		}
		if (plainDns === 0 && encryptedDns === 0) {
			findings.push('No DNS traffic data available yet');
		} else if (dnsScore < 50) {
			findings.push('Consider enabling DNS-over-HTTPS or DNS-over-TLS on your router');
		}
		return findings;
	}

	function getNetworkFindings(): string[] {
		const findings: string[] = [];
		// OLD CODE START — #96: the device list's length, at most 100
		// const totalDevices = deviceList.devices.length;
		// OLD CODE END
		const baselinedDevices = scoredDevices;
		const unbaselined = totalDevices - baselinedDevices;

		findings.push(`${totalDevices} device(s) discovered on your network`);
		if (unbaselined > 0) {
			findings.push(`${unbaselined} device(s) not yet baselined`);
		} else if (totalDevices > 0) {
			findings.push('All devices have been baselined');
		}
		return findings;
	}

	function getPatchFindings(): string[] {
		const findings: string[] = [];
		const services = protocols.services;

		const legacyProtocols = ['http', 'ftp', 'telnet', 'pop3', 'imap'];
		for (const lp of legacyProtocols) {
			const count = services
				.filter((s) => s.name.toLowerCase() === lp)
				.reduce((sum, s) => sum + s.count, 0);
			if (count > 0) {
				findings.push(`${count.toLocaleString()} ${lp.toUpperCase()} connections (consider upgrading to encrypted variant)`);
			}
		}
		if (findings.length === 0) {
			findings.push('No legacy unencrypted protocols detected');
		}
		return findings;
	}

	function getAlertFindings(): string[] {
		const findings: string[] = [];
		const total = alertCounts.counts.total;

		if (total === 0) {
			findings.push('No alerts detected — your network looks clean');
		} else {
			findings.push(`${total.toLocaleString()} total alert(s) in the current period`);
			if (alertCounts.counts.high > 0) {
				findings.push(`${alertCounts.counts.high} high-severity alert(s) require attention`);
			}
			const resolved = (investigationStats.by_status['resolved'] ?? 0) + (investigationStats.by_status['closed'] ?? 0);
			const totalInv = investigationStats.total;
			if (totalInv > 0) {
				findings.push(`${resolved} of ${totalInv} investigation(s) resolved`);
			}
		}
		return findings;
	}

	function getMonitoringFindings(): string[] {
		const findings: string[] = [];
		// OLD CODE START — #96: the device list's length, at most 100
		// const totalDevices = deviceList.devices.length;
		// OLD CODE END
		const scored = scoredDevices;

		if (totalDevices === 0) {
			findings.push('No devices discovered yet');
		} else {
			findings.push(`${scored} of ${totalDevices} device(s) have risk scores computed`);
			const unscored = totalDevices - scored;
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
			};
		});
	}

	// OLD CODE START — #96: scored every category, including ones whose input failed
	// let categories = $derived<CategoryScore[]>([
	// OLD CODE END
	let categories = $derived<CategoryScore[]>(withFailures([
		{
			name: 'Encryption',
			sub: 'Percent of connections that can be encrypted · current period',
			icon: 'lock',
			score: encryptionScore,
			status: getStatus(encryptionScore),
			statusClass: getStatusClass(encryptionScore),
			description: 'Share of connections that use encryption (TLS/HTTPS, QUIC, SSH, VPN). Local chatter that is never encrypted (DNS, DHCP, NTP, discovery, pings) is left out.',
			findings: getEncryptionFindings(),
			needs: ['protocols'],
		},
		{
			name: 'DNS security',
			sub: 'Percent of DNS lookups sent over TLS · current period',
			icon: 'globe',
			score: dnsScore,
			status: getStatus(dnsScore),
			statusClass: getStatusClass(dnsScore),
			description: 'Share of DNS lookups sent over DNS-over-TLS instead of plain text. DNS-over-HTTPS looks like any other HTTPS, so it is not counted.',
			findings: getDnsFindings(),
			needs: ['protocols'],
		},
		{
			name: 'Network segmentation',
			sub: '100, less 10 for each device not yet baselined',
			icon: 'layers',
			score: networkScore,
			status: getStatus(networkScore),
			statusClass: getStatusClass(networkScore),
			description: 'Whether all devices have been baselined and communicate with expected destinations.',
			findings: getNetworkFindings(),
			needs: ['devices', 'risk'],
		},
		{
			name: 'Patch currency',
			sub: 'Percent of connections not on legacy protocols · current period',
			icon: 'refresh',
			score: patchScore,
			status: getStatus(patchScore),
			statusClass: getStatusClass(patchScore),
			description: 'Usage of modern protocol versions (TLS 1.3, HTTP/2+) vs legacy unencrypted protocols.',
			findings: getPatchFindings(),
			needs: ['protocols'],
		},
		{
			name: 'Alert response',
			sub: 'Percent of investigations resolved or closed',
			icon: 'bell-ring',
			score: alertScore,
			status: getStatus(alertScore),
			statusClass: getStatusClass(alertScore),
			description: 'How effectively alerts are being acknowledged and investigated.',
			findings: getAlertFindings(),
			// with no alerts the score is 100 whatever the investigations; with some it needs them
			needs: alertCounts.counts.total > 0 ? ['alerts', 'investigations'] : ['alerts'],
		},
		{
			name: 'Monitoring coverage',
			sub: 'Percent of devices with a risk score',
			icon: 'eye',
			score: monitoringScore,
			status: getStatus(monitoringScore),
			statusClass: getStatusClass(monitoringScore),
			description: 'Proportion of discovered devices that have been risk-scored and are actively monitored.',
			findings: getMonitoringFindings(),
			needs: ['devices', 'risk'],
		},
	]));

	/** Categories that couldn't be computed: the overall score needs all six. */
	let uncomputed = $derived(categories.filter((c) => c.score === null).map((c) => c.name));

	// ---------------------------------------------------------------------------
	// Recommendations
	// ---------------------------------------------------------------------------

	let recommendations = $derived.by(() => {
		const recs: { text: string; priority: 'high' | 'medium' | 'low' }[] = [];
		// OLD CODE START — #96: a category that couldn't be computed was judged on its stand-in score
		// if (encryptionScore < 80) {
		// if (dnsScore < 80) {
		// if (networkScore < 80) {
		// if (patchScore < 80) {
		// if (alertScore < 80) {
		// if (monitoringScore < 80) {
		// if (recs.length === 0) {
		// OLD CODE END
		const low = (name: string, score: number) => !uncomputed.includes(name) && score < 80;

		if (low('Encryption', encryptionScore)) {
			recs.push({
				text: 'Reduce unencrypted HTTP traffic by enabling HTTPS on internal services and ensuring browser HSTS is active.',
				priority: encryptionScore < 50 ? 'high' : 'medium',
			});
		}
		if (low('DNS security', dnsScore)) {
			recs.push({
				text: 'Enable DNS-over-HTTPS (DoH) or DNS-over-TLS (DoT) on your router or devices to encrypt DNS queries.',
				priority: dnsScore < 50 ? 'high' : 'medium',
			});
		}
		if (low('Network segmentation', networkScore)) {
			recs.push({
				text: 'Review un-baselined devices on the Devices page and mark them as known to improve segmentation visibility.',
				priority: 'medium',
			});
		}
		if (low('Patch currency', patchScore)) {
			recs.push({
				text: 'Replace legacy protocols (FTP, Telnet, plain HTTP) with encrypted alternatives (SFTP, SSH, HTTPS).',
				priority: patchScore < 50 ? 'high' : 'medium',
			});
		}
		if (low('Alert response', alertScore)) {
			recs.push({
				text: 'Investigate and resolve open alerts. Create investigations for high-severity alerts to improve response tracking.',
				priority: alertScore < 50 ? 'high' : 'medium',
			});
		}
		if (low('Monitoring coverage', monitoringScore)) {
			recs.push({
				text: 'Ensure all devices are being monitored. Visit the Devices page to trigger risk scoring for un-scored devices.',
				priority: 'medium',
			});
		}
		if (uncomputed.length > 0) {
			recs.push({
				text: `Couldn't compute ${uncomputed.join(', ')}: a request failed. Refresh to try again.`,
				priority: 'medium',
			});
		} else if (recs.length === 0) {
			recs.push({
				text: 'Your network security posture looks excellent. Keep monitoring for changes and new devices.',
				priority: 'low',
			});
		}
		return recs;
	});

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03 redesign: wrote state whenever it finished and reported nothing;
	// the guarded loader below feeds the page refresh contract (PLAN.md §5.5)
	// async function fetchAll() {
	// 	loading = true;
	// 	// #96: each input on its own, so one failure marks only the categories built on it
	// 	const [protocolsRes, alertsRes, devicesRes, riskRes, statsRes] = await Promise.allSettled([
	// 		getProtocolDistribution(),
	// 		getAlertCount(),
	// 		getDeviceCount(),
	// 		getRiskScores(),
	// 		getInvestigationStats(),
	// 	]);
	// 	if (protocolsRes.status === 'fulfilled') protocols = protocolsRes.value;
	// 	if (alertsRes.status === 'fulfilled') alertCounts = alertsRes.value;
	// 	if (devicesRes.status === 'fulfilled') deviceCount = devicesRes.value;
	// 	if (riskRes.status === 'fulfilled') riskScores = riskRes.value;
	// 	if (statsRes.status === 'fulfilled') investigationStats = statsRes.value;
	// 	const settled: Record<Input, PromiseSettledResult<unknown>> = {
	// 		protocols: protocolsRes,
	// 		alerts: alertsRes,
	// 		devices: devicesRes,
	// 		risk: riskRes,
	// 		investigations: statsRes,
	// 	};
	// 	failed = (Object.keys(settled) as Input[]).filter((k) => settled[k].status === 'rejected');
	// 	loading = false;
	// }
	// OLD CODE END
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		loading = true;
		// #96: each input on its own, so one failure marks only the categories built on it
		const [protocolsRes, alertsRes, devicesRes, riskRes, statsRes] = await Promise.allSettled([
			getProtocolDistribution(),
			getAlertCount(),
			getDeviceCount(),
			getRiskScores(),
			getInvestigationStats(),
		]);
		if (!guard.current(g)) return 'skipped';
		if (protocolsRes.status === 'fulfilled') protocols = protocolsRes.value;
		if (alertsRes.status === 'fulfilled') alertCounts = alertsRes.value;
		if (devicesRes.status === 'fulfilled') deviceCount = devicesRes.value;
		if (riskRes.status === 'fulfilled') riskScores = riskRes.value;
		if (statsRes.status === 'fulfilled') investigationStats = statsRes.value;
		const settled: Record<Input, PromiseSettledResult<unknown>> = {
			protocols: protocolsRes,
			alerts: alertsRes,
			devices: devicesRes,
			risk: riskRes,
			investigations: statsRes,
		};
		failed = (Object.keys(settled) as Input[]).filter((k) => settled[k].status === 'rejected');
		loading = false;
		loaded = true;
		if (failed.length === 0) return 'ok';
		return failed.length === Object.keys(settled).length ? 'failed' : 'partial';
	}

	// OLD CODE START — #96: any failure left the defaults in place, so it scored as a clean network
	/*
	async function fetchAll() {
		loading = true;
		try {
			const [protocolsRes, alertsRes, devicesRes, riskRes, statsRes] = await Promise.all([
				getProtocolDistribution(),
				getAlertCount(),
				// OLD CODE START — #96: see the getDevices import
				// getDevices(),
				// OLD CODE END
				getDeviceCount(),
				getRiskScores(),
				getInvestigationStats(),
			]);

			protocols = protocolsRes;
			alertCounts = alertsRes;
			// OLD CODE START — #96: see the getDevices import
			// deviceList = devicesRes;
			// OLD CODE END
			deviceCount = devicesRes;
			riskScores = riskRes;
			investigationStats = statsRes;
		} catch {
			// Graceful degradation — scores will show 100% with empty data
		} finally {
			loading = false;
		}
	}
	*/
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Initial fetch
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03 redesign: the first load now goes through the refresh contract
	// $effect(() => {
	// 	fetchAll();
	// });
	// OLD CODE END
	const refresh = registerPageRefresh(load);
	onMount(() => {
		refresh.run();
	});
	onDestroy(() => refresh.unregister());

	// ---------------------------------------------------------------------------
	// Page summary (only figures computed above, nothing new)
	// ---------------------------------------------------------------------------

	const computed = $derived(categories.filter((c) => c.score !== null));
	const byStatus = (status: CategoryScore['status']) => categories.filter((c) => c.status === status);

	const radarAxes = $derived(computed.map((c) => ({ key: c.name, label: c.name, value: c.score ?? 0 })));
	const weakest = $derived(computed.reduce<CategoryScore | null>((low, c) => (low && (low.score ?? 0) <= (c.score ?? 0) ? low : c), null));

	const summary = $derived.by(() => {
		if (overallScore >= 90) return 'Excellent security posture. Your network follows best practices across all categories.';
		if (overallScore >= 80) return 'Good security posture with minor areas for improvement.';
		if (overallScore >= 70) return 'Moderate security posture. Several areas need attention.';
		if (overallScore >= 60) return 'Below average. Multiple security practices need improvement.';
		return 'Critical issues detected. Immediate action recommended.';
	});

	type Recommendation = { text: string; priority: 'high' | 'medium' | 'low' };
	const PRIORITY_RANK: Record<Recommendation['priority'], number> = { high: 3, medium: 2, low: 1 };
	const recColumns: Column<Recommendation>[] = [
		{ key: 'priority', label: 'Priority', sortValue: (r) => PRIORITY_RANK[r.priority], cell: priorityCell },
		{ key: 'text', label: 'Recommendation', sortValue: (r) => r.text.toLowerCase(), cell: recCell, class: 'wrap' },
	];

	/** "Encryption, DNS security" or "None". */
	const names = (cats: CategoryScore[]) => (cats.length > 0 ? cats.map((c) => c.name).join(', ') : 'None');
</script>

{#snippet priorityCell(r: Recommendation)}<SeverityPill level={r.priority} />{/snippet}
{#snippet recCell(r: Recommendation)}{r.text}{/snippet}

<svelte:head>
	<title>Security Posture | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Security posture</h1>
		<p class="page-sub">How well your network follows security best practices</p>
	</div>
	<div class="head-actions">
		<!-- The top bar's Refresh does the same; this one stays for phone widths, where the top bar is hidden -->
		<button class="btn" onclick={() => refresh.run()} disabled={loading}>
			<Icon name="refresh" />{loading ? 'Refreshing…' : 'Refresh'}
		</button>
	</div>
</div>

<div class="grid posture">
	<KpiCard
		class="c-4"
		label="Good"
		icon="check"
		value={loaded ? byStatus('Good').length : '—'}
		unit={loaded ? 'of 6' : undefined}
		note="Scored 80 or more"
		sub={loaded ? names(byStatus('Good')) : undefined}
	/>
	<KpiCard
		class="c-4"
		label="Needs attention"
		icon="warn"
		value={loaded ? byStatus('Needs attention').length : '—'}
		unit={loaded ? 'of 6' : undefined}
		note="Scored 50 to 79"
		sub={loaded ? names(byStatus('Needs attention')) : undefined}
	/>
	<KpiCard
		class="c-4"
		label="Poor"
		icon="threats"
		value={loaded ? byStatus('Poor').length : '—'}
		unit={loaded ? 'of 6' : undefined}
		note="Scored under 50"
		sub={loaded ? names(byStatus('Poor')) : undefined}
	/>

	<Card title="Score by category" sub="0 to 100 for each category · higher is better" hero class="c-8">
		{#if !loaded}
			<CardState state="loading" title="Calculating security posture…" />
		{:else if radarAxes.length < 3}
			<CardState
				state="error"
				title="Couldn't compute enough categories to draw them."
				message="{uncomputed.join(', ')} have no score because a request failed. Refresh to try again."
				onaction={() => refresh.run()}
			/>
		{:else}
			<Radar
				axes={radarAxes}
				ariaLabel={weakest ? `Score by category: lowest is ${weakest.name} at ${weakest.score} out of 100` : 'Score by category'}
			/>
			{#if uncomputed.length > 0}
				<p class="note">Not shown: {uncomputed.join(', ')}, because a request failed.</p>
			{/if}
		{/if}
	</Card>

	<Card title="Overall security posture" sub="Weighted across the six categories" class="c-4">
		{#if !loaded}
			<CardState state="loading" title="Calculating the overall score" />
		{:else if uncomputed.length > 0}
			<!-- #96: a weighted score over the categories that loaded would read as the whole picture -->
			<CardState
				state="error"
				title="Couldn't compute the overall score"
				message="{uncomputed.join(', ')} {uncomputed.length === 1 ? 'has' : 'have'} no score because a request failed. Refresh to try again."
				onaction={() => refresh.run()}
			/>
		{:else}
			<div class="overall">
				<Ring
					value={overallScore}
					label="Grade {overallGrade}"
					ariaLabel="Overall score {overallScore} out of 100, grade {overallGrade}"
				/>
				<p class="trust-plain">{summary}</p>
			</div>
		{/if}
	</Card>

	{#if !loaded}
		<Card title="Categories" sub="Six checks, each scored 0 to 100" class="c-12">
			<CardState state="loading" title="Scoring the categories" />
		</Card>
	{:else}
		{#each categories as cat (cat.name)}
			<Card title={cat.name} sub={cat.sub} class="c-4 category-card">
				{#snippet actions()}
					<span class="chip {cat.statusClass}">{cat.status}</span>
				{/snippet}

				<div class="stack">
					{#if cat.score === null}
						<!-- #96: no score for a category whose input failed -->
						<div class="score-row">
							<span class="score dim">—</span>
							<span class="unavailable">{cat.findings[0]}</span>
						</div>
					{:else}
						<div class="score-row">
							<span class="score">{cat.score}%</span>
							<Meter value={cat.score} label="{cat.name} score" />
						</div>
					{/if}

					<p class="desc">{cat.description}</p>

					<Collapsible title="View findings" badge={String(cat.findings.length)}>
						<ul class="findings">
							{#each cat.findings as finding}
								<li><Icon name="check" /><span>{finding}</span></li>
							{/each}
						</ul>
					</Collapsible>
				</div>
			</Card>
		{/each}
	{/if}

	<Card title="Improve your score" sub="What to change, highest priority first" class="c-12">
		{#if !loaded}
			<CardState state="loading" title="Working out recommendations" />
		{:else}
			<div class="recs">
				<DataTable
					columns={recColumns}
					rows={recommendations}
					ariaLabel="Recommendations"
					rowKey={(r) => r.text}
					initialSort={{ key: 'priority', dir: 'desc' }}
				/>
			</div>
		{/if}
	</Card>
</div>

<style>
	.overall {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-4);
		text-align: center;
	}

	.note {
		margin-top: var(--sp-3);
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.score-row {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.score {
		font: 300 var(--text-xl)/1 var(--font-display);
		letter-spacing: -0.03em;
		font-variant-numeric: tabular-nums;
	}

	.unavailable,
	.desc {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.findings {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.findings li {
		display: flex;
		gap: var(--sp-2);
	}

	.findings li :global(.ic) {
		flex: none;
		width: 14px;
		height: 14px;
		margin-top: 3px;
		color: var(--text-3);
	}

	.recs :global(td.wrap) {
		white-space: normal;
		min-width: 16em;
	}

	/* Keep the status chip beside the title when the subtitle wraps */
	.posture > :global(.category-card > .card-head) {
		flex-wrap: nowrap;
	}
</style>
