<script lang="ts">
	/**
	 * Certificates (NET-154): which connections got a certificate that should worry you, and when
	 * your own devices' certificates run out. Every figure comes from one complete pass over the
	 * window's TLS sessions (/api/certificates/overview); lists are paged here, never the counts.
	 */
	import { onDestroy, onMount, tick } from 'svelte';
	import {
		getCertificateOverview,
		type CertDevice,
		type CertFinding,
		type CertificateOverview,
		type CertSite,
		type FindingKind,
	} from '$lib/api/certificates';
	import { getRegistryDevices } from '$lib/api/devices-registry';
	import { outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { namesByIp } from '$lib/utils/device-names';
	import { loadFailed } from '$lib/utils/load-failed';
	import { sortRows, type SortDir } from '$lib/utils/table-sort.svelte';
	import AlertRow from '$lib/components/ui/AlertRow.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import { shortSeen } from '../alerts/alert-view';
	import CertDetail from './CertDetail.svelte';
	import {
		RANGES,
		deviceName,
		deviceVerification,
		findingEvidence,
		findingTitle,
		formatWhen,
		runsOut,
		runsOutSentence,
		siteMatches,
		siteName,
		siteStatus,
		staleNotice,
		whoUsed,
		type RangeOption,
		type RangeValue,
	} from './cert-view';

	const PAGE_SIZE = 25;
	const FINDINGS_SHOWN = 10;
	const LIST_FILTERS = [
		{ value: 'all', label: 'All' },
		{ value: 'look', label: 'Needs a look' },
		{ value: 'devices', label: 'Your devices' },
	] as const;
	type ListFilter = (typeof LIST_FILTERS)[number]['value'];

	let rangeValue = $state<RangeValue>('7d');
	let loaded = $state<{ data: CertificateOverview; range: RangeOption; at: Date } | null>(null);
	let loading = $state(true);
	let failure = $state<{ range: RangeOption; reason: string } | null>(null);
	let names = $state<ReadonlyMap<string, string>>(new Map());
	let selected = $state<{ type: 'finding' | 'site'; id: string } | null>(null);
	let listFilter = $state<ListFilter>('all');
	let query = $state('');
	let page = $state(1);
	let sortKey = $state('sessions');
	let sortDir = $state<SortDir>('desc');
	let showAllFindings = $state(false);
	let showQuiet = $state(false);

	const refresh = registerPageRefresh(load);
	onMount(() => {
		refresh.run();
	});
	onDestroy(refresh.unregister);

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const range = RANGES.find((r) => r.value === rangeValue) ?? RANGES[1];
		const to = new Date();
		const from = new Date(to.getTime() - range.hours * 3_600_000);
		loading = true;
		const results = await Promise.allSettled([
			getCertificateOverview(from.toISOString(), to.toISOString()),
			getRegistryDevices({ limit: 200 }),
		]);
		if (!guard.current(g)) return 'skipped';
		const [overview, registry] = results;
		// Without the registry, devices show by address
		if (registry.status === 'fulfilled') names = namesByIp(registry.value.devices);
		if (overview.status === 'fulfilled') {
			loaded = { data: overview.value, range, at: new Date() };
			failure = null;
		} else {
			failure = { range, reason: overview.reason instanceof Error ? overview.reason.message : '' };
		}
		loading = false;
		return outcome(results);
	}

	function changeRange(value: RangeValue) {
		rangeValue = value;
		refresh.run();
	}

	const fmt = (n: number): string => n.toLocaleString('en-GB');
	const data = $derived(loaded?.data ?? null);
	const words = $derived(loaded?.range.words ?? '');
	const summary = $derived(data?.summary ?? null);

	// The most serious finding per site, for its status (findings arrive most serious first)
	const worstKind = $derived.by(() => {
		const kinds = new Map<string, FindingKind>();
		for (const f of data?.findings ?? []) if (!kinds.has(f.site_id)) kinds.set(f.site_id, f.kind);
		return kinds;
	});

	const findings = $derived(data?.findings ?? []);
	const truncated = $derived(
		data
			? [
					{ what: 'findings', cut: data.findings_truncated, total: data.findings_total },
					{ what: 'sites', cut: data.sites_truncated, total: data.sites_total },
					{ what: 'services on your network', cut: data.devices_truncated, total: data.devices_total },
				].filter((t) => t.cut)
			: [],
	);
	const shownFindings = $derived(showAllFindings ? findings : findings.slice(0, FINDINGS_SHOWN));

	const selectedFinding = $derived(selected?.type === 'finding' ? findings.find((f) => f.id === selected?.id) : undefined);
	const selectedSite = $derived(selected?.type === 'site' ? data?.sites.find((s) => s.id === selected?.id) : undefined);

	// --- All certificates: filter, search, then sort the whole list before cutting a page ---

	const SITE_SORT: Record<string, (s: CertSite) => unknown> = {
		site: (s) => siteName(s.name, s.server),
		used_by: (s) => s.clients_total,
		authority: (s) => s.authorities.join(', '),
		certificates: (s) => s.certificates_total,
		sessions: (s) => s.sessions,
		last_seen: (s) => s.last_seen,
		status: (s) => (s.worst === 'high' ? 4 : s.worst === 'medium' ? 3 : s.worst === 'low' ? 2 : s.verified ? 0 : 1),
	};

	const matchingSites = $derived.by(() => {
		const sites = (data?.sites ?? []).filter((s) =>
			listFilter === 'look' ? worstKind.has(s.id) : listFilter === 'devices' ? s.scope === 'local' || s.scope === 'mixed' : true,
		);
		return sortRows(
			sites.filter((s) => siteMatches(s, query, names)),
			SITE_SORT[sortKey] ?? SITE_SORT.sessions,
			sortDir,
		);
	});
	const pageCount = $derived(Math.max(1, Math.ceil(matchingSites.length / PAGE_SIZE)));
	const currentPage = $derived(Math.min(page, pageCount));
	const pageRows = $derived(matchingSites.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE));

	function setListFilter(value: ListFilter) {
		listFilter = value;
		page = 1;
	}

	const siteColumns: Column<CertSite>[] = [
		{ key: 'site', label: 'Site', cell: siteCell },
		{ key: 'used_by', label: 'Used by', cell: usedByCell },
		{ key: 'authority', label: 'Authority', cell: authorityCell },
		{ key: 'certificates', label: 'Certificates', numeric: true, cell: certCountCell },
		{ key: 'sessions', label: 'Sessions', numeric: true, cell: sessionsCell },
		{ key: 'last_seen', label: 'Last seen', cell: lastSeenCell },
		{ key: 'status', label: 'Status', cell: statusCell },
	];

	// --- Your devices' certificates ---

	const deviceColumns: Column<CertDevice>[] = [
		{ key: 'site', label: 'Site', sortValue: (d) => siteName(d.site, d.server), cell: deviceSiteCell },
		{ key: 'device', label: 'Device', sortValue: (d) => deviceName(d.server, names), cell: deviceCell },
		{ key: 'authority', label: 'Authority', cell: deviceAuthorityCell },
		{ key: 'verification', label: 'Verification', sortValue: deviceVerification, cell: verificationCell },
		{ key: 'days_left', label: 'Runs out', numeric: true, cell: runsOutCell },
		{ key: 'sessions', label: 'Sessions', numeric: true, cell: deviceSessionsCell },
		{ key: 'last_seen', label: 'Last seen', cell: deviceLastSeenCell },
	];

	async function openSite(id: string) {
		selected = { type: 'site', id };
		await tick();
		document.getElementById('cert-sites')?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
	}

	const seen = (when: string): string => formatWhen(when);

	// OLD CODE START — 2026-11-05 NET-154: the whole previous page (script, markup and styles). It listed up to
	// 1,000 certificates from x509 records in the window, judged "Expired" against now, and raised a
	// "Potential MITM" banner for any site with two issuers, which big sites have all the time.
	// 	/**
	// 	 * Certificate Inventory — TLS certificate tracking and analysis.
	// 	 *
	// 	 * Shows certificate table with status filtering, hero stats cards,
	// 	 * and detail modal. Alerts on issuer changes (potential MITM).
	// 	 */
	//
	// 	import { onDestroy, onMount } from 'svelte';
	// 	// OLD CODE START — sorting moved into DataTable (utils/table-sort, blanks last both ways)
	// 	// import { compareValues } from '$lib/utils/table-sort.svelte';
	// 	// OLD CODE END
	// 	import {
	// 		getCertificates,
	// 		getExpiringCerts,
	// 		getSelfSignedCerts,
	// 		getIssuerChanges,
	// 		getCertStats,
	// 		type Certificate,
	// 		type IssuerChange,
	// 		type CertStats,
	// 	} from '$lib/api/certificates';
	// 	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	// 	import Card from '$lib/components/ui/Card.svelte';
	// 	import CardState from '$lib/components/ui/CardState.svelte';
	// 	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	// 	import Icon from '$lib/components/ui/Icon.svelte';
	// 	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	// 	import Pills from '$lib/components/ui/Pills.svelte';
	//
	// 	// State
	// 	let certificates = $state<Certificate[]>([]);
	// 	// OLD CODE START — 2026-11-01: stats now include expired_count
	// 	// let stats = $state<CertStats>({ total_certs: 0, expiring_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: '', to: '' });
	// 	// OLD CODE END
	// 	// OLD CODE START — 2026-11-02: null now means the stats couldn't be loaded (cards show a dash)
	// 	// let stats = $state<CertStats>({ total_certs: 0, expiring_count: 0, expired_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: '', to: '' });
	// 	// OLD CODE END
	// 	// OLD CODE START — zeros before the first load read as real counts (PLAN §4.1)
	// 	// let stats = $state<CertStats | null>({ total_certs: 0, expiring_count: 0, expired_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: '', to: '' });
	// 	// OLD CODE END
	// 	let stats = $state<CertStats | null>(null);
	// 	let issuerChanges = $state<IssuerChange[]>([]);
	// 	let loading = $state(true);
	// 	let statusFilter = $state('all');
	// 	let selectedCert = $state<Certificate | null>(null);
	//
	// 	// OLD CODE START — DataTable sorts every column (utils/table-sort: numbers in text by value, blanks last)
	// 	// // Sort state
	// 	// let sortField = $state('domain');
	// 	// let sortDir = $state<'asc' | 'desc'>('asc');
	// 	//
	// 	// function toggleSort(field: string) {
	// 	// 	if (sortField === field) {
	// 	// 		sortDir = sortDir === 'desc' ? 'asc' : 'desc';
	// 	// 	} else {
	// 	// 		sortField = field;
	// 	// 		sortDir = field === 'not_after' ? 'asc' : 'desc';
	// 	// 	}
	// 	// }
	// 	//
	// 	// let sortedCertificates = $derived.by(() => {
	// 	// 	const sorted = [...certificates];
	// 	// 	sorted.sort((a, b) => {
	// 	// 		let aVal: string | number = '';
	// 	// 		let bVal: string | number = '';
	// 	// 		switch (sortField) {
	// 	// 			case 'domain':
	// 	// 				aVal = (a.domain || a.server_name || '').toLowerCase();
	// 	// 				bVal = (b.domain || b.server_name || '').toLowerCase();
	// 	// 				break;
	// 	// 			case 'issuer':
	// 	// 				aVal = (a.issuer || '').toLowerCase();
	// 	// 				bVal = (b.issuer || '').toLowerCase();
	// 	// 				break;
	// 	// 			case 'not_before':
	// 	// 				aVal = a.not_before || '';
	// 	// 				bVal = b.not_before || '';
	// 	// 				break;
	// 	// 			case 'not_after':
	// 	// 				aVal = a.not_after || '';
	// 	// 				bVal = b.not_after || '';
	// 	// 				break;
	// 	// 			case 'status':
	// 	// 				aVal = (a.status || '').toLowerCase();
	// 	// 				bVal = (b.status || '').toLowerCase();
	// 	// 				break;
	// 	// 			case 'source_ip':
	// 	// 				aVal = (a.source_ip || '').toLowerCase();
	// 	// 				bVal = (b.source_ip || '').toLowerCase();
	// 	// 				break;
	// 	// 		}
	// 	// 		// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 	// 		// if (aVal < bVal) return sortDir === 'asc' ? -1 : 1;
	// 	// 		// if (aVal > bVal) return sortDir === 'asc' ? 1 : -1;
	// 	// 		// return 0;
	// 	// 		// OLD CODE END
	// 	// 		if (!aVal !== !bVal) return aVal ? -1 : 1; // a blank (no source IP, no date) goes last both ways
	// 	// 		const cmp = compareValues(aVal, bVal);
	// 	// 		return sortDir === 'asc' ? cmp : -cmp;
	// 	// 	});
	// 	// 	return sorted;
	// 	// });
	// 	//
	// 	// // Load data on mount
	// 	// $effect(() => {
	// 	// 	loadData();
	// 	// });
	// 	// OLD CODE END
	//
	// 	// OLD CODE START — #96: the getters returned [] on failure, read as "No certificates found"
	// 	// and no MITM warning; they now throw
	// 	// async function loadData() {
	// 	// 	loading = true;
	// 	// 	const [certsRes, statsRes, changesRes] = await Promise.all([
	// 	// 		getCertificates(),
	// 	// 		getCertStats(),
	// 	// 		getIssuerChanges(),
	// 	// 	]);
	// 	// 	certificates = certsRes.certificates;
	// 	// 	stats = statsRes;
	// 	// 	issuerChanges = changesRes.changes;
	// 	// 	loading = false;
	// 	// }
	// 	//
	// 	// async function filterByStatus(filter: string) {
	// 	// 	statusFilter = filter;
	// 	// 	loading = true;
	// 	//
	// 	// 	if (filter === 'expiring') {
	// 	// 		const res = await getExpiringCerts(30);
	// 	// 		certificates = res.certificates;
	// 	// 	} else if (filter === 'self-signed') {
	// 	// 		const res = await getSelfSignedCerts();
	// 	// 		certificates = res.certificates;
	// 	// 	} else {
	// 	// 		const res = await getCertificates();
	// 	// 		certificates = res.certificates;
	// 	// 	}
	// 	// 	loading = false;
	// 	// }
	// 	// OLD CODE END
	// 	let certsFailed = $state(false);
	// 	let changesFailed = $state(false);
	//
	// 	// OLD CODE START — PLAN §5.5: one guarded loader for the first load, Refresh and the filter,
	// 	// so a refresh keeps the chosen filter and a slower, older answer never wins
	// 	// async function loadData() {
	// 	// 	loading = true;
	// 	// 	const [certsRes, statsRes, changesRes] = await Promise.allSettled([
	// 	// 		getCertificates(),
	// 	// 		getCertStats(),
	// 	// 		getIssuerChanges(),
	// 	// 	]);
	// 	// 	certificates = certsRes.status === 'fulfilled' ? certsRes.value.certificates : [];
	// 	// 	certsFailed = certsRes.status === 'rejected';
	// 	// 	stats = statsRes.status === 'fulfilled' ? statsRes.value : null;
	// 	// 	issuerChanges = changesRes.status === 'fulfilled' ? changesRes.value.changes : [];
	// 	// 	changesFailed = changesRes.status === 'rejected';
	// 	// 	loading = false;
	// 	// }
	// 	//
	// 	// async function filterByStatus(filter: string) {
	// 	// 	statusFilter = filter;
	// 	// 	loading = true;
	// 	// 	try {
	// 	// 		const res =
	// 	// 			filter === 'expiring' ? await getExpiringCerts(30)
	// 	// 			: filter === 'self-signed' ? await getSelfSignedCerts()
	// 	// 			: await getCertificates();
	// 	// 		certificates = res.certificates;
	// 	// 		certsFailed = false;
	// 	// 	} catch {
	// 	// 		certificates = [];
	// 	// 		certsFailed = true;
	// 	// 	}
	// 	// 	loading = false;
	// 	// }
	// 	// OLD CODE END
	// 	const refresh = registerPageRefresh(loadData);
	// 	onMount(() => {
	// 		refresh.run();
	// 	});
	// 	onDestroy(refresh.unregister);
	//
	// 	async function loadData(guard: LoadGuard): Promise<LoadResult> {
	// 		const g = guard.begin();
	// 		const filter = statusFilter;
	// 		loading = true;
	// 		const [certsRes, statsRes, changesRes] = await Promise.allSettled([
	// 			filter === 'expiring' ? getExpiringCerts(30) : filter === 'self-signed' ? getSelfSignedCerts() : getCertificates(),
	// 			getCertStats(),
	// 			getIssuerChanges(),
	// 		]);
	// 		if (!guard.current(g)) return 'skipped';
	// 		certificates = certsRes.status === 'fulfilled' ? certsRes.value.certificates : [];
	// 		certsFailed = certsRes.status === 'rejected';
	// 		// getCertStats answers null when the counts couldn't be loaded
	// 		stats = statsRes.status === 'fulfilled' ? statsRes.value : null;
	// 		issuerChanges = changesRes.status === 'fulfilled' ? changesRes.value.changes : [];
	// 		changesFailed = changesRes.status === 'rejected';
	// 		loading = false;
	// 		const ok = [!certsFailed, stats !== null, !changesFailed].filter(Boolean).length;
	// 		return ok === 3 ? 'ok' : ok === 0 ? 'failed' : 'partial';
	// 	}
	//
	// 	function filterByStatus(filter: string) {
	// 		statusFilter = filter;
	// 		refresh.run();
	// 	}
	//
	// 	const FILTERS = [
	// 		{ value: 'all', label: 'All' },
	// 		{ value: 'expiring', label: 'Expiring' },
	// 		{ value: 'self-signed', label: 'Self-signed' },
	// 	];
	//
	// 	// OLD CODE START — status badge classes; the status is now a system chip
	// 	// function statusBadgeClass(status: string): string {
	// 	// 	switch (status) {
	// 	// 		case 'valid': return 'status-valid';
	// 	// 		case 'expiring': return 'status-warning';
	// 	// 		case 'expired': return 'status-critical';
	// 	// 		case 'self-signed': return 'status-info';
	// 	// 		default: return '';
	// 	// 	}
	// 	// }
	// 	// OLD CODE END
	// 	const STATUS: Record<string, { label: string; tone: string }> = {
	// 		valid: { label: 'Valid', tone: 'is-ok' },
	// 		expiring: { label: 'Expiring', tone: 'is-warn' },
	// 		expired: { label: 'Expired', tone: 'is-bad' },
	// 		'self-signed': { label: 'Self-signed', tone: '' },
	// 	};
	//
	// 	function formatDate(dateStr: string): string {
	// 		if (!dateStr) return '-';
	// 		try {
	// 			return new Date(dateStr).toLocaleDateString();
	// 		} catch {
	// 			return dateStr;
	// 		}
	// 	}
	//
	// 	// OLD CODE START — long values now truncate in CSS (.trunc) with the full text as a title
	// 	// function truncate(str: string, len: number): string {
	// 	// 	if (!str) return '-';
	// 	// 	return str.length > len ? str.slice(0, len) + '...' : str;
	// 	// }
	// 	// OLD CODE END
	//
	// 	const domainOf = (c: Certificate) => c.domain || c.server_name || '';
	//
	// 	const columns: Column<Certificate>[] = [
	// 		{ key: 'domain', label: 'Domain', sortValue: domainOf, cell: domainCell },
	// 		{ key: 'issuer', label: 'Issuer', cell: issuerCell },
	// 		{ key: 'not_before', label: 'Valid from', cell: fromCell },
	// 		{ key: 'not_after', label: 'Valid to', cell: toCell },
	// 		{ key: 'status', label: 'Status', cell: statusCell },
	// 		{ key: 'source_ip', label: 'Source', class: 'mono' },
	// 	];
	//
	// 	// The dialog: focus moves to its close button, and Escape closes it
	// 	let closeButton = $state<HTMLButtonElement>();
	// 	$effect(() => {
	// 		if (selectedCert) closeButton?.focus();
	// 	});
	// // </ script>
	//
	// {#snippet domainCell(cert: Certificate)}<span class="mono trunc" title={domainOf(cert)}>{domainOf(cert) || '-'}</span>{/snippet}
	// {#snippet issuerCell(cert: Certificate)}<span class="trunc" title={cert.issuer}>{cert.issuer || '-'}</span>{/snippet}
	// {#snippet fromCell(cert: Certificate)}<span class="num">{formatDate(cert.not_before)}</span>{/snippet}
	// {#snippet toCell(cert: Certificate)}<span class="num">{formatDate(cert.not_after)}</span>{/snippet}
	// {#snippet statusCell(cert: Certificate)}
	// 	<span class="chip {STATUS[cert.status]?.tone ?? ''}">{STATUS[cert.status]?.label ?? cert.status}</span>
	// {/snippet}
	//
	// <svelte:head>
	// 	<title>Certificates | NetTap</title>
	// </svelte:head>
	//
	// <svelte:window onkeydown={(e) => { if (e.key === 'Escape' && selectedCert) selectedCert = null; }} />
	//
	// <div class="page-head">
	// 	<div>
	// 		<h1 class="page-title">Certificates</h1>
	// 		<p class="page-sub">Track observed certificates, detect expiry, self-signed usage, and issuer changes. TLS 1.3 encrypts certificates, so only those sent in TLS 1.2 or older connections appear here.</p>
	// 	</div>
	// </div>
	//
	// <div class="grid">
	// 	<KpiCard class="c-3" label="Total certificates" icon="certs" value={stats?.total_certs ?? '—'} note="Last 7 days" />
	// 	<KpiCard
	// 		class="c-3"
	// 		label="Expiring in 30 days"
	// 		icon="changelog"
	// 		value={stats?.expiring_count ?? '—'}
	// 		sub={stats ? `${stats.expired_count} already expired` : loading ? undefined : 'Counts unavailable'}
	// 	/>
	// 	<KpiCard class="c-3" label="Self-signed" icon="certs" value={stats?.self_signed_count ?? '—'} note="Last 7 days" />
	// 	<KpiCard class="c-3" label="Issuer changes" icon="warn" value={stats?.issuer_changes_count ?? '—'} note="Domains with more than one issuer" />
	//
	// 	{#if changesFailed}
	// 		<p class="notice is-warn c-12" role="status"><Icon name="warn" />Couldn't check for issuer changes (possible MITM): the request failed.</p>
	// 	{/if}
	// 	{#if issuerChanges.length > 0}
	// 		<div class="notice is-error c-12" role="alert">
	// 			<Icon name="warn" />
	// 			<div>
	// 				<strong>Potential MITM warning:</strong> {issuerChanges.length} domain{issuerChanges.length !== 1 ? 's have' : ' has'} multiple certificate issuers.
	// 				<ul class="changes">
	// 					{#each issuerChanges as change (change.domain)}
	// 						<li><span class="mono">{change.domain}</span>: {change.issuers.join(', ')} ({change.issuer_count} issuers)</li>
	// 					{/each}
	// 				</ul>
	// 			</div>
	// 		</div>
	// 	{/if}
	//
	// 	<Card title="Certificate inventory" sub="One row per certificate · last 7 days" class="c-12">
	// 		<div class="toolbar">
	// 			<Pills options={FILTERS} value={statusFilter} onchange={filterByStatus} ariaLabel="Certificate status" />
	// 		</div>
	// 		{#if loading}
	// 			<CardState state="loading" title="Loading certificates" />
	// 		{:else if certsFailed}
	// 			<CardState
	// 				state="error"
	// 				title="Couldn't load certificates: the request failed."
	// 				message="Check that NetTap is running on the System page, then try again."
	// 				onaction={() => refresh.run()}
	// 			/>
	// 		{:else if certificates.length === 0}
	// 			<CardState
	// 				state="empty"
	// 				icon="certs"
	// 				title="No certificates found for the selected filter."
	// 				message="Certificates appear here once NetTap sees a TLS 1.2 or older handshake."
	// 			/>
	// 		{:else}
	// 			<DataTable
	// 				{columns}
	// 				rows={certificates}
	// 				ariaLabel="Certificates"
	// 				rowKey={(c) => c._id}
	// 				initialSort={{ key: 'domain', dir: 'asc' }}
	// 				onrowactivate={(c) => (selectedCert = c)}
	// 				rowLabel={(c) => `Open certificate for ${domainOf(c) || 'an unnamed server'}`}
	// 				selectedKey={selectedCert?._id}
	// 			/>
	// 		{/if}
	// 	</Card>
	// </div>
	//
	// {#if selectedCert}
	// 	<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
	// 	<!-- The scrim closes on click; Escape and the close button are the keyboard path -->
	// 	<div class="overlay" onclick={() => (selectedCert = null)}>
	// 		<!-- svelte-ignore a11y_click_events_have_key_events -->
	// 		<div class="card dialog" role="dialog" aria-modal="true" aria-labelledby="cert-title" tabindex="-1" onclick={(e) => e.stopPropagation()}>
	// 			<div class="card-head">
	// 				<div>
	// 					<h2 class="card-title" id="cert-title">Certificate details</h2>
	// 					<p class="card-sub mono">{selectedCert.domain || selectedCert.server_name || '-'}</p>
	// 				</div>
	// 				<button class="icon-btn" type="button" aria-label="Close" bind:this={closeButton} onclick={() => (selectedCert = null)}><Icon name="close" /></button>
	// 			</div>
	// 			<dl class="facts">
	// 				<dt>Domain</dt><dd class="mono">{selectedCert.domain || selectedCert.server_name || '-'}</dd>
	// 				<dt>Subject</dt><dd>{selectedCert.subject || '-'}</dd>
	// 				<dt>Issuer</dt><dd>{selectedCert.issuer || '-'}</dd>
	// 				<dt>Valid from</dt><dd>{formatDate(selectedCert.not_before)}</dd>
	// 				<dt>Valid to</dt><dd>{formatDate(selectedCert.not_after)}</dd>
	// 				<dt>Status</dt><dd><span class="chip {STATUS[selectedCert.status]?.tone ?? ''}">{STATUS[selectedCert.status]?.label ?? selectedCert.status}</span></dd>
	// 				<dt>TLS version</dt><dd>{selectedCert.tls_version || '-'}</dd>
	// 				<dt>SHA-256</dt><dd class="mono">{selectedCert.hash_sha256 || '-'}</dd>
	// 				<dt>Source IP</dt><dd class="mono">{selectedCert.source_ip || '-'}</dd>
	// 				<dt>Destination</dt><dd class="mono">{selectedCert.destination_ip || '-'}:{selectedCert.destination_port || '-'}</dd>
	// 				<dt>Validation</dt><dd>{selectedCert.validation_status || '-'}</dd>
	// 				<dt>Server names</dt><dd class="mono">{selectedCert.server_names?.join(', ') || '-'}</dd>
	// 				<dt>SAN DNS</dt><dd class="mono">{selectedCert.san_dns?.join(', ') || '-'}</dd>
	// 				<dt>Clients</dt><dd class="mono">{selectedCert.clients?.join(', ') || '-'}</dd>
	// 				<dt>Key</dt><dd>{selectedCert.key_type ? `${selectedCert.key_type} ${selectedCert.key_length ?? ''}` : '-'}</dd>
	// 				<dt>First seen</dt><dd>{formatDate(selectedCert.first_seen)}</dd>
	// 				<dt>Observed</dt><dd>{formatDate(selectedCert.timestamp)}</dd>
	// 				<dt>Sessions</dt><dd class="num">{selectedCert.times_seen ?? '-'}</dd>
	// 			</dl>
	// 		</div>
	// 	</div>
	// {/if}
	//
	// <style>
	// 	/* Layout glue the system lacks: the issuer list, and the details dialog over the scrim */
	// 	.changes { margin: var(--sp-2) 0 0; padding-left: var(--sp-5); }
	// 	.overlay { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; padding: var(--sp-4); background: var(--scrim); }
	// 	.dialog { width: min(40rem, 100%); max-height: calc(100dvh - var(--sp-8)); overflow-y: auto; box-shadow: var(--shadow-pop); }
	// 	.dialog .facts { padding-top: 0; border-top: 0; }
	// </style>
	// OLD CODE END
