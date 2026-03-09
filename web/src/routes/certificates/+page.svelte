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
			<div class="stat-value">{stats.total_certs}</div>
			<div class="stat-label">Total Certificates</div>
		</div>
		<div class="stat-card" class:stat-warning={stats.expiring_count > 0}>
			<div class="stat-value">{stats.expiring_count}</div>
			<div class="stat-label">Expiring (30d)</div>
		</div>
		<div class="stat-card" class:stat-info={stats.self_signed_count > 0}>
			<div class="stat-value">{stats.self_signed_count}</div>
			<div class="stat-label">Self-Signed</div>
		</div>
		<div class="stat-card" class:stat-critical={stats.issuer_changes_count > 0}>
			<div class="stat-value">{stats.issuer_changes_count}</div>
			<div class="stat-label">Issuer Changes</div>
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
						<th>Domain</th>
						<th>Issuer</th>
						<th>Valid From</th>
						<th>Valid To</th>
						<th>Status</th>
						<th>Source</th>
					</tr>
				</thead>
				<tbody>
					{#each certificates as cert}
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

	.stat-card {
		padding: var(--space-md);
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		text-align: center;
	}

	.stat-value {
		font-size: var(--text-3xl);
		font-weight: 800;
		color: var(--text-primary);
	}

	.stat-label {
		font-size: var(--text-sm);
		color: var(--text-muted);
		margin-top: var(--space-xs);
	}

	.stat-warning .stat-value { color: var(--status-warning); }
	.stat-info .stat-value { color: var(--accent); }
	.stat-critical .stat-value { color: var(--status-critical); }

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
		font-weight: 600;
		background: var(--bg-secondary);
		border-bottom: 1px solid var(--border-default);
		color: var(--text-secondary);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.data-table td {
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-subtle);
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
		padding: 2px 8px;
		font-size: var(--text-xs);
		font-weight: 600;
		border-radius: var(--radius-full);
		text-transform: uppercase;
	}

	.status-valid { background: color-mix(in srgb, var(--status-success) 15%, transparent); color: var(--status-success); }
	.status-warning { background: color-mix(in srgb, var(--status-warning) 15%, transparent); color: var(--status-warning); }
	.status-critical { background: color-mix(in srgb, var(--status-critical) 15%, transparent); color: var(--status-critical); }
	.status-info { background: color-mix(in srgb, var(--accent) 15%, transparent); color: var(--accent); }

	/* Modal */
	.modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
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
		border-bottom: 1px solid var(--border-subtle);
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
