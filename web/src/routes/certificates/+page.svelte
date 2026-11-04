<script lang="ts">
	/**
	 * Certificate Inventory — TLS certificate tracking and analysis.
	 *
	 * Shows certificate table with status filtering, hero stats cards,
	 * and detail modal. Alerts on issuer changes (potential MITM).
	 */

	import { onDestroy, onMount } from 'svelte';
	// OLD CODE START — sorting moved into DataTable (utils/table-sort, blanks last both ways)
	// import { compareValues } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	import {
		getCertificates,
		getExpiringCerts,
		getSelfSignedCerts,
		getIssuerChanges,
		getCertStats,
		type Certificate,
		type IssuerChange,
		type CertStats,
	} from '$lib/api/certificates';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';

	// State
	let certificates = $state<Certificate[]>([]);
	// OLD CODE START — 2026-11-01: stats now include expired_count
	// let stats = $state<CertStats>({ total_certs: 0, expiring_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: '', to: '' });
	// OLD CODE END
	// OLD CODE START — 2026-11-02: null now means the stats couldn't be loaded (cards show a dash)
	// let stats = $state<CertStats>({ total_certs: 0, expiring_count: 0, expired_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: '', to: '' });
	// OLD CODE END
	// OLD CODE START — zeros before the first load read as real counts (PLAN §4.1)
	// let stats = $state<CertStats | null>({ total_certs: 0, expiring_count: 0, expired_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: '', to: '' });
	// OLD CODE END
	let stats = $state<CertStats | null>(null);
	let issuerChanges = $state<IssuerChange[]>([]);
	let loading = $state(true);
	let statusFilter = $state('all');
	let selectedCert = $state<Certificate | null>(null);

	// OLD CODE START — DataTable sorts every column (utils/table-sort: numbers in text by value, blanks last)
	// // Sort state
	// let sortField = $state('domain');
	// let sortDir = $state<'asc' | 'desc'>('asc');
	//
	// function toggleSort(field: string) {
	// 	if (sortField === field) {
	// 		sortDir = sortDir === 'desc' ? 'asc' : 'desc';
	// 	} else {
	// 		sortField = field;
	// 		sortDir = field === 'not_after' ? 'asc' : 'desc';
	// 	}
	// }
	//
	// let sortedCertificates = $derived.by(() => {
	// 	const sorted = [...certificates];
	// 	sorted.sort((a, b) => {
	// 		let aVal: string | number = '';
	// 		let bVal: string | number = '';
	// 		switch (sortField) {
	// 			case 'domain':
	// 				aVal = (a.domain || a.server_name || '').toLowerCase();
	// 				bVal = (b.domain || b.server_name || '').toLowerCase();
	// 				break;
	// 			case 'issuer':
	// 				aVal = (a.issuer || '').toLowerCase();
	// 				bVal = (b.issuer || '').toLowerCase();
	// 				break;
	// 			case 'not_before':
	// 				aVal = a.not_before || '';
	// 				bVal = b.not_before || '';
	// 				break;
	// 			case 'not_after':
	// 				aVal = a.not_after || '';
	// 				bVal = b.not_after || '';
	// 				break;
	// 			case 'status':
	// 				aVal = (a.status || '').toLowerCase();
	// 				bVal = (b.status || '').toLowerCase();
	// 				break;
	// 			case 'source_ip':
	// 				aVal = (a.source_ip || '').toLowerCase();
	// 				bVal = (b.source_ip || '').toLowerCase();
	// 				break;
	// 		}
	// 		// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 		// if (aVal < bVal) return sortDir === 'asc' ? -1 : 1;
	// 		// if (aVal > bVal) return sortDir === 'asc' ? 1 : -1;
	// 		// return 0;
	// 		// OLD CODE END
	// 		if (!aVal !== !bVal) return aVal ? -1 : 1; // a blank (no source IP, no date) goes last both ways
	// 		const cmp = compareValues(aVal, bVal);
	// 		return sortDir === 'asc' ? cmp : -cmp;
	// 	});
	// 	return sorted;
	// });
	//
	// // Load data on mount
	// $effect(() => {
	// 	loadData();
	// });
	// OLD CODE END

	// OLD CODE START — #96: the getters returned [] on failure, read as "No certificates found"
	// and no MITM warning; they now throw
	// async function loadData() {
	// 	loading = true;
	// 	const [certsRes, statsRes, changesRes] = await Promise.all([
	// 		getCertificates(),
	// 		getCertStats(),
	// 		getIssuerChanges(),
	// 	]);
	// 	certificates = certsRes.certificates;
	// 	stats = statsRes;
	// 	issuerChanges = changesRes.changes;
	// 	loading = false;
	// }
	//
	// async function filterByStatus(filter: string) {
	// 	statusFilter = filter;
	// 	loading = true;
	//
	// 	if (filter === 'expiring') {
	// 		const res = await getExpiringCerts(30);
	// 		certificates = res.certificates;
	// 	} else if (filter === 'self-signed') {
	// 		const res = await getSelfSignedCerts();
	// 		certificates = res.certificates;
	// 	} else {
	// 		const res = await getCertificates();
	// 		certificates = res.certificates;
	// 	}
	// 	loading = false;
	// }
	// OLD CODE END
	let certsFailed = $state(false);
	let changesFailed = $state(false);

	// OLD CODE START — PLAN §5.5: one guarded loader for the first load, Refresh and the filter,
	// so a refresh keeps the chosen filter and a slower, older answer never wins
	// async function loadData() {
	// 	loading = true;
	// 	const [certsRes, statsRes, changesRes] = await Promise.allSettled([
	// 		getCertificates(),
	// 		getCertStats(),
	// 		getIssuerChanges(),
	// 	]);
	// 	certificates = certsRes.status === 'fulfilled' ? certsRes.value.certificates : [];
	// 	certsFailed = certsRes.status === 'rejected';
	// 	stats = statsRes.status === 'fulfilled' ? statsRes.value : null;
	// 	issuerChanges = changesRes.status === 'fulfilled' ? changesRes.value.changes : [];
	// 	changesFailed = changesRes.status === 'rejected';
	// 	loading = false;
	// }
	//
	// async function filterByStatus(filter: string) {
	// 	statusFilter = filter;
	// 	loading = true;
	// 	try {
	// 		const res =
	// 			filter === 'expiring' ? await getExpiringCerts(30)
	// 			: filter === 'self-signed' ? await getSelfSignedCerts()
	// 			: await getCertificates();
	// 		certificates = res.certificates;
	// 		certsFailed = false;
	// 	} catch {
	// 		certificates = [];
	// 		certsFailed = true;
	// 	}
	// 	loading = false;
	// }
	// OLD CODE END
	const refresh = registerPageRefresh(loadData);
	onMount(() => {
		refresh.run();
	});
	onDestroy(refresh.unregister);

	async function loadData(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const filter = statusFilter;
		loading = true;
		const [certsRes, statsRes, changesRes] = await Promise.allSettled([
			filter === 'expiring' ? getExpiringCerts(30) : filter === 'self-signed' ? getSelfSignedCerts() : getCertificates(),
			getCertStats(),
			getIssuerChanges(),
		]);
		if (!guard.current(g)) return 'skipped';
		certificates = certsRes.status === 'fulfilled' ? certsRes.value.certificates : [];
		certsFailed = certsRes.status === 'rejected';
		// getCertStats answers null when the counts couldn't be loaded
		stats = statsRes.status === 'fulfilled' ? statsRes.value : null;
		issuerChanges = changesRes.status === 'fulfilled' ? changesRes.value.changes : [];
		changesFailed = changesRes.status === 'rejected';
		loading = false;
		const ok = [!certsFailed, stats !== null, !changesFailed].filter(Boolean).length;
		return ok === 3 ? 'ok' : ok === 0 ? 'failed' : 'partial';
	}

	function filterByStatus(filter: string) {
		statusFilter = filter;
		refresh.run();
	}

	const FILTERS = [
		{ value: 'all', label: 'All' },
		{ value: 'expiring', label: 'Expiring' },
		{ value: 'self-signed', label: 'Self-signed' },
	];

	// OLD CODE START — status badge classes; the status is now a system chip
	// function statusBadgeClass(status: string): string {
	// 	switch (status) {
	// 		case 'valid': return 'status-valid';
	// 		case 'expiring': return 'status-warning';
	// 		case 'expired': return 'status-critical';
	// 		case 'self-signed': return 'status-info';
	// 		default: return '';
	// 	}
	// }
	// OLD CODE END
	const STATUS: Record<string, { label: string; tone: string }> = {
		valid: { label: 'Valid', tone: 'is-ok' },
		expiring: { label: 'Expiring', tone: 'is-warn' },
		expired: { label: 'Expired', tone: 'is-bad' },
		'self-signed': { label: 'Self-signed', tone: '' },
	};

	function formatDate(dateStr: string): string {
		if (!dateStr) return '-';
		try {
			return new Date(dateStr).toLocaleDateString();
		} catch {
			return dateStr;
		}
	}

	// OLD CODE START — long values now truncate in CSS (.trunc) with the full text as a title
	// function truncate(str: string, len: number): string {
	// 	if (!str) return '-';
	// 	return str.length > len ? str.slice(0, len) + '...' : str;
	// }
	// OLD CODE END

	const domainOf = (c: Certificate) => c.domain || c.server_name || '';

	const columns: Column<Certificate>[] = [
		{ key: 'domain', label: 'Domain', sortValue: domainOf, cell: domainCell },
		{ key: 'issuer', label: 'Issuer', cell: issuerCell },
		{ key: 'not_before', label: 'Valid from', cell: fromCell },
		{ key: 'not_after', label: 'Valid to', cell: toCell },
		{ key: 'status', label: 'Status', cell: statusCell },
		{ key: 'source_ip', label: 'Source', class: 'mono' },
	];

	// The dialog: focus moves to its close button, and Escape closes it
	let closeButton = $state<HTMLButtonElement>();
	$effect(() => {
		if (selectedCert) closeButton?.focus();
	});
