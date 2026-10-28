<script lang="ts">
	/**
	 * Certificate Inventory — TLS certificate tracking and analysis.
	 *
	 * Shows certificate table with status filtering, hero stats cards,
	 * and detail modal. Alerts on issuer changes (potential MITM).
	 */

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

	// State
	let certificates = $state<Certificate[]>([]);
	let stats = $state<CertStats>({ total_certs: 0, expiring_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: '', to: '' });
	let issuerChanges = $state<IssuerChange[]>([]);
	let loading = $state(true);
	let statusFilter = $state('all');
	let selectedCert = $state<Certificate | null>(null);

	// Sort state
	let sortField = $state('domain');
	let sortDir = $state<'asc' | 'desc'>('asc');

	function toggleSort(field: string) {
		if (sortField === field) {
			sortDir = sortDir === 'desc' ? 'asc' : 'desc';
		} else {
			sortField = field;
			sortDir = field === 'not_after' ? 'asc' : 'desc';
		}
	}

	let sortedCertificates = $derived.by(() => {
		const sorted = [...certificates];
		sorted.sort((a, b) => {
			let aVal: string | number = '';
			let bVal: string | number = '';
			switch (sortField) {
				case 'domain':
					aVal = (a.domain || a.server_name || '').toLowerCase();
					bVal = (b.domain || b.server_name || '').toLowerCase();
					break;
				case 'issuer':
					aVal = (a.issuer || '').toLowerCase();
					bVal = (b.issuer || '').toLowerCase();
					break;
				case 'not_before':
					aVal = a.not_before || '';
					bVal = b.not_before || '';
					break;
				case 'not_after':
					aVal = a.not_after || '';
					bVal = b.not_after || '';
					break;
				case 'status':
					aVal = (a.status || '').toLowerCase();
					bVal = (b.status || '').toLowerCase();
					break;
				case 'source_ip':
					aVal = (a.source_ip || '').toLowerCase();
					bVal = (b.source_ip || '').toLowerCase();
					break;
			}
			if (aVal < bVal) return sortDir === 'asc' ? -1 : 1;
			if (aVal > bVal) return sortDir === 'asc' ? 1 : -1;
			return 0;
		});
		return sorted;
	});

	// Load data on mount
	$effect(() => {
		loadData();
	});

	async function loadData() {
		loading = true;
		const [certsRes, statsRes, changesRes] = await Promise.all([
			getCertificates(),
			getCertStats(),
			getIssuerChanges(),
		]);
		certificates = certsRes.certificates;
		stats = statsRes;
		issuerChanges = changesRes.changes;
		loading = false;
	}

	async function filterByStatus(filter: string) {
		statusFilter = filter;
		loading = true;

		if (filter === 'expiring') {
			const res = await getExpiringCerts(30);
			certificates = res.certificates;
		} else if (filter === 'self-signed') {
			const res = await getSelfSignedCerts();
			certificates = res.certificates;
		} else {
			const res = await getCertificates();
			certificates = res.certificates;
		}
		loading = false;
	}

	function statusBadgeClass(status: string): string {
		switch (status) {
			case 'valid': return 'status-valid';
			case 'expiring': return 'status-warning';
			case 'expired': return 'status-critical';
			case 'self-signed': return 'status-info';
			default: return '';
		}
	}

	function formatDate(dateStr: string): string {
		if (!dateStr) return '-';
		try {
			return new Date(dateStr).toLocaleDateString();
		} catch {
			return dateStr;
		}
	}

	function truncate(str: string, len: number): string {
		if (!str) return '-';
		return str.length > len ? str.slice(0, len) + '...' : str;
	}
</script>

<svelte:head>
	<title>Certificates | NetTap</title>
</svelte:head>

