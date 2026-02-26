<script lang="ts">
	import { getProtocolDistribution } from '$api/traffic';
	import { getAlertCount } from '$api/alerts';
	import { getDevices } from '$api/devices';
	import { getRiskScores } from '$api/risk';
	import { getInvestigationStats } from '$api/investigations';
	import type { ProtocolsResponse } from '$api/traffic';
	import type { AlertCountResponse } from '$api/alerts';
	import type { DeviceListResponse } from '$api/devices';
	import type { RiskScoresResponse } from '$api/risk';
	import type { InvestigationStats } from '$api/investigations';
	import Collapsible from '$components/Collapsible.svelte';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	interface CategoryScore {
		name: string;
		icon: string;
		score: number;
		status: 'Good' | 'Needs Attention' | 'Poor';
		statusClass: string;
		description: string;
		findings: string[];
	}

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = $state(true);
	let protocols = $state<ProtocolsResponse>({ from: '', to: '', protocols: [], services: [] });
	let alertCounts = $state<AlertCountResponse>({ from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } });
	let deviceList = $state<DeviceListResponse>({ from: '', to: '', limit: 100, devices: [] });
	let riskScores = $state<RiskScoresResponse>({ scores: [] });
	let investigationStats = $state<InvestigationStats>({ total: 0, by_status: {}, by_severity: {} });

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

	let encryptionScore = $derived.by(() => {
		const services = protocols.services;
		if (services.length === 0) return 100;

		const totalConnections = services.reduce((sum, s) => sum + s.count, 0);
		if (totalConnections === 0) return 100;

		const encryptedNames = ['ssl', 'tls', 'https', 'imaps', 'smtps', 'ldaps', 'ftps', 'ssh', 'dns_over_tls', 'dns_over_https'];
		const encryptedCount = services
			.filter((s) => encryptedNames.some((n) => s.name.toLowerCase().includes(n)))
			.reduce((sum, s) => sum + s.count, 0);

		return Math.round((encryptedCount / totalConnections) * 100);
	});

	let dnsScore = $derived.by(() => {
		const services = protocols.services;
		if (services.length === 0) return 100;

		const totalDns = services
			.filter((s) => s.name.toLowerCase().includes('dns'))
			.reduce((sum, s) => sum + s.count, 0);
		if (totalDns === 0) return 100;

		const plainDns = services
			.filter((s) => s.name.toLowerCase() === 'dns')
			.reduce((sum, s) => sum + s.count, 0);

		return Math.round(100 - (plainDns / totalDns) * 100);
	});

	let networkScore = $derived.by(() => {
		const totalDevices = deviceList.devices.length;
		if (totalDevices === 0) return 100;

		const devicesWithRisk = riskScores.scores.length;
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
		const totalDevices = deviceList.devices.length;
		if (totalDevices === 0) return 100;

		const devicesWithRisk = riskScores.scores.length;
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

	let gradeColorClass = $derived.by(() => {
		if (overallScore >= 90) return 'grade-a';
		if (overallScore >= 80) return 'grade-b';
		if (overallScore >= 70) return 'grade-c';
		return 'grade-df';
	});

	// ---------------------------------------------------------------------------
	// Category cards
	// ---------------------------------------------------------------------------

	function getStatus(score: number): 'Good' | 'Needs Attention' | 'Poor' {
		if (score >= 80) return 'Good';
		if (score >= 50) return 'Needs Attention';
		return 'Poor';
	}

	function getStatusClass(score: number): string {
		if (score >= 80) return 'badge-success';
		if (score >= 50) return 'badge-warning';
		return 'badge-danger';
	}

	function getEncryptionFindings(): string[] {
		const findings: string[] = [];
		const services = protocols.services;
		const totalConnections = services.reduce((sum, s) => sum + s.count, 0);

		const httpCount = services
			.filter((s) => s.name.toLowerCase() === 'http')
			.reduce((sum, s) => sum + s.count, 0);
		const httpsCount = services
			.filter((s) => s.name.toLowerCase() === 'ssl' || s.name.toLowerCase() === 'https')
			.reduce((sum, s) => sum + s.count, 0);

		if (httpCount > 0) {
			findings.push(`${httpCount.toLocaleString()} unencrypted HTTP connections detected`);
		}
		if (httpsCount > 0) {
			findings.push(`${httpsCount.toLocaleString()} encrypted HTTPS/TLS connections`);
		}
		if (totalConnections > 0) {
			findings.push(`${encryptionScore}% of total traffic is encrypted`);
		} else {
			findings.push('No traffic data available yet');
		}
		return findings;
	}

	function getDnsFindings(): string[] {
		const findings: string[] = [];
		const services = protocols.services;

		const plainDns = services
			.filter((s) => s.name.toLowerCase() === 'dns')
			.reduce((sum, s) => sum + s.count, 0);
		const encryptedDns = services
			.filter((s) => ['dns_over_tls', 'dns_over_https', 'doh', 'dot'].some((n) => s.name.toLowerCase().includes(n)))
			.reduce((sum, s) => sum + s.count, 0);

		if (plainDns > 0) {
			findings.push(`${plainDns.toLocaleString()} plain-text DNS queries observed`);
		}
		if (encryptedDns > 0) {
			findings.push(`${encryptedDns.toLocaleString()} encrypted DNS queries (DoH/DoT)`);
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
		const totalDevices = deviceList.devices.length;
		const baselinedDevices = riskScores.scores.length;
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
		const totalDevices = deviceList.devices.length;
		const scored = riskScores.scores.length;

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

	let categories = $derived<CategoryScore[]>([
		{
			name: 'Encryption',
			icon: 'lock',
			score: encryptionScore,
			status: getStatus(encryptionScore),
			statusClass: getStatusClass(encryptionScore),
			description: 'Percentage of network traffic using TLS/HTTPS encryption vs unencrypted protocols.',
			findings: getEncryptionFindings(),
		},
		{
			name: 'DNS Security',
			icon: 'globe',
			score: dnsScore,
			status: getStatus(dnsScore),
			statusClass: getStatusClass(dnsScore),
			description: 'How much of your DNS traffic uses encrypted transports like DNS-over-HTTPS or DNS-over-TLS.',
			findings: getDnsFindings(),
		},
		{
			name: 'Network Segmentation',
			icon: 'layers',
			score: networkScore,
			status: getStatus(networkScore),
			statusClass: getStatusClass(networkScore),
			description: 'Whether all devices have been baselined and communicate with expected destinations.',
			findings: getNetworkFindings(),
		},
		{
			name: 'Patch Currency',
			icon: 'refresh',
			score: patchScore,
			status: getStatus(patchScore),
			statusClass: getStatusClass(patchScore),
			description: 'Usage of modern protocol versions (TLS 1.3, HTTP/2+) vs legacy unencrypted protocols.',
			findings: getPatchFindings(),
		},
		{
			name: 'Alert Response',
			icon: 'bell-ring',
			score: alertScore,
			status: getStatus(alertScore),
			statusClass: getStatusClass(alertScore),
			description: 'How effectively alerts are being acknowledged and investigated.',
			findings: getAlertFindings(),
		},
		{
			name: 'Monitoring Coverage',
			icon: 'eye',
			score: monitoringScore,
			status: getStatus(monitoringScore),
			statusClass: getStatusClass(monitoringScore),
			description: 'Proportion of discovered devices that have been risk-scored and are actively monitored.',
			findings: getMonitoringFindings(),
		},
	]);

	// ---------------------------------------------------------------------------
	// Recommendations
	// ---------------------------------------------------------------------------

	let recommendations = $derived.by(() => {
		const recs: { text: string; priority: 'high' | 'medium' | 'low' }[] = [];

		if (encryptionScore < 80) {
			recs.push({
				text: 'Reduce unencrypted HTTP traffic by enabling HTTPS on internal services and ensuring browser HSTS is active.',
				priority: encryptionScore < 50 ? 'high' : 'medium',
			});
		}
		if (dnsScore < 80) {
			recs.push({
				text: 'Enable DNS-over-HTTPS (DoH) or DNS-over-TLS (DoT) on your router or devices to encrypt DNS queries.',
				priority: dnsScore < 50 ? 'high' : 'medium',
			});
		}
		if (networkScore < 80) {
			recs.push({
				text: 'Review un-baselined devices on the Devices page and mark them as known to improve segmentation visibility.',
				priority: 'medium',
			});
		}
		if (patchScore < 80) {
			recs.push({
				text: 'Replace legacy protocols (FTP, Telnet, plain HTTP) with encrypted alternatives (SFTP, SSH, HTTPS).',
				priority: patchScore < 50 ? 'high' : 'medium',
			});
		}
		if (alertScore < 80) {
			recs.push({
				text: 'Investigate and resolve open alerts. Create investigations for high-severity alerts to improve response tracking.',
				priority: alertScore < 50 ? 'high' : 'medium',
			});
		}
		if (monitoringScore < 80) {
			recs.push({
				text: 'Ensure all devices are being monitored. Visit the Devices page to trigger risk scoring for un-scored devices.',
				priority: 'medium',
			});
		}
		if (recs.length === 0) {
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

	async function fetchAll() {
		loading = true;
		try {
			const [protocolsRes, alertsRes, devicesRes, riskRes, statsRes] = await Promise.all([
				getProtocolDistribution(),
				getAlertCount(),
				getDevices(),
				getRiskScores(),
				getInvestigationStats(),
			]);

			protocols = protocolsRes;
			alertCounts = alertsRes;
			deviceList = devicesRes;
			riskScores = riskRes;
			investigationStats = statsRes;
		} catch {
			// Graceful degradation — scores will show 100% with empty data
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Initial fetch
	// ---------------------------------------------------------------------------

	$effect(() => {
		fetchAll();
	});
</script>

<svelte:head>
	<title>Security Posture | NetTap</title>
</svelte:head>

<div class="compliance-page">
	<!-- Page header -->
	<div class="page-header">
		<div class="header-left">
			<h2>Security Posture</h2>
			<p class="text-muted">How well your network follows security best practices</p>
		</div>
		<div class="header-actions">
			<button class="btn btn-primary btn-sm" onclick={fetchAll} disabled={loading}>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="23 4 23 10 17 10" />
					<polyline points="1 20 1 14 7 14" />
					<path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
				</svg>
				{loading ? 'Refreshing...' : 'Refresh'}
			</button>
		</div>
	</div>

	{#if loading}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Calculating security posture...</p>
		</div>
	{:else}
		<!-- Overall score card -->
		<div class="overall-score-card card">
			<div class="overall-score-content">
				<div class="grade-circle {gradeColorClass}">
					<span class="grade-letter">{overallGrade}</span>
				</div>
				<div class="overall-score-info">
					<h3 class="overall-score-title">Overall Security Posture</h3>
					<div class="overall-score-bar-wrapper">
						<div class="overall-score-percentage {gradeColorClass}-text">{overallScore}%</div>
						<div class="progress-bar-track progress-bar-lg">
							<div
								class="progress-bar-fill {gradeColorClass}-bg"
								style="width: {overallScore}%"
							></div>
						</div>
					</div>
					<p class="overall-score-summary text-muted">
						{#if overallScore >= 90}
							Excellent security posture. Your network follows best practices across all categories.
						{:else if overallScore >= 80}
							Good security posture with minor areas for improvement.
						{:else if overallScore >= 70}
							Moderate security posture. Several areas need attention.
						{:else if overallScore >= 60}
							Below average. Multiple security practices need improvement.
						{:else}
							Critical issues detected. Immediate action recommended.
						{/if}
					</p>
				</div>
			</div>
		</div>

		<!-- Category cards grid (2x3) -->
		<div class="grid grid-cols-2 category-grid">
			{#each categories as cat}
				<div class="card category-card">
					<div class="category-header">
						<div class="category-icon-name">
							<div class="category-icon">
								<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									{#if cat.icon === 'lock'}
										<rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0110 0v4" />
									{:else if cat.icon === 'globe'}
										<circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
									{:else if cat.icon === 'layers'}
										<polygon points="12 2 2 7 12 12 22 7 12 2" /><polyline points="2 17 12 22 22 17" /><polyline points="2 12 12 17 22 12" />
									{:else if cat.icon === 'refresh'}
										<polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
									{:else if cat.icon === 'bell-ring'}
										<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 01-3.46 0" /><path d="M2 8a10.78 10.78 0 011-4" /><path d="M22 8a10.78 10.78 0 00-1-4" />
									{:else if cat.icon === 'eye'}
										<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
									{/if}
								</svg>
							</div>
							<span class="category-name">{cat.name}</span>
						</div>
						<span class="badge {cat.statusClass}">{cat.status}</span>
					</div>

					<div class="category-score-row">
						<span class="category-score-value">{cat.score}%</span>
						<div class="progress-bar-track">
							<div
								class="progress-bar-fill {cat.score >= 80 ? 'fill-success' : cat.score >= 50 ? 'fill-warning' : 'fill-danger'}"
								style="width: {cat.score}%"
							></div>
						</div>
					</div>

					<p class="category-description text-muted">{cat.description}</p>

					<!-- Expandable detail section -->
					<Collapsible title="View Findings" badge={String(cat.findings.length)}>
						<ul class="findings-list">
							{#each cat.findings as finding}
								<li class="finding-item">
									<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
										<polyline points="9 11 12 14 22 4" />
										<path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
									</svg>
									<span>{finding}</span>
								</li>
							{/each}
						</ul>
					</Collapsible>
				</div>
			{/each}
		</div>

		<!-- Improve Your Score section -->
		<div class="card recommendations-card">
			<div class="recommendations-header">
				<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="12" cy="12" r="10" />
					<line x1="12" y1="16" x2="12" y2="12" />
					<line x1="12" y1="8" x2="12.01" y2="8" />
				</svg>
				<h3>Improve Your Score</h3>
			</div>
			<p class="recommendations-subtitle text-muted">Actionable recommendations to improve your network's security posture</p>

			<div class="recommendations-list">
				{#each recommendations as rec}
					<div class="recommendation-item">
						<span class="rec-priority badge {rec.priority === 'high' ? 'badge-danger' : rec.priority === 'medium' ? 'badge-warning' : 'badge-success'}">
							{rec.priority.toUpperCase()}
						</span>
						<span class="rec-text">{rec.text}</span>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>

<style>
	.compliance-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Page header */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.header-left h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	/* Loading state */
	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* Overall score card */
	.overall-score-card {
		padding: var(--space-xl);
	}

	.overall-score-card:hover {
		border-color: var(--border-default);
	}

	.overall-score-content {
		display: flex;
		align-items: center;
		gap: var(--space-xl);
	}

	.grade-circle {
		width: 96px;
		height: 96px;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		border: 4px solid;
	}

	.grade-circle.grade-a {
		background-color: var(--success-muted);
		border-color: var(--success);
	}

	.grade-circle.grade-b {
		background-color: var(--accent-muted);
		border-color: var(--accent);
	}

	.grade-circle.grade-c {
		background-color: var(--warning-muted);
		border-color: var(--warning);
	}

	.grade-circle.grade-df {
		background-color: var(--danger-muted);
		border-color: var(--danger);
	}

	.grade-letter {
		font-size: 2.5rem;
		font-weight: 800;
		line-height: 1;
	}

	.grade-a .grade-letter {
		color: var(--success);
	}

	.grade-b .grade-letter {
		color: var(--accent);
	}

	.grade-c .grade-letter {
		color: var(--warning);
	}

	.grade-df .grade-letter {
		color: var(--danger);
	}

	.overall-score-info {
		flex: 1;
		min-width: 0;
	}

	.overall-score-title {
		font-size: var(--text-xl);
		font-weight: 700;
		margin-bottom: var(--space-sm);
	}

	.overall-score-bar-wrapper {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		margin-bottom: var(--space-sm);
	}

	.overall-score-percentage {
		font-size: var(--text-2xl);
		font-weight: 700;
		flex-shrink: 0;
		min-width: 56px;
	}

	.grade-a-text {
		color: var(--success);
	}

	.grade-b-text {
		color: var(--accent);
	}

	.grade-c-text {
		color: var(--warning);
	}

	.grade-df-text {
		color: var(--danger);
	}

	.overall-score-summary {
		font-size: var(--text-sm);
		line-height: var(--leading-relaxed);
	}

	/* Progress bars */
	.progress-bar-track {
		flex: 1;
		height: 8px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: hidden;
	}

	.progress-bar-lg {
		height: 12px;
	}

	.progress-bar-fill {
		height: 100%;
		border-radius: var(--radius-full);
		transition: width 0.6s ease;
	}

	.grade-a-bg {
		background-color: var(--success);
	}

	.grade-b-bg {
		background-color: var(--accent);
	}

	.grade-c-bg {
		background-color: var(--warning);
	}

	.grade-df-bg {
		background-color: var(--danger);
	}

	.fill-success {
		background-color: var(--success);
	}

	.fill-warning {
		background-color: var(--warning);
	}

	.fill-danger {
		background-color: var(--danger);
	}

	/* Category grid */
	.category-grid {
		gap: var(--space-md);
	}

	.category-card {
		padding: var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.category-card:hover {
		border-color: var(--border-default);
	}

	.category-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.category-icon-name {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.category-icon {
		width: 36px;
		height: 36px;
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		color: var(--accent);
		flex-shrink: 0;
	}

	.category-name {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
	}

	.category-score-row {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.category-score-value {
		font-size: var(--text-xl);
		font-weight: 700;
		color: var(--text-primary);
		min-width: 52px;
		flex-shrink: 0;
	}

	.category-description {
		font-size: var(--text-sm);
		line-height: var(--leading-relaxed);
	}

	/* Findings list */
	.findings-list {
		list-style: none;
		padding: 0;
		margin: var(--space-sm) 0 0 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.finding-item {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		font-size: var(--text-sm);
		color: var(--text-secondary);
		line-height: var(--leading-normal);
	}

	.finding-item svg {
		flex-shrink: 0;
		margin-top: 2px;
		color: var(--accent);
	}

	/* Recommendations card */
	.recommendations-card {
		padding: var(--space-lg);
	}

	.recommendations-card:hover {
		border-color: var(--border-default);
	}

	.recommendations-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-bottom: var(--space-xs);
		color: var(--accent);
	}

	.recommendations-header h3 {
		font-size: var(--text-lg);
		font-weight: 700;
		color: var(--text-primary);
	}

	.recommendations-subtitle {
		font-size: var(--text-sm);
		margin-bottom: var(--space-lg);
	}

	.recommendations-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.recommendation-item {
		display: flex;
		align-items: flex-start;
		gap: var(--space-md);
		padding: var(--space-md);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-default);
	}

	.rec-priority {
		flex-shrink: 0;
		margin-top: 1px;
	}

	.rec-text {
		font-size: var(--text-sm);
		color: var(--text-primary);
		line-height: var(--leading-relaxed);
	}

	/* Responsive */
	@media (max-width: 768px) {
		.page-header {
			flex-direction: column;
		}

		.header-actions {
			width: 100%;
			justify-content: flex-end;
		}

		.overall-score-content {
			flex-direction: column;
			text-align: center;
		}

		.overall-score-bar-wrapper {
			flex-direction: column;
			align-items: stretch;
		}

		.overall-score-percentage {
			text-align: center;
		}
	}

	@media (max-width: 640px) {
		.recommendation-item {
			flex-direction: column;
			gap: var(--space-sm);
		}
	}
</style>