</script>

{#snippet domainCell(cert: Certificate)}<span class="mono trunc" title={domainOf(cert)}>{domainOf(cert) || '-'}</span>{/snippet}
{#snippet issuerCell(cert: Certificate)}<span class="trunc" title={cert.issuer}>{cert.issuer || '-'}</span>{/snippet}
{#snippet fromCell(cert: Certificate)}<span class="num">{formatDate(cert.not_before)}</span>{/snippet}
{#snippet toCell(cert: Certificate)}<span class="num">{formatDate(cert.not_after)}</span>{/snippet}
{#snippet statusCell(cert: Certificate)}
	<span class="chip {STATUS[cert.status]?.tone ?? ''}">{STATUS[cert.status]?.label ?? cert.status}</span>
{/snippet}

<svelte:head>
	<title>Certificates | NetTap</title>
</svelte:head>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape' && selectedCert) selectedCert = null; }} />

<div class="page-head">
	<div>
		<h1 class="page-title">Certificates</h1>
		<p class="page-sub">Track observed certificates, detect expiry, self-signed usage, and issuer changes. TLS 1.3 encrypts certificates, so only those sent in TLS 1.2 or older connections appear here.</p>
	</div>
</div>

<div class="grid">
	<KpiCard class="c-3" label="Total certificates" icon="certs" value={stats?.total_certs ?? '—'} note="Last 7 days" />
	<KpiCard
		class="c-3"
		label="Expiring in 30 days"
		icon="changelog"
		value={stats?.expiring_count ?? '—'}
		sub={stats ? `${stats.expired_count} already expired` : loading ? undefined : 'Counts unavailable'}
	/>
	<KpiCard class="c-3" label="Self-signed" icon="certs" value={stats?.self_signed_count ?? '—'} note="Last 7 days" />
	<KpiCard class="c-3" label="Issuer changes" icon="warn" value={stats?.issuer_changes_count ?? '—'} note="Domains with more than one issuer" />

	{#if changesFailed}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" />Couldn't check for issuer changes (possible MITM): the request failed.</p>
	{/if}
	{#if issuerChanges.length > 0}
		<div class="notice is-error c-12" role="alert">
			<Icon name="warn" />
			<div>
				<strong>Potential MITM warning:</strong> {issuerChanges.length} domain{issuerChanges.length !== 1 ? 's have' : ' has'} multiple certificate issuers.
				<ul class="changes">
					{#each issuerChanges as change (change.domain)}
						<li><span class="mono">{change.domain}</span>: {change.issuers.join(', ')} ({change.issuer_count} issuers)</li>
					{/each}
				</ul>
			</div>
		</div>
	{/if}

	<Card title="Certificate inventory" sub="One row per certificate · last 7 days" class="c-12">
		<div class="toolbar">
			<Pills options={FILTERS} value={statusFilter} onchange={filterByStatus} ariaLabel="Certificate status" />
		</div>
		{#if loading}
			<CardState state="loading" title="Loading certificates" />
		{:else if certsFailed}
			<CardState
				state="error"
				title="Couldn't load certificates: the request failed."
				message="Check that NetTap is running on the System page, then try again."
				onaction={() => refresh.run()}
			/>
		{:else if certificates.length === 0}
			<CardState
				state="empty"
				icon="certs"
				title="No certificates found for the selected filter."
				message="Certificates appear here once NetTap sees a TLS 1.2 or older handshake."
			/>
		{:else}
			<DataTable
				{columns}
				rows={certificates}
				ariaLabel="Certificates"
				rowKey={(c) => c._id}
				initialSort={{ key: 'domain', dir: 'asc' }}
				onrowactivate={(c) => (selectedCert = c)}
				rowLabel={(c) => `Open certificate for ${domainOf(c) || 'an unnamed server'}`}
				selectedKey={selectedCert?._id}
			/>
		{/if}
	</Card>
</div>

{#if selectedCert}
	<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
	<!-- The scrim closes on click; Escape and the close button are the keyboard path -->
	<div class="overlay" onclick={() => (selectedCert = null)}>
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div class="card dialog" role="dialog" aria-modal="true" aria-labelledby="cert-title" tabindex="-1" onclick={(e) => e.stopPropagation()}>
			<div class="card-head">
				<div>
					<h2 class="card-title" id="cert-title">Certificate details</h2>
					<p class="card-sub mono">{selectedCert.domain || selectedCert.server_name || '-'}</p>
				</div>
				<button class="icon-btn" type="button" aria-label="Close" bind:this={closeButton} onclick={() => (selectedCert = null)}><Icon name="close" /></button>
			</div>
			<dl class="facts">
				<dt>Domain</dt><dd class="mono">{selectedCert.domain || selectedCert.server_name || '-'}</dd>
				<dt>Subject</dt><dd>{selectedCert.subject || '-'}</dd>
				<dt>Issuer</dt><dd>{selectedCert.issuer || '-'}</dd>
				<dt>Valid from</dt><dd>{formatDate(selectedCert.not_before)}</dd>
				<dt>Valid to</dt><dd>{formatDate(selectedCert.not_after)}</dd>
				<dt>Status</dt><dd><span class="chip {STATUS[selectedCert.status]?.tone ?? ''}">{STATUS[selectedCert.status]?.label ?? selectedCert.status}</span></dd>
				<dt>TLS version</dt><dd>{selectedCert.tls_version || '-'}</dd>
				<dt>SHA-256</dt><dd class="mono">{selectedCert.hash_sha256 || '-'}</dd>
				<dt>Source IP</dt><dd class="mono">{selectedCert.source_ip || '-'}</dd>
				<dt>Destination</dt><dd class="mono">{selectedCert.destination_ip || '-'}:{selectedCert.destination_port || '-'}</dd>
				<dt>Validation</dt><dd>{selectedCert.validation_status || '-'}</dd>
				<dt>Server names</dt><dd class="mono">{selectedCert.server_names?.join(', ') || '-'}</dd>
				<dt>SAN DNS</dt><dd class="mono">{selectedCert.san_dns?.join(', ') || '-'}</dd>
				<dt>Clients</dt><dd class="mono">{selectedCert.clients?.join(', ') || '-'}</dd>
				<dt>Key</dt><dd>{selectedCert.key_type ? `${selectedCert.key_type} ${selectedCert.key_length ?? ''}` : '-'}</dd>
				<dt>First seen</dt><dd>{formatDate(selectedCert.first_seen)}</dd>
				<dt>Observed</dt><dd>{formatDate(selectedCert.timestamp)}</dd>
				<dt>Sessions</dt><dd class="num">{selectedCert.times_seen ?? '-'}</dd>
			</dl>
		</div>
	</div>
{/if}

<style>
	/* Layout glue the system lacks: the issuer list, and the details dialog over the scrim */
	.changes { margin: var(--sp-2) 0 0; padding-left: var(--sp-5); }
	.overlay { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; padding: var(--sp-4); background: var(--scrim); }
	.dialog { width: min(40rem, 100%); max-height: calc(100dvh - var(--sp-8)); overflow-y: auto; box-shadow: var(--shadow-pop); }
	.dialog .facts { padding-top: 0; border-top: 0; }
</style>