<div class="certificates-page">
	<div class="page-header">
		<h2>TLS Certificate Inventory</h2>
		<p class="text-muted">Track observed certificates, detect expiry, self-signed usage, and issuer changes.</p>
	</div>

	<!-- Hero Stats -->
	<div class="stats-grid">
		<div class="stat-card">
			<span class="stat-label">Total Certificates</span>
			<span class="stat-value">{stats.total_certs}</span>
		</div>
		<div class="stat-card" class:stat-warning={stats.expiring_count > 0}>
			<span class="stat-label">Expiring (30d)</span>
			<span class="stat-value">{stats.expiring_count}</span>
		</div>
		<div class="stat-card" class:stat-info={stats.self_signed_count > 0}>
			<span class="stat-label">Self-Signed</span>
			<span class="stat-value">{stats.self_signed_count}</span>
		</div>
		<div class="stat-card" class:stat-critical={stats.issuer_changes_count > 0}>
			<span class="stat-label">Issuer Changes</span>
			<span class="stat-value">{stats.issuer_changes_count}</span>
		</div>
	</div>

	<!-- Issuer Change Alerts -->
	{#if issuerChanges.length > 0}
		<div class="alert alert-danger">
			<strong>Potential MITM Warning:</strong> {issuerChanges.length} domain{issuerChanges.length !== 1 ? 's have' : ' has'} multiple certificate issuers.
			{#each issuerChanges as change}
				<div class="issuer-change-detail">
					<strong>{change.domain}</strong>: {change.issuers.join(', ')} ({change.issuer_count} issuers)
				</div>
			{/each}
		</div>
	{/if}

	<!-- Status Filters -->
	<div class="filter-tabs">
		<button class="tab" class:active={statusFilter === 'all'} onclick={() => filterByStatus('all')}>All</button>
		<button class="tab" class:active={statusFilter === 'expiring'} onclick={() => filterByStatus('expiring')}>Expiring</button>
		<button class="tab" class:active={statusFilter === 'self-signed'} onclick={() => filterByStatus('self-signed')}>Self-Signed</button>
	</div>

	<!-- Certificate Table -->
	{#if loading}
		<div class="card">
			<p class="text-muted" style="padding: var(--space-lg);">Loading certificates...</p>
		</div>
	{:else if certificates.length === 0}
		<div class="card">
			<p class="text-muted" style="padding: var(--space-lg);">No certificates found for the selected filter.</p>
		</div>
	{:else}
		<div class="table-wrapper">
			<table class="data-table">
				<thead>
					<tr>
						<th class="sortable" onclick={() => toggleSort('domain')}>
							Domain {sortField === 'domain' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
						</th>
						<th class="sortable" onclick={() => toggleSort('issuer')}>
							Issuer {sortField === 'issuer' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
						</th>
						<th class="sortable" onclick={() => toggleSort('not_before')}>
							Valid From {sortField === 'not_before' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
						</th>
						<th class="sortable" onclick={() => toggleSort('not_after')}>
							Valid To {sortField === 'not_after' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
						</th>
						<th class="sortable" onclick={() => toggleSort('status')}>
							Status {sortField === 'status' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
						</th>
						<th class="sortable" onclick={() => toggleSort('source_ip')}>
							Source {sortField === 'source_ip' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
						</th>
					</tr>
				</thead>
				<tbody>
					{#each sortedCertificates as cert}
						<tr onclick={() => selectedCert = cert} class="clickable-row">
							<td class="mono">{truncate(cert.domain || cert.server_name, 40)}</td>
							<td>{truncate(cert.issuer, 30)}</td>
							<td>{formatDate(cert.not_before)}</td>
							<td>{formatDate(cert.not_after)}</td>
							<td>
								<span class="status-badge {statusBadgeClass(cert.status)}">{cert.status}</span>
							</td>
							<td class="mono text-muted">{cert.source_ip}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	<!-- Detail Modal -->
	{#if selectedCert}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="modal-overlay" onclick={() => selectedCert = null} onkeydown={(e) => { if (e.key === 'Escape') selectedCert = null; }}>
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="modal-content" onclick={(e) => e.stopPropagation()}>
				<div class="modal-header">
					<h3>Certificate Details</h3>
					<button class="btn btn-sm" onclick={() => selectedCert = null}>Close</button>
				</div>
				<div class="detail-grid">
					<div class="detail-row">
						<span class="detail-label">Domain</span>
						<span class="detail-value mono">{selectedCert.domain || selectedCert.server_name || '-'}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">Subject</span>
						<span class="detail-value">{selectedCert.subject || '-'}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">Issuer</span>
						<span class="detail-value">{selectedCert.issuer || '-'}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">Valid From</span>
						<span class="detail-value">{formatDate(selectedCert.not_before)}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">Valid To</span>
						<span class="detail-value">{formatDate(selectedCert.not_after)}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">Status</span>
						<span class="detail-value"><span class="status-badge {statusBadgeClass(selectedCert.status)}">{selectedCert.status}</span></span>
					</div>
					<div class="detail-row">
						<span class="detail-label">TLS Version</span>
						<span class="detail-value">{selectedCert.tls_version || '-'}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">SHA-256</span>
						<span class="detail-value mono" style="word-break: break-all;">{selectedCert.hash_sha256 || '-'}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">Source IP</span>
						<span class="detail-value mono">{selectedCert.source_ip || '-'}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">Destination</span>
						<span class="detail-value mono">{selectedCert.destination_ip || '-'}:{selectedCert.destination_port || '-'}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">Validation</span>
						<span class="detail-value">{selectedCert.validation_status || '-'}</span>
					</div>
					<div class="detail-row">
						<span class="detail-label">Observed</span>
						<span class="detail-value">{formatDate(selectedCert.timestamp)}</span>
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.certificates-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.page-header h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	/* Stats cards */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
	}

	/* stat-card, stat-value, stat-label inherit from global.css */

	.stat-warning .stat-value { color: var(--amber); }
	.stat-info .stat-value { color: var(--accent); }
	.stat-critical .stat-value { color: var(--red); }

	/* Issuer change alerts */
	.issuer-change-detail {
		margin-top: var(--space-xs);
		font-size: var(--text-sm);
	}

	/* Filter tabs */
	.filter-tabs {
		display: flex;
		gap: var(--space-xs);
	}

	.tab {
		padding: var(--space-xs) var(--space-md);
		font-size: var(--text-sm);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--bg-secondary);
		color: var(--text-secondary);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.tab:hover { background: var(--bg-tertiary); }
	.tab.active {
		background: var(--accent-muted);
		border-color: var(--accent);
		color: var(--accent);
		font-weight: 600;
	}

	/* Table */
	.table-wrapper {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.data-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	.data-table th {
		padding: var(--space-sm) var(--space-md);
		text-align: left;
		font-weight: 500;
		background: var(--bg-secondary);
		border-bottom: 1px solid var(--border-default);
		color: var(--text-muted);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		white-space: nowrap;
	}

	.data-table th.sortable {
		cursor: pointer;
		user-select: none;
	}

	.data-table th.sortable:hover {
		color: var(--text-primary);
	}

	.data-table td {
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-dim);
	}

	.clickable-row {
		cursor: pointer;
		transition: background var(--transition-fast);
	}

	.clickable-row:hover {
		background: var(--bg-secondary);
	}

	.mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}

	/* Status badges */
	.status-badge {
		display: inline-block;
		padding: var(--space-xs) var(--space-sm);
		font-size: var(--text-xs);
		font-weight: 600;
		border-radius: var(--radius-full);
		text-transform: uppercase;
	}

	.status-valid { background: var(--green-dim); color: var(--green); }
	.status-warning { background: var(--amber-dim); color: var(--amber); }
	.status-critical { background: var(--red-dim); color: var(--red); }
	.status-info { background: var(--cyan-dim); color: var(--accent); }

	/* Modal */
	.modal-overlay {
		position: fixed;
		inset: 0;
		background: var(--bg-overlay);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.modal-content {
		background: var(--bg-primary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
		max-width: 600px;
		width: 90%;
		max-height: 80vh;
		overflow-y: auto;
	}

	.modal-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-md);
	}

	.modal-header h3 {
		font-size: var(--text-lg);
		font-weight: 700;
	}

	.detail-grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.detail-row {
		display: flex;
		gap: var(--space-md);
		padding: var(--space-xs) 0;
		border-bottom: 1px solid var(--border-dim);
	}

	.detail-label {
		min-width: 120px;
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-secondary);
	}

	.detail-value {
		font-size: var(--text-sm);
		color: var(--text-primary);
	}

	@media (max-width: 768px) {
		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}

	@media (max-width: 480px) {
		.stats-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
