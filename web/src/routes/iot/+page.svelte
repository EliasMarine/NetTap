<script lang="ts">
	/**
	 * IoT Trust Score Dashboard — /iot
	 *
	 * Complete smart home health dashboard:
	 *   1. KPIs (devices, anomalies, privacy concerns, unencrypted)
	 *   2. Smart home health: the trust Ring with its privacy, security and behaviour rows
	 *   3. Findings feed
	 *   4. Device trust scores (table; a row opens the drawer)
	 *   5. Manufacturer profiles
	 *   6. Network isolation
	 *   7. Device detail drawer (5 tabs)
	 */

	import { onDestroy, untrack } from 'svelte';
	import DetailDrawer from '$lib/components/DetailDrawer.svelte';
	import DrawerSection from '$lib/components/drawer/DrawerSection.svelte';
	import KVRow from '$lib/components/drawer/KVRow.svelte';
	import type { DrawerTab } from '$lib/components/DetailDrawer.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import BarList, { type BarItem } from '$lib/components/ui/BarList.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import Who from '$lib/components/ui/Who.svelte';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import Donut from '$lib/components/ui/charts/Donut.svelte';
	import Ring from '$lib/components/ui/charts/Ring.svelte';
	import type { SeverityLevel } from '$lib/utils/severity';
	import { registerPageRefresh, outcome, createLoadGuard, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';

	import {
		getFleetSummary,
		getPrivacyReport,
		getCommunicationMap,
		getActivityTimeline,
		getProtocolAudit,
		getNetworkIsolation,
		getManufacturerProfiles,
	} from '$lib/api/iot';
	import type {
		FleetSummary, FleetDevice, PrivacyReport, PrivacyDevice,
		CommunicationMap, ActivityTimeline,
		ProtocolAudit, ProtocolDevice, ProtocolFinding,
		NetworkIsolation, IsolationPair,
		ManufacturerProfilesResponse,
	} from '$lib/api/iot';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let fleet = $state<FleetSummary | null>(null);
	let privacy = $state<PrivacyReport | null>(null);
	let protocol = $state<ProtocolAudit | null>(null);
	let isolation = $state<NetworkIsolation | null>(null);
	let manufacturers = $state<ManufacturerProfilesResponse | null>(null);

	let loading = $state(true);
	let selectedRange = $state('24h');

	// Detail drawer state
	let drawerOpen = $state(false);
	let selectedDevice = $state<FleetDevice | null>(null);
	let activeTab = $state('overview');
	let commMapData = $state<CommunicationMap | null>(null);
	let timelineData = $state<ActivityTimeline | null>(null);
	// #96: a failed request says so; once the page has loaded, a null section above means it failed
	let commFailed = $state(false);
	let timelineFailed = $state(false);
	let drawerLoading = $state(false);

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const TIME_RANGES = [
		{ label: '1h', value: '1h' },
		{ label: '6h', value: '6h' },
		{ label: '24h', value: '24h' },
		{ label: '7d', value: '7d' },
	];
	const RANGE_LABEL: Record<string, string> = { '1h': 'last hour', '6h': 'last 6 hours', '24h': 'last 24 hours', '7d': 'last 7 days' };
	const rangeLabel = $derived(RANGE_LABEL[selectedRange] ?? 'last 24 hours');

	const DRAWER_TABS: DrawerTab[] = [
		{ id: 'overview', label: 'Overview' },
		{ id: 'communication', label: 'Comm Map' },
		{ id: 'privacy', label: 'Privacy' },
		{ id: 'protocol', label: 'Protocol' },
		{ id: 'timeline', label: 'Timeline' },
	];

	// ---------------------------------------------------------------------------
	// Time helpers
	// ---------------------------------------------------------------------------

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

	// ---------------------------------------------------------------------------
	// Fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03 UI redesign: fetchAll goes through the page refresh contract
	// (PLAN.md §5.5) with a load guard, so a slow 7 d reply can't overwrite a newer 1 h one
	// async function fetchAll(range: string) {
	// 	loading = true;
	// 	const params = computeTimeParams(range);
	// 	const [fleetRes, privacyRes, protocolRes, isolationRes, mfgRes] = await Promise.allSettled([
	// 		getFleetSummary(params), getPrivacyReport(params), getProtocolAudit(params),
	// 		getNetworkIsolation(params), getManufacturerProfiles(params),
	// 	]);
	// 	fleet = fleetRes.status === 'fulfilled' ? fleetRes.value : null;
	// 	privacy = privacyRes.status === 'fulfilled' ? privacyRes.value : null;
	// 	protocol = protocolRes.status === 'fulfilled' ? protocolRes.value : null;
	// 	isolation = isolationRes.status === 'fulfilled' ? isolationRes.value : null;
	// 	manufacturers = mfgRes.status === 'fulfilled' ? mfgRes.value : null;
	// 	loading = false;
	// }
	// $effect(() => { fetchAll(selectedRange); });
	// OLD CODE END

	// OLD CODE START — one failed endpoint blanked the whole page
	/*
	async function fetchAll(range: string) {
		loading = true;
		const params = computeTimeParams(range);
		try {
			const [fleetRes, privacyRes, protocolRes, isolationRes, mfgRes] = await Promise.all([
				getFleetSummary(params),
				getPrivacyReport(params),
				getProtocolAudit(params),
				getNetworkIsolation(params),
				getManufacturerProfiles(params),
			]);
			fleet = fleetRes;
			privacy = privacyRes;
			protocol = protocolRes;
			isolation = isolationRes;
			manufacturers = mfgRes;
		} catch {
			fleet = null;
			privacy = null;
			protocol = null;
			isolation = null;
			manufacturers = null;
		} finally {
			loading = false;
		}
	}
	*/
	// OLD CODE END

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const params = computeTimeParams(selectedRange);
		loading = true;
		// The getters throw on HTTP errors, so a failed section is null (its error state)
		// instead of fake zeros; a failed fleet summary shows the page's error state.
		const results = await Promise.allSettled([
			getFleetSummary(params),
			getPrivacyReport(params),
			getProtocolAudit(params),
			getNetworkIsolation(params),
			getManufacturerProfiles(params),
		]);
		if (!guard.current(g)) return 'skipped';
		const [fleetRes, privacyRes, protocolRes, isolationRes, mfgRes] = results;
		fleet = fleetRes.status === 'fulfilled' ? fleetRes.value : null;
		privacy = privacyRes.status === 'fulfilled' ? privacyRes.value : null;
		protocol = protocolRes.status === 'fulfilled' ? protocolRes.value : null;
		isolation = isolationRes.status === 'fulfilled' ? isolationRes.value : null;
		manufacturers = mfgRes.status === 'fulfilled' ? mfgRes.value : null;
		loading = false;
		return outcome(results);
	}

	const refresh = registerPageRefresh(load);
	// a newer device's drawer data must not be overwritten by an older device's reply
	const drawerGuard = createLoadGuard();
	onDestroy(() => {
		refresh.unregister();
		drawerGuard.invalidate();
	});

	$effect(() => {
		void selectedRange; // reload when the range changes
		untrack(() => refresh.run());
	});

	async function selectDevice(device: FleetDevice) {
		const g = drawerGuard.begin();
		selectedDevice = device;
		drawerOpen = true;
		activeTab = 'overview';
		drawerLoading = true;
		const params = computeTimeParams(selectedRange);
		// OLD CODE START — #96: one failure blanked both tabs, and each read as "no data for this device"
		// try {
		// 	const [commMap, timeline] = await Promise.all([
		// 		getCommunicationMap(device.mac, params),
		// 		getActivityTimeline(device.mac, params),
		// 	]);
		// 	commMapData = commMap;
		// 	timelineData = timeline;
		// } catch {
		// 	commMapData = null;
		// 	timelineData = null;
		// } finally {
		// 	drawerLoading = false;
		// }
		// OLD CODE END
		const [commMap, timeline] = await Promise.allSettled([
			getCommunicationMap(device.mac, params),
			getActivityTimeline(device.mac, params),
		]);
		if (!drawerGuard.current(g)) return;
		commMapData = commMap.status === 'fulfilled' ? commMap.value : null;
		commFailed = commMap.status === 'rejected';
		timelineData = timeline.status === 'fulfilled' ? timeline.value : null;
		timelineFailed = timeline.status === 'rejected';
		drawerLoading = false;
	}

	function closeDrawer() {
		drawerGuard.begin(); // drop a reply still on its way
		drawerOpen = false;
		selectedDevice = null;
		commMapData = null;
		timelineData = null;
	}

	// ---------------------------------------------------------------------------
	// Derived — Hero ring
	// ---------------------------------------------------------------------------

	// OLD CODE START — NET-158: no score read as 0, grade F
	// let healthScore = $derived(fleet?.health_score ?? 0);
	// let healthGrade = $derived(fleet?.health_grade ?? 'F');
	// OLD CODE END
	// null: no device has enough measured to score
	let healthScore = $derived(fleet?.health_score ?? null);
	let healthGrade = $derived(fleet?.health_grade ?? null);

	function gradeColor(grade: string): string {
		switch (grade) {
			case 'A': return 'var(--ok)';
			case 'B': return 'var(--sev-low)';
			case 'C': return 'var(--sev-medium)';
			case 'D': return 'var(--sev-high)';
			default: return 'var(--sev-critical)';
		}
	}

	// OLD CODE START — 2026-11-03 UI redesign: the half-circle gauge; the system's trust Ring draws the score
	// let gaugeColor = $derived(gradeColor(healthGrade));
	// let gaugeArcPath = $derived.by(() => {
	// 	const pct = Math.min(healthScore / 100, 1);
	// 	const angle = pct * 180;
	// 	const rad = (angle * Math.PI) / 180;
	// 	const endX = 90 - 75 * Math.cos(rad);
	// 	const endY = 90 - 75 * Math.sin(rad);
	// 	const largeArc = angle > 180 ? 1 : 0;
	// 	return `M 15 90 A 75 75 0 ${largeArc} 1 ${endX} ${endY}`;
	// });
	// let heroSubtitle = $derived(fleet?.subtitle || 'Scanning your smart home...');
	// let sortedDevices = $derived.by(() => {
	// 	if (!fleet?.devices) return [];
	// 	return [...fleet.devices].sort((a, b) => a.score - b.score);
	// });
	// OLD CODE END
	let heroSubtitle = $derived(fleet?.subtitle || 'Scanning your smart home…');
	// the table opens worst trust score first (initialSort), as the old grid did
	const fleetDevices = $derived(fleet?.devices ?? []);

	// ---------------------------------------------------------------------------
	// Derived — Findings feed
	// ---------------------------------------------------------------------------

	interface Finding {
		id: string;
		severity: string;
		description: string;
		deviceName: string;
		deviceMac: string;
		category: 'Privacy' | 'Security' | 'Behavior';
		timestamp: string;
	}

	let findings = $derived.by((): Finding[] => {
		const items: Finding[] = [];
		let idx = 0;

		// Protocol audit findings
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

		// Privacy findings from privacy report
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
				// OLD CODE START — 2026-11-01: fired for devices with only local chatter (N/A)
				// if (dev.encryption_ratio < 0.9) {
				// OLD CODE END
				if (dev.encryption_applicable !== false && dev.encryption_ratio < 0.9) {
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

		// Sort by severity (high first)
		const sevOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
		items.sort((a, b) => (sevOrder[a.severity] ?? 4) - (sevOrder[b.severity] ?? 4));
		return items;
	});

	// #96: findings come from the privacy and protocol checks; a failed one is not "healthy"
	const checksFailed = $derived(
		privacy === null && protocol === null ? 'privacy or protocols' : privacy === null ? 'privacy' : protocol === null ? 'protocols' : null,
	);
	const CATEGORY_LABEL: Record<Finding['category'], string> = { Privacy: 'Privacy', Security: 'Security', Behavior: 'Behaviour' };

	// ---------------------------------------------------------------------------
	// Derived — Manufacturer bar items
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03 UI redesign: HorizontalBarList items, each coloured by grade
	// let mfgBarItems = $derived.by((): BarItem[] => {
	// 	if (!manufacturers?.manufacturers) return [];
	// 	const mfgs = [...manufacturers.manufacturers].sort((a, b) => a.avg_trust_score - b.avg_trust_score);
	// 	const max = Math.max(...mfgs.map(m => m.avg_trust_score), 1);
	// 	return mfgs.map(m => ({
	// 		key: m.name, label: m.name, value: m.avg_trust_score,
	// 		formattedValue: `${Math.round(m.avg_trust_score)}`, color: gradeColor(m.avg_trust_grade),
	// 		secondaryValue: `${m.device_count} device${m.device_count !== 1 ? 's' : ''}`,
	// 	}));
	// });
	// OLD CODE END
	// OLD CODE START — NET-158: a vendor with no scored device has no score (null)
	// let mfgBarItems = $derived.by((): BarItem[] => {
	// 	if (!manufacturers?.manufacturers) return [];
	// 	return [...manufacturers.manufacturers]
	// 		.sort((a, b) => a.avg_trust_score - b.avg_trust_score)
	// 		.map((m) => ({
	// 			key: m.name, label: m.name, value: m.avg_trust_score,
	// 			display: `${Math.round(m.avg_trust_score)}`,
	// 			detail: `grade ${m.avg_trust_grade} · ${m.device_count} device${m.device_count !== 1 ? 's' : ''}`,
	// 		}));
	// });
	// OLD CODE END
	let mfgBarItems = $derived.by((): BarItem[] => {
		if (!manufacturers?.manufacturers) return [];
		// worst first, unscored vendors last
		return [...manufacturers.manufacturers]
			.sort((a, b) => (a.avg_trust_score ?? Infinity) - (b.avg_trust_score ?? Infinity))
			.map((m) => ({
				key: m.name,
				label: m.name,
				value: m.avg_trust_score ?? 0,
				display: m.avg_trust_score === null ? '—' : `${Math.round(m.avg_trust_score)}`,
				detail: [
					m.avg_trust_grade === null ? 'not enough measured' : `grade ${m.avg_trust_grade}`,
					`from ${m.scored_device_count} of ${m.device_count} device${m.device_count !== 1 ? 's' : ''}`,
				].join(' · '),
			}));
	});

	// ---------------------------------------------------------------------------
	// Derived — Drawer device data
	// ---------------------------------------------------------------------------

	let selectedPrivacy = $derived.by((): PrivacyDevice | null => {
		if (!privacy?.devices || !selectedDevice) return null;
		return privacy.devices.find(d => d.mac === selectedDevice!.mac) ?? null;
	});

	let selectedProtocol = $derived.by((): ProtocolDevice | null => {
		if (!protocol?.devices || !selectedDevice) return null;
		return protocol.devices.find(d => d.mac === selectedDevice!.mac) ?? null;
	});

	// OLD CODE START — 2026-11-03 UI redesign: HorizontalBarList, DonutChart and TimeSeriesChart data;
	// BarList, Donut and AreaChart take plain items and series
	// let commBarItems = …  (label, formattedValue, colour by baseline, IN BASELINE / NEW badge)
	// let trackerBarItems = …  (domain, query count, red)
	// let privacyDonutSegments = …  (Encrypted green / Unencrypted red, in %)
	// let timelineChartData = $derived(timelineData?.buckets.map(b => ({ time: b.time, value: b.connections })) ?? []);
	// OLD CODE END
	let commBarItems = $derived.by((): BarItem[] => {
		if (!commMapData?.destinations) return [];
		const dests = [...commMapData.destinations].sort((a, b) => (b.bytes_sent + b.bytes_received) - (a.bytes_sent + a.bytes_received));
		return dests.slice(0, 20).map(d => ({
			key: d.ip,
			label: d.hostname || d.ip,
			value: d.bytes_sent + d.bytes_received,
			display: formatBytes(d.bytes_sent + d.bytes_received),
			// OLD CODE START — NET-158: with no baseline every destination read "new"
			// detail: [d.country, d.in_baseline ? 'in baseline' : 'new'].filter(Boolean).join(' · '),
			// OLD CODE END
			detail: [d.country, d.in_baseline === null ? null : d.in_baseline ? 'in baseline' : 'new'].filter(Boolean).join(' · '),
		}));
	});
	const newNotChecked = $derived(commMapData?.destinations.some((d) => d.in_baseline === null) ?? false);

	let trackerBarItems = $derived.by((): BarItem[] => {
		if (!selectedPrivacy?.tracker_domains) return [];
		return selectedPrivacy.tracker_domains.map(t => ({
			key: t.domain,
			label: t.domain,
			value: t.query_count,
			display: `${t.query_count}`,
			detail: 'lookups',
		}));
	});

	let encryptedPct = $derived(selectedPrivacy ? Math.round(selectedPrivacy.encryption_ratio * 100) : 0);

	const timelineBuckets = $derived(timelineData?.buckets ?? []);
	const busiestBucket = $derived(timelineBuckets.reduce((best, b, i) => (b.connections > (timelineBuckets[best]?.connections ?? -1) ? i : best), -1));

	// OLD CODE START — 2026-11-03 UI redesign: the hand-built isolation and protocol tables' sorts;
	// DataTable sorts every column. (The protocol sort ranked critical 0, so its first descending
	// click put info on top; the severity column now ranks higher-is-worse.)
	// let isoSortField = $state<string>('connection_count');
	// let isoSortDir = $state<'asc' | 'desc'>('desc');
	// function toggleIsoSort(field: string) { … }
	// let sortedIsolationPairs = $derived.by(() => { … compareValues … riskRank … });
	// let protoSortField = $state<string>('severity');
	// let protoSortDir = $state<'asc' | 'desc'>('desc');
	// function toggleProtoSort(field: string) { … }
	// let sortedProtocolFindings = $derived.by(() => { … sevOrder critical 0 … });
	// OLD CODE END
	const RISK_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
	const protocolFindings = $derived(
		(selectedProtocol?.findings ?? []).map((f, i): ProtocolFinding & { key: string } => ({ ...f, key: `${f.type}-${f.port}-${i}` })),
	);

	// ---------------------------------------------------------------------------
	// Formatters
	// ---------------------------------------------------------------------------

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
		if (!dateStr) return '—';
		const diff = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	// OLD CODE START — 2026-11-03 UI redesign: dots, badges and tags coloured by hand; SeverityPill carries
	// colour, shape and word, and category tags are neutral
	// function severityColor(severity: string): string {
	// 	switch (severity) {
	// 		case 'critical': return 'var(--sev-critical)';
	// 		case 'high': return 'var(--sev-high)';
	// 		case 'medium': return 'var(--sev-medium)';
	// 		case 'low': return 'var(--sev-low)';
	// 		case 'info': return 'var(--sev-info)';
	// 		default: return 'var(--text-muted)';
	// 	}
	// }
	// function severityBadgeClass(severity: string): string {
	// 	switch (severity) {
	// 		case 'critical': return 'severity-critical';
	// 		case 'high': return 'severity-high';
	// 		case 'medium': return 'severity-medium';
	// 		case 'low': return 'severity-low';
	// 		case 'info': return 'severity-info';
	// 		default: return '';
	// 	}
	// }
	// function categoryColor(cat: string): string {
	// 	switch (cat) {
	// 		case 'Privacy': return 'var(--purple)';
	// 		case 'Security': return 'var(--red)';
	// 		case 'Behavior': return 'var(--amber)';
	// 		default: return 'var(--text-muted)';
	// 	}
	// }
	// OLD CODE END

	/** A severity the daemon sent, or null for anything else (shown as its raw word). */
	function asLevel(severity: string): SeverityLevel | null {
		return severity in RISK_RANK ? (severity as SeverityLevel) : null;
	}

	function scoreToGrade(score: number): string {
		if (score >= 90) return 'A';
		if (score >= 75) return 'B';
		if (score >= 60) return 'C';
		if (score >= 40) return 'D';
		return 'F';
	}

	function openFindingDevice(finding: Finding) {
		const dev = fleet?.devices.find(d => d.mac === finding.deviceMac);
		if (dev) selectDevice(dev);
	}

	// a pillar with no measured check is null and shows "—"
	const scoreRows = (s: { privacy_score: number | null; security_score: number | null; behavior_score: number | null }) => [
		{ label: 'Privacy', value: s.privacy_score, colour: 1 },
		{ label: 'Security', value: s.security_score, colour: 2 },
		{ label: 'Behaviour', value: s.behavior_score, colour: 3 },
	];

	// Every column sorts (design system); the cell snippets are at the top of the markup
	const deviceColumns: Column<FleetDevice>[] = [
		{ key: 'name', label: 'Device', cell: deviceCell },
		{ key: 'manufacturer', label: 'Manufacturer' },
		{ key: 'score', label: 'Trust', numeric: true, cell: trustCell },
		{ key: 'privacy_score', label: 'Privacy', cell: privacyCell },
		{ key: 'encryption_pct', label: 'Encrypted', numeric: true, cell: encryptedCell, sortValue: (d) => (d.encryption_applicable === false ? null : d.encryption_pct) },
		// OLD CODE START — NET-158: 0 for a device whose anomalies were never checked
		// { key: 'anomaly_count', label: 'Anomalies', numeric: true },
		// OLD CODE END
		{ key: 'anomaly_count', label: 'Anomalies', numeric: true, cell: anomalyCell },
		{ key: 'last_seen', label: 'Last seen', cell: seenCell, sortValue: (d) => (d.last_seen ? Date.parse(d.last_seen) : null) },
	];
	const isolationColumns: Column<IsolationPair>[] = [
		{ key: 'iot_device', label: 'IoT device', cell: isoDeviceCell, sortValue: (p) => p.iot_device.name },
		{ key: 'internal_target', label: 'Internal target', cell: targetCell, sortValue: (p) => p.internal_target.hostname ?? p.internal_target.ip },
		{ key: 'risk', label: 'Risk', cell: riskCell, sortValue: (p) => RISK_RANK[p.risk] ?? -1 },
		{ key: 'connection_count', label: 'Connections', numeric: true, cell: isoConnCell },
		{ key: 'ports', label: 'Ports', cell: portsCell, sortValue: (p) => p.ports.join(', ') },
		{ key: 'description', label: 'Description', cell: descCell },
	];
	const protocolColumns: Column<ProtocolFinding & { key: string }>[] = [
		{ key: 'type', label: 'Type', cell: typeCell },
		{ key: 'severity', label: 'Severity', cell: findingSevCell, sortValue: (f) => RISK_RANK[f.severity] ?? -1 },
		{ key: 'port', label: 'Port', numeric: true, cell: findingPortCell },
		{ key: 'description', label: 'Description', cell: findingDescCell },
	];
</script>

{#snippet grade(letter: string, small = false)}
	<span class={['grade', small && 'sm']} style:--g={gradeColor(letter)}>{letter}</span>
{/snippet}
{#snippet severity(level: string)}
	{@const known = asLevel(level)}
	{#if known}<SeverityPill level={known} />{:else}<span class="chip">{level}</span>{/if}
{/snippet}
{#snippet deviceCell(d: FleetDevice)}<Who name={d.name} ip={d.ip ?? undefined} category="iot" />{/snippet}
<!-- OLD CODE START — NET-158: score, grade and percentage could be null (not enough measured, N/A)
{#snippet trustCell(d: FleetDevice)}<span class="trust-cell">{@render grade(d.grade, true)}<span class="num">{d.score}</span></span>{/snippet}
{#snippet privacyCell(d: FleetDevice)}{@render grade(scoreToGrade(d.privacy_score), true)}{/snippet}
{#snippet encryptedCell(d: FleetDevice)}{d.encryption_applicable === false ? 'N/A' : `${d.encryption_pct}%`}{/snippet}
OLD CODE END -->
{#snippet trustCell(d: FleetDevice)}
	{#if d.score === null || d.grade === null}<span class="dim">— Not enough measured</span>
	{:else}<span class="trust-cell">{@render grade(d.grade, true)}<span class="num">{d.score}</span></span>{/if}
{/snippet}
{#snippet privacyCell(d: FleetDevice)}{#if d.privacy_score === null}—{:else}{@render grade(scoreToGrade(d.privacy_score), true)}{/if}{/snippet}
{#snippet encryptedCell(d: FleetDevice)}{d.encryption_applicable === false || d.encryption_pct === null ? 'N/A' : `${d.encryption_pct}%`}{/snippet}
{#snippet anomalyCell(d: FleetDevice)}{d.anomaly_count === null ? 'Not checked' : d.anomaly_count}{/snippet}
{#snippet seenCell(d: FleetDevice)}{timeAgo(d.last_seen)}{/snippet}
{#snippet isoDeviceCell(p: IsolationPair)}<Who name={p.iot_device.name} ip={p.iot_device.ip} category="iot" />{/snippet}
{#snippet targetCell(p: IsolationPair)}<span class="mono">{p.internal_target.hostname ?? p.internal_target.ip}</span>{/snippet}
{#snippet riskCell(p: IsolationPair)}{@render severity(p.risk)}{/snippet}
{#snippet isoConnCell(p: IsolationPair)}{formatNumber(p.connection_count)}{/snippet}
{#snippet portsCell(p: IsolationPair)}<span class="mono">{p.ports.join(', ')}</span>{/snippet}
{#snippet descCell(p: IsolationPair)}<span class="trunc" title={p.description}>{p.description}</span>{/snippet}
{#snippet typeCell(f: ProtocolFinding)}<span class="tag">{f.type.replace(/_/g, ' ')}</span>{/snippet}
{#snippet findingSevCell(f: ProtocolFinding)}{@render severity(f.severity)}{/snippet}
{#snippet findingPortCell(f: ProtocolFinding)}<span class="mono">{f.port ?? '—'}</span>{/snippet}
{#snippet findingDescCell(f: ProtocolFinding)}<span class="trunc" title={f.description}>{f.description}</span>{/snippet}
{#snippet scores(rows: { label: string; value: number | null; colour: number }[])}
	<ul class="score-rows">
		{#each rows as row (row.label)}
			<li>
				<span>{row.label}</span><b>{row.value ?? '—'}</b>
				<span class="bar-track" aria-hidden="true"><span class="bar-fill c-d{row.colour}" style:--w="{Math.max(0, Math.min(100, row.value ?? 0))}%"></span></span>
			</li>
		{/each}
	</ul>
{/snippet}

<svelte:head>
	<title>IoT Trust Score | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">IoT trust score</h1>
		<p class="page-sub">Smart home device health, privacy and security</p>
	</div>
	<div class="head-actions">
		<Pills ariaLabel="Time range" options={TIME_RANGES} bind:value={selectedRange} />
	</div>
</div>

{#if !fleet}
	<Card title="Smart home health" sub="Trust score out of 100 · {rangeLabel}">
		{#if loading}
			<CardState state="loading" title="Scanning IoT devices" />
		{:else}
			<!-- OLD CODE START — 2026-11-03 UI redesign: "Failed to load IoT data." (the system's error pattern is "Couldn't load …") -->
			<!-- OLD CODE END -->
			<CardState
				state="error"
				title="Couldn't load IoT data: the request failed."
				message="Check that the daemon is running and OpenSearch is accessible."
				onaction={() => refresh.run()}
			/>
		{/if}
	</Card>
{:else}
	<div class="grid">
		<KpiCard class="c-3" label="IoT devices" icon="iot" value={fleet.device_count} sub="Classified devices" note={rangeLabel} />
		<!-- OLD CODE START — NET-158: "0 · All clear" when no device had a baseline (nothing was
		     checked), over a 1 h check labelled with the page's range; "0 · No trackers" counted only
		     devices with more than 5 trackers, while Findings lists every tracker
		<KpiCard class="c-3" label="Anomalies" icon="warn" value={fleet.anomaly_count} sub={fleet.anomaly_count === 0 ? 'All clear' : 'Need review'} note={rangeLabel} />
		<KpiCard class="c-3" label="Privacy concerns" icon="threats" value={fleet.privacy_concerns} sub={fleet.privacy_concerns === 0 ? 'No trackers' : 'Tracker domains found'} note={rangeLabel} />
		OLD CODE END -->
		<KpiCard class="c-3" label="Anomalies" icon="warn"
			value={fleet.anomalies_checked === 0 ? '—' : fleet.anomaly_count}
			sub={fleet.anomalies_checked === 0 ? 'Not checked: no device has a baseline' : `${fleet.anomalies_checked} of ${fleet.device_count} devices checked`}
			note="last hour" />
		<KpiCard class="c-3" label="Privacy concerns" icon="threats" value={fleet.privacy_concerns}
			sub={fleet.privacy_concerns === 0 ? 'None with over 5 tracker domains' : 'Devices with over 5 tracker domains'} note={rangeLabel} />
		<KpiCard class="c-3" label="Unencrypted" icon="certs" value={fleet.unencrypted_count} sub={fleet.unencrypted_count === 0 ? 'Fully encrypted' : 'Devices using plaintext'} note={rangeLabel} />

		<Card class="c-4" hero title="Smart home health" sub="Trust score out of 100 · from {fleet.scored_device_count} of {fleet.device_count} devices · {rangeLabel}">
			<div class="trust-top">
				<!-- OLD CODE START — NET-158: no scored device drew 0, grade F
				<Ring value={healthScore} ariaLabel="Smart home health {healthScore} of 100, grade {healthGrade}" />
				OLD CODE END -->
				{#if healthScore !== null && healthGrade !== null}
					<Ring value={healthScore} ariaLabel="Smart home health {healthScore} of 100, grade {healthGrade}" />
				{:else}
					<div class="foot-stat"><b>—</b>Not enough measured</div>
				{/if}
				<div class="trust-side">
					{#if healthGrade !== null}{@render grade(healthGrade)}{/if}
					<p class="trust-plain">{heroSubtitle}</p>
				</div>
			</div>
			{@render scores(scoreRows(fleet))}
		</Card>

		<Card class="c-8" title="Findings" sub="From the privacy and protocol checks · {rangeLabel}">
			{#snippet actions()}
				{#if findings.length > 0}<span class="chip is-warn">{findings.length} findings</span>{/if}
			{/snippet}
			{#if checksFailed && findings.length === 0}
				<CardState state="error" title="Couldn't check {checksFailed}: the request failed." onaction={() => refresh.run()} />
			{:else if findings.length === 0}
				<!-- OLD CODE START — 2026-11-03 UI redesign: "No findings -- all devices look healthy." -->
				<!-- OLD CODE END -->
				<CardState state="empty" icon="check" title="No findings. All devices look healthy." />
			{:else}
				{#if checksFailed}<p class="note">Couldn't check {checksFailed}: the request failed.</p>{/if}
				<ul class="findings">
					{#each findings.slice(0, 20) as finding (finding.id)}
						<li class="finding">
							{@render severity(finding.severity)}
							<div class="finding-body">
								<p>{finding.description}</p>
								<div class="finding-meta">
									<button class="link finding-device" type="button" onclick={() => openFindingDevice(finding)}>{finding.deviceName}</button>
									<span class="tag">{CATEGORY_LABEL[finding.category]}</span>
								</div>
							</div>
						</li>
					{/each}
				</ul>
				{#if findings.length > 20}
					<p class="note">+{findings.length - 20} more findings</p>
				{/if}
			{/if}
		</Card>

		<Card class="c-12" title="Device trust scores" sub="Out of 100 · worst first · {rangeLabel}">
			{#snippet actions()}
				{#if fleetDevices.length > 0}<span class="chip">{fleetDevices.length} devices</span>{/if}
			{/snippet}
			{#if fleetDevices.length > 0}
				<DataTable
					ariaLabel="Device trust scores"
					rows={fleetDevices}
					rowKey={(d) => d.mac}
					initialSort={{ key: 'score', dir: 'asc' }}
					onrowactivate={selectDevice}
					rowLabel={(d) => `Open ${d.name}`}
					selectedKey={drawerOpen ? selectedDevice?.mac : undefined}
					columns={deviceColumns}
				/>
			{:else}
				<CardState
					state="empty"
					icon="iot"
					title="No IoT devices classified yet."
					message="Devices are classified from manufacturer fingerprints (Ring, Nest, Wyze and others)."
				/>
			{/if}
		</Card>

		<!-- OLD CODE START — NET-158: an average over every device, scored or not
		<Card class="c-4" title="Manufacturer profiles" sub="Average trust score out of 100 · worst first">
		OLD CODE END -->
		<Card class="c-4" title="Manufacturer profiles" sub="Trust score out of 100 over scored devices · worst first">
			{#snippet actions()}
				{#if manufacturers?.manufacturers?.length}<span class="chip">{manufacturers.manufacturers.length} vendors</span>{/if}
			{/snippet}
			{#if manufacturers === null}
				<CardState state="error" title="Couldn't load manufacturer profiles: the request failed." onaction={() => refresh.run()} />
			{:else if mfgBarItems.length > 0}
				<BarList items={mfgBarItems} />
			{:else}
				<CardState state="empty" icon="iot" title="No manufacturer data available." />
			{/if}
		</Card>

		<Card class="c-8" title="Network isolation" sub="IoT devices talking to other local devices · {rangeLabel}">
			{#snippet actions()}
				{#if isolation}
					<span class="trust-cell"><span class="chip num">{isolation.segmentation_score}/100</span>{@render grade(isolation.segmentation_grade, true)}</span>
				{/if}
			{/snippet}
			{#if isolation === null}
				<CardState state="error" title="Couldn't check for cross-segment IoT communication: the request failed." onaction={() => refresh.run()} />
			{:else if isolation.pairs.length === 0}
				<CardState state="empty" icon="check" title="No cross-segment IoT communication detected." />
			{:else}
				<DataTable
					ariaLabel="Network isolation"
					rows={isolation.pairs}
					rowKey={(p) => `${p.iot_device.mac}-${p.internal_target.ip}`}
					initialSort={{ key: 'connection_count', dir: 'desc' }}
					columns={isolationColumns}
				/>
				{#if isolation.recommendation}
					<div class="todo"><b>What to do</b>{isolation.recommendation}</div>
				{/if}
			{/if}
		</Card>
	</div>
{/if}

<!-- ==================================================================
     Device Detail Drawer
     ================================================================== -->
<DetailDrawer
	open={drawerOpen}
	title={selectedDevice?.name ?? 'Device Details'}
	subtitle={selectedDevice?.mac ?? ''}
	tabs={DRAWER_TABS}
	{activeTab}
	onclose={closeDrawer}
	ontabchange={(tabId) => (activeTab = tabId)}
>
	{#snippet children()}
		{#if drawerLoading && activeTab !== 'overview'}
			<CardState state="loading" title="Loading device data" />
		{:else if selectedDevice}
			<!-- Tab 1: Overview -->
			{#if activeTab === 'overview'}
				<DrawerSection title="Trust Score Breakdown">
					{@render scores(scoreRows(selectedDevice))}
				</DrawerSection>

				<DrawerSection title="Device Info">
					<KVRow label="IP Address" value={selectedDevice.ip} mono copyable />
					<KVRow label="MAC Address" value={selectedDevice.mac} mono copyable />
					<KVRow label="Manufacturer" value={selectedDevice.manufacturer} />
					<!-- OLD CODE START — NET-158: score and grade can be null; the coverage is stated
					<KVRow label="Trust Grade" value={`${selectedDevice.grade} (${selectedDevice.score}/100)`} />
					OLD CODE END -->
					<KVRow label="Trust Grade" value={selectedDevice.score === null ? 'Not enough measured' : `${selectedDevice.grade} (${selectedDevice.score}/100)`} />
					<KVRow label="Measured" value={`from ${selectedDevice.checks_available} of ${selectedDevice.checks_total} checks (${selectedDevice.coverage} of 100 points)`} />
					<KVRow label="Last Seen" value={selectedDevice.last_seen ? timeAgo(selectedDevice.last_seen) : '—'} />
				</DrawerSection>

				<DrawerSection title="Quick Stats">
					<!-- OLD CODE START — NET-158: null encryption and anomalies
					<KVRow label="Encryption" value={selectedDevice.encryption_applicable === false ? 'N/A' : `${selectedDevice.encryption_pct}%`} mono />
					<KVRow label="Anomalies" value={String(selectedDevice.anomaly_count)} mono />
					OLD CODE END -->
					<KVRow label="Encryption" value={selectedDevice.encryption_applicable === false || selectedDevice.encryption_pct === null ? 'N/A' : `${selectedDevice.encryption_pct}%`} mono />
					<KVRow label="Trackers" value={String(selectedDevice.tracker_count)} mono />
					<KVRow label="Anomalies" value={selectedDevice.anomaly_count === null ? 'Not checked' : String(selectedDevice.anomaly_count)} mono />
				</DrawerSection>

			<!-- Tab 2: Communication Map -->
			{:else if activeTab === 'communication'}
				<DrawerSection title="Top Destinations">
					{#if commBarItems.length > 0}
						{#if newNotChecked}<p class="note">New destinations not checked: this device has no baseline yet.</p>{/if}
						<BarList items={commBarItems} />
					{:else if commFailed}
						<p class="note">Couldn't load this device's destinations: the request failed.</p>
					{:else}
						<p class="note">No communication data for this device.</p>
					{/if}
				</DrawerSection>

			<!-- Tab 3: Privacy -->
			{:else if activeTab === 'privacy'}
				{#if selectedPrivacy}
					<!-- NET-158: the trust score's privacy pillar, the same figure as the Overview tab -->
					<DrawerSection title="Privacy Grade">
						{#if selectedPrivacy.privacy_grade === null || selectedPrivacy.privacy_score === null}
							<p class="note">— Not enough measured</p>
						{:else}
							<div class="trust-cell">
								{@render grade(selectedPrivacy.privacy_grade)}
								<span class="num">{selectedPrivacy.privacy_score}/100</span>
							</div>
						{/if}
					</DrawerSection>

					{#if selectedPrivacy.tracker_lookup_share !== null}
						<DrawerSection title="Tracker lookups">
							<div class="foot-stat"><b>{Math.round(selectedPrivacy.tracker_lookup_share * 100)}%</b>share of lookups to trackers</div>
						</DrawerSection>
					{/if}

					{#if trackerBarItems.length > 0}
						<DrawerSection title="Tracker Domains ({selectedPrivacy.tracker_count})">
							<BarList items={trackerBarItems} />
						</DrawerSection>
					{/if}

					<DrawerSection title="Encryption">
						<!-- OLD CODE START — 2026-11-03 UI redesign: the donut drew 0% encrypted for a device with only local chatter -->
						<!-- OLD CODE END -->
						{#if selectedPrivacy.encryption_applicable === false}
							<p class="note">N/A: only local traffic (DNS, mDNS, NTP) was seen, so there is nothing to encrypt.</p>
						{:else}
							<Donut
								items={[
									{ key: 'encrypted', label: 'Encrypted', value: encryptedPct },
									{ key: 'unencrypted', label: 'Unencrypted', value: 100 - encryptedPct },
								]}
								total={encryptedPct}
								centreLabel="% encrypted"
								formatValue={(n) => `${n}%`}
								ariaLabel="{encryptedPct}% of connections encrypted"
							/>
						{/if}
					</DrawerSection>

					<DrawerSection title="Phone Home Frequency">
						<div class="foot-stat"><b>{Math.round(selectedPrivacy.phone_home_per_hour)}</b>requests per hour</div>
					</DrawerSection>
				{:else if privacy === null}
					<p class="note">Couldn't load the privacy report: the request failed.</p>
				{:else}
					<p class="note">No privacy data available for this device.</p>
				{/if}

			<!-- Tab 4: Protocol Audit -->
			{:else if activeTab === 'protocol'}
				{#if selectedProtocol && selectedProtocol.findings.length > 0}
					<DrawerSection title="Protocol Findings ({selectedProtocol.findings.length})">
						<DataTable
							ariaLabel="Protocol findings"
							rows={protocolFindings}
							rowKey={(f) => f.key}
							initialSort={{ key: 'severity', dir: 'desc' }}
							columns={protocolColumns}
						/>
					</DrawerSection>
				{:else if protocol === null}
					<DrawerSection title="Protocol Audit">
						<p class="note">Couldn't run the protocol audit: the request failed.</p>
					</DrawerSection>
				{:else}
					<DrawerSection title="Protocol Audit">
						<p class="ok-line"><span class="chip is-ok">Compliant</span>All protocols within expected parameters.</p>
					</DrawerSection>
				{/if}

			<!-- Tab 5: Activity Timeline -->
			{:else if activeTab === 'timeline'}
				<DrawerSection title="Connections Over Time">
					{#if busiestBucket >= 0}
						<AreaChart
							series={[{ key: 'connections', label: 'Connections', colour: 1, points: timelineBuckets.map((b) => ({ t: b.time, v: b.connections })) }]}
							formatX={(t) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
							formatY={(n) => formatNumber(Math.round(n))}
							formatTip={(i) => `${new Date(timelineBuckets[i].time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ${formatNumber(timelineBuckets[i].connections)} connections`}
							highlightIndex={busiestBucket}
							ariaLabel="Busiest at {new Date(timelineBuckets[busiestBucket].time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}, with {formatNumber(timelineBuckets[busiestBucket].connections)} connections"
							height={200}
						/>
					{:else if timelineFailed}
						<p class="note">Couldn't load this device's activity: the request failed.</p>
					{:else}
						<p class="note">No activity data available.</p>
					{/if}
				</DrawerSection>
			{/if}
		{/if}
	{/snippet}
</DetailDrawer>

<style>
	/* Layout glue the system lacks */
	.grade { color: var(--g); background: color-mix(in srgb, var(--g) 14%, transparent); }
	.grade.sm { width: 26px; height: 26px; border-radius: var(--r-sm); font-size: var(--text-sm); }
	.trust-side { display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-2); min-width: 0; }
	.trust-cell { display: inline-flex; align-items: center; gap: var(--sp-2); }
	.note { color: var(--text-2); font-size: var(--text-sm); }
	.findings { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
	.finding { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: var(--sp-3); align-items: start; padding: var(--sp-3) 0; }
	.finding + .finding { border-top: 1px solid var(--line); }
	.finding-body { display: flex; flex-direction: column; gap: var(--sp-1); font-size: var(--text-sm); min-width: 0; }
	.finding-meta { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
	.finding-device { background: none; border: 0; padding: 0; cursor: pointer; }
	.ok-line { display: flex; align-items: center; gap: var(--sp-2); font-size: var(--text-sm); color: var(--text-2); }
	.todo { margin-top: var(--sp-4); }
</style>