</script>

{#snippet siteCell(s: CertSite)}<span class="mono trunc" title={siteName(s.name, s.server)}>{siteName(s.name, s.server)}</span>{/snippet}
{#snippet usedByCell(s: CertSite)}<span class="trunc">{whoUsed(s.clients, s.clients_total, names) || '—'}</span>{/snippet}
{#snippet authorityCell(s: CertSite)}<span class="trunc" title={s.authorities.join(', ')}>{s.authorities.join(', ') || 'Unavailable'}</span>{/snippet}
{#snippet certCountCell(s: CertSite)}<span class="num">{fmt(s.certificates_total)}</span>{/snippet}
{#snippet sessionsCell(s: CertSite)}<span class="num">{fmt(s.sessions)}</span>{/snippet}
{#snippet lastSeenCell(s: CertSite)}<span class="num">{seen(s.last_seen)}</span>{/snippet}
{#snippet statusCell(s: CertSite)}
	{@const status = siteStatus(s, worstKind.get(s.id))}
	<span class="chip {status.tone}">{status.label}</span>
{/snippet}

{#snippet deviceCell(d: CertDevice)}
	{#if d.server}
		<a href="/devices/{encodeURIComponent(d.server)}" title={d.server}>{deviceName(d.server, names)}</a><span class="mono dim">:{d.port ?? '—'}</span>
	{:else}<span class="dim">—</span>{/if}
{/snippet}
{#snippet deviceSiteCell(d: CertDevice)}<span class="mono trunc" title={siteName(d.site, d.server)}>{siteName(d.site, d.server)}</span>{/snippet}
{#snippet deviceAuthorityCell(d: CertDevice)}<span class="trunc">{d.details_available ? (d.self_signed ? 'Self-signed' : (d.authority ?? '—')) : 'Unavailable'}</span>{/snippet}
{#snippet verificationCell(d: CertDevice)}<span class="trunc" title={deviceVerification(d)}>{deviceVerification(d)}</span>{/snippet}
{#snippet runsOutCell(d: CertDevice)}<span class="num">{runsOut(d.days_left)}</span>{/snippet}
{#snippet deviceSessionsCell(d: CertDevice)}<span class="num">{fmt(d.sessions)}</span>{/snippet}
{#snippet deviceLastSeenCell(d: CertDevice)}<span class="num">{seen(d.last_seen)}</span>{/snippet}

{#snippet loadState(what: string)}
	{#if loading && !data}
		<CardState state="loading" title="Working out {what}…" message="Checking every TLS session in the window. This can take up to a minute for 30 days." />
	{:else}
		<CardState
			state="error"
			title={loadFailed('certificate data')}
			message={failure?.reason || 'Check that NetTap is running on the System page, then try again.'}
			onaction={() => refresh.run()}
		/>
	{/if}
{/snippet}

<svelte:head>
	<title>Certificates | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Certificates</h1>
		<p class="page-sub">
			Certificates that couldn't be verified, expired or weak, and when your own devices' certificates run out. Certificates are sent in
			TLS 1.2 and older connections; TLS 1.3 hides them.
		</p>
	</div>
	<Pills options={RANGES.map((r) => ({ value: r.value, label: r.label }))} value={rangeValue} onchange={changeRange} ariaLabel="Time range" />
</div>

<div class="grid">
	<KpiCard
		class="c-4"
		label="Needs a look"
		icon="warn"
		value={summary ? fmt(summary.findings.total) : '—'}
		sub={summary ? `${fmt(summary.findings.high)} high · ${fmt(summary.findings.medium)} medium · ${fmt(summary.findings.low)} low` : undefined}
		note={words || undefined}
	/>
	<KpiCard
		class="c-4"
		label="Your devices' certificates"
		icon="devices"
		value={summary ? fmt(summary.local_certificates) : '—'}
		sub={summary
			? `on ${fmt(summary.local_endpoints)} ${summary.local_endpoints === 1 ? 'service' : 'services'}${summary.soonest_local_expiry_days === null ? '' : ` · soonest ${runsOutSentence(summary.soonest_local_expiry_days)}`}`
			: undefined}
		note={words || undefined}
	/>
	<KpiCard
		class="c-4"
		label="Certificates seen"
		icon="certs"
		value={summary ? fmt(summary.certificates) : '—'}
		sub={summary ? `across ${fmt(summary.sites)} ${summary.sites === 1 ? 'site' : 'sites'} · TLS 1.2 and older` : undefined}
		note={words || undefined}
	/>

	{#if failure && loaded}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" />{staleNotice(failure.range, loaded.range, loaded.at, failure.reason)}</p>
	{/if}
	{#if summary && summary.certificates_without_details > 0}
		<p class="notice c-12" role="note">
			<Icon name="certs" />{fmt(summary.certificates_without_details)}
			{summary.certificates_without_details === 1 ? 'certificate has' : 'certificates have'} no stored details. {summary.certificates_without_details === 1
				? 'Its'
				: 'Their'} {fmt(summary.sessions_without_details)} {summary.sessions_without_details === 1 ? 'session is' : 'sessions are'} counted, with issuer and dates shown as unavailable.
		</p>
	{/if}
	{#if data}
		{#each truncated as t (t.what)}
			<p class="notice is-warn c-12" role="status"><Icon name="warn" />Listing the first 5,000 of {fmt(t.total)} {t.what}. Every figure above counts all of them.</p>
		{/each}
	{/if}
</div>

<div class="grid alert-layout" class:no-drawer={!selectedFinding}>
	<Card
		class="c-8 alert-list-card"
		title="Needs a look"
		sub={data ? `${fmt(findings.length)} ${findings.length === 1 ? 'finding' : 'findings'} · ${words} · most serious first` : 'Most serious first'}
	>
		{#if !data}
			{@render loadState('what needs a look')}
		{:else if findings.length === 0}
			<CardState
				state="empty"
				icon="check"
				title="Nothing needs a look"
				message="{fmt(data.summary.certificates)} certificates from {fmt(data.summary.sites)} sites in the {words}. None failed verification on a server outside your network, and none of the {fmt(data.summary.certificates - data.summary.certificates_without_details)} with stored details was expired when used, weak, or close to running out on your own devices."
			/>
		{:else}
			<div class="alert-rows">
				{#each shownFindings as f (f.id)}
					<AlertRow
						severity={f.severity}
						title={findingTitle(f, names)}
						signature={findingEvidence(f)}
						device={f.kind === 'device-expiry'
							? { name: deviceName(f.server, names) }
							: f.clients.length
								? { name: whoUsed(f.clients, f.clients_total, names) }
								: undefined}
						count={f.sessions}
						lastSeen={f.last_seen ? shortSeen(f.last_seen) : '—'}
						selected={selectedFinding?.id === f.id}
						onselect={() => (selected = { type: 'finding', id: f.id })}
					/>
				{/each}
			</div>
			{#if findings.length > FINDINGS_SHOWN}
				<button class="btn more" type="button" onclick={() => (showAllFindings = !showAllFindings)}>
					{showAllFindings ? 'Show the first 10' : `Show all ${fmt(findings.length)} findings`}
				</button>
			{/if}
		{/if}
		{#snippet foot()}
			{#if data && data.quiet_switches.length > 0}
				<p class="dim">
					{fmt(data.quiet_switches.length)}
					{data.quiet_switches.length === 1 ? 'site used' : 'sites used'} more than one authority, and every certificate verified. Big sites switch between
					well-known authorities often, so these aren't listed above.
					<button class="link-btn" type="button" aria-expanded={showQuiet} onclick={() => (showQuiet = !showQuiet)}>
						{showQuiet ? 'Hide them' : 'Show them'}
					</button>
				</p>
				{#if showQuiet}
					<ul class="quiet">
						{#each data.quiet_switches as q (q.site_id)}
							<li>
								<button class="link-btn mono" type="button" onclick={() => openSite(q.site_id)}>{siteName(q.site, q.server)}</button>
								<span class="dim">{q.authorities.join(', ')}</span>
							</li>
						{/each}
					</ul>
				{/if}
			{/if}
		{/snippet}
	</Card>
	{#if selectedFinding && data}
		<CertDetail finding={selectedFinding} details={data.details} {names} onclose={() => (selected = null)} />
	{/if}
</div>

<div class="grid">
	<Card
		class="c-12"
		title="Your devices' certificates"
		sub={data ? `One row per service on your network. Authority and runs out are for the certificate it sent last; verification and sessions cover every certificate it sent · ${words}` : 'One row per service on your network'}
	>
		{#if !data}
			{@render loadState("your devices' certificates")}
		{:else if data.devices.length === 0}
			<CardState
				state="empty"
				icon="devices"
				title="No certificates from your own devices"
				message="None of your devices served a certificate over TLS 1.2 or older in the {words}."
			/>
		{:else}
			<DataTable
				columns={deviceColumns}
				rows={data.devices}
				ariaLabel="Your devices' certificates"
				rowKey={(d) => d.id}
				initialSort={{ key: 'days_left', dir: 'asc' }}
				onrowactivate={(d) => openSite(d.site_id)}
				rowLabel={(d) => `Open ${siteName(d.site, d.server)} served by ${deviceName(d.server, names)}`}
			/>
			<p class="dim note">Self-signed is normal for routers, printers and cameras. The date matters more: once a certificate runs out, browsers warn every time you open that device's page.</p>
		{/if}
	</Card>
</div>

<div class="grid alert-layout" class:no-drawer={!selectedSite} id="cert-sites">
	<Card
		class="c-8 alert-list-card"
		title="All certificates"
		sub={data ? `One row per site, renewed certificates folded in · ${fmt(data.sites_total)} ${data.sites_total === 1 ? 'site' : 'sites'} · ${words}` : 'One row per site'}
	>
		{#if !data}
			{@render loadState('certificates')}
		{:else if data.sites.length === 0}
			<CardState
				state="empty"
				icon="certs"
				title="No certificates in the {words}"
				message="Certificates appear once NetTap sees a TLS 1.2 or older handshake. TLS 1.3 hides them."
			/>
		{:else}
			<div class="toolbar">
				<SearchField id="cert-search" label="Search sites, authorities and devices" placeholder="Search sites, authorities and devices" size="toolbar" bind:value={query} oninput={() => (page = 1)} />
				<Pills options={[...LIST_FILTERS]} value={listFilter} onchange={setListFilter} ariaLabel="Show" />
			</div>
			<DataTable
				columns={siteColumns}
				rows={pageRows}
				ariaLabel="All certificates by site"
				rowKey={(s) => s.id}
				initialSort={{ key: sortKey, dir: sortDir }}
				onsortchange={(key, dir) => {
					sortKey = key;
					sortDir = dir;
					page = 1;
				}}
				onrowactivate={(s) => (selected = { type: 'site', id: s.id })}
				rowLabel={(s) => `Open ${siteName(s.name, s.server)}`}
				selectedKey={selectedSite?.id}
				pager={matchingSites.length > PAGE_SIZE
					? {
							page: currentPage,
							pageCount,
							total: matchingSites.length,
							from: (currentPage - 1) * PAGE_SIZE + 1,
							to: Math.min(currentPage * PAGE_SIZE, matchingSites.length),
							onpage: (p) => (page = p),
						}
					: undefined}
			>
				{#snippet empty()}
					<CardState state="empty" icon="search" title="No sites match" message="Try another filter or search." />
				{/snippet}
			</DataTable>
		{/if}
	</Card>
	{#if selectedSite && data}
		<CertDetail
			site={selectedSite}
			status={siteStatus(selectedSite, worstKind.get(selectedSite.id))}
			details={data.details}
			{names}
			onclose={() => (selected = null)}
		/>
	{/if}
</div>

<style>
	/* Layout glue the system lacks */
	.alert-layout { align-items: start; }
	.more { margin-top: var(--sp-3); color: var(--text-1); }
	.note { margin: var(--sp-3) 0 0; font-size: var(--text-sm); }
	.quiet { margin: var(--sp-2) 0 0; padding-left: var(--sp-5); display: grid; gap: var(--sp-1); }
	.link-btn { background: none; border: 0; padding: 0; color: var(--accent-strong); cursor: pointer; font: inherit; text-decoration: underline; }
	.link-btn:hover { color: var(--text-1); }
	.link-btn:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
</style>
