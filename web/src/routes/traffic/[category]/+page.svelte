<script lang="ts">
	/**
	 * Traffic Category Detail — Per-device bandwidth breakdown for a category.
	 *
	 * Layout:
	 *   - Back link, category icon + name, time range pills
	 *   - Stat cards row: Total Bandwidth, Active Devices, Connections
	 *   - Content grid: Per-device table (sortable) + Top Domains sidebar
	 */

	import { page } from '$app/stores';
	import { getCategoryDetail, getTrafficCategories } from '$api/traffic';
	import type { CategoryDetailResponse, TrafficCategoryDomain } from '$api/traffic';
	import HorizontalBarList from '$components/HorizontalBarList.svelte';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Category metadata
	// ---------------------------------------------------------------------------

	const CATEGORY_META: Record<string, { icon: string; color: string }> = {
		streaming: { icon: '\u25B6', color: 'var(--red)' },
		gaming: { icon: '\uD83C\uDFAE', color: 'var(--purple)' },
		social: { icon: '\uD83D\uDC65', color: 'var(--blue)' },
		communication: { icon: '\uD83D\uDCAC', color: 'var(--amber)' },
		work: { icon: '\uD83D\uDCBC', color: 'var(--green)' },
		iot: { icon: '\uD83D\uDCE1', color: 'var(--orange)' },
		cloud: { icon: '\u2601', color: 'var(--cyan)' },
		file_transfer: { icon: '\uD83D\uDCC1', color: 'var(--teal)' },
		dns: { icon: '\uD83C\uDF10', color: 'var(--text-muted)' },
		email: { icon: '\u2709', color: 'var(--pink)' },
		web: { icon: '\uD83D\uDD17', color: 'var(--accent)' },
		security: { icon: '\uD83D\uDD12', color: 'var(--green)' },
		shopping: { icon: '\uD83D\uDED2', color: 'var(--orange)' },
		news: { icon: '\uD83D\uDCF0', color: 'var(--blue)' },
		ads: { icon: '\uD83D\uDCCA', color: 'var(--text-muted)' },
		updates: { icon: '\u2B07', color: 'var(--teal)' },
		suspicious: { icon: '\u26A0', color: 'var(--red)' },
		other: { icon: '\u2026', color: 'var(--text-muted)' },
	};

	// ---------------------------------------------------------------------------
	// Time range pills
	// ---------------------------------------------------------------------------

	const TIME_RANGES = [
		{ label: '1h', value: '1h' },
		{ label: '6h', value: '6h' },
		{ label: '24h', value: '24h' },
		{ label: '7d', value: '7d' },
		{ label: '30d', value: '30d' },
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let category = $derived($page.params.category ?? 'other');
	let meta = $derived(CATEGORY_META[category] ?? CATEGORY_META['other']);
	let selectedRange = $state('24h');
	let data = $state<CategoryDetailResponse | null>(null);
	let loading = $state(true);
	let topDomains = $state<TrafficCategoryDomain[]>([]);

	// Sort state
	let sortField = $state<string>('total_bytes');
	let sortDir = $state<'asc' | 'desc'>('desc');

	function toggleSort(field: string) {
		if (sortField === field) {
			sortDir = sortDir === 'desc' ? 'asc' : 'desc';
		} else {
			sortField = field;
			sortDir = 'desc';
		}
	}

	let sortedDevices = $derived.by(() => {
		if (!data?.devices) return [];
		return [...data.devices].sort((a, b) => {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			const av = (a as any)[sortField] ?? 0;
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			const bv = (b as any)[sortField] ?? 0;
			const cmp = av < bv ? -1 : av > bv ? 1 : 0;
			return sortDir === 'asc' ? cmp : -cmp;
		});
	});

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	function computeTimeParams(range: string): { from?: string; to?: string } {
		const now = new Date();
		let from: Date;
		switch (range) {
			case '1h':
				from = new Date(now.getTime() - 60 * 60 * 1000);
				break;
			case '6h':
				from = new Date(now.getTime() - 6 * 60 * 60 * 1000);
				break;
			case '7d':
				from = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
				break;
			case '30d':
				from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
				break;
			default: // 24h
				from = new Date(now.getTime() - 24 * 60 * 60 * 1000);
				break;
		}
		return { from: from.toISOString(), to: now.toISOString() };
	}

	async function fetchData() {
		loading = true;
		const timeParams = computeTimeParams(selectedRange);

		try {
			const [detailRes, categoriesRes] = await Promise.allSettled([
				getCategoryDetail(category, timeParams),
				getTrafficCategories(timeParams),
			]);

			data = detailRes.status === 'fulfilled' ? detailRes.value : null;

			// Extract top_domains from the matching category in the categories response
			if (categoriesRes.status === 'fulfilled') {
				const matchingCat = categoriesRes.value.categories.find(
					(c) => c.name === category
				);
				topDomains = matchingCat?.top_domains ?? [];
			} else {
				topDomains = [];
			}
		} catch {
			data = null;
			topDomains = [];
		} finally {
			loading = false;
		}
	}

	// Refetch when selectedRange or category changes
	$effect(() => {
		// Read reactive values to track them
		const _range = selectedRange;
		const _cat = category;
		// Avoid unused variable lint warnings
		void _range;
		void _cat;
		fetchData();
	});

	// ---------------------------------------------------------------------------
	// Format helpers
	// ---------------------------------------------------------------------------

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toLocaleString();
	}

	function sortArrow(field: string): string {
		if (sortField !== field) return '';
		return sortDir === 'asc' ? ' \u25B2' : ' \u25BC';
	}

	// Category display name
	let displayName = $derived(data?.label ?? category.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()));

	// Max bytes for inline bar widths in the table
	let maxDeviceBytes = $derived.by(() => {
		if (!data?.devices?.length) return 1;
		return Math.max(...data.devices.map((d) => d.total_bytes), 1);
	});
</script>

<svelte:head>
	<title>{displayName} Traffic | NetTap</title>
</svelte:head>

<div class="category-detail">
	<!-- Page header -->
	<div class="page-header">
		<div class="header-left">
			<a href="/" class="back-link">&larr; Back</a>
			<div class="category-title">
				<span class="category-icon" style="color: {meta.color};">{meta.icon}</span>
				<div>
					<h2>{displayName}</h2>
					<p class="text-muted">Per-device bandwidth breakdown</p>
				</div>
			</div>
		</div>
		<div class="pills">
			{#each TIME_RANGES as range}
				<button
					class="pill"
					class:active={selectedRange === range.value}
					onclick={() => (selectedRange = range.value)}
				>
					{range.label}
				</button>
			{/each}
		</div>
	</div>

	<!-- Loading state -->
	{#if loading}
		<div class="loading-state">
			<div class="loading-spinner"></div>
			<span class="text-muted">Loading category data...</span>
		</div>
	{:else if !data || (data.device_count === 0 && data.total_bytes === 0)}
		<!-- Empty state -->
		<div class="empty-state">
			<div class="empty-icon">{meta.icon}</div>
			<p class="empty-text">No traffic data for {displayName}</p>
			<p class="empty-hint">Try expanding the time range or check that devices are generating traffic in this category.</p>
		</div>
	{:else}
		<!-- Stats grid -->
		<div class="stats-grid">
			<div class="card stat-card">
				<div class="stat-label">Total Bandwidth</div>
				<div class="stat-value" style="color: {meta.color};">
					{formatBytes(data.total_bytes)}
				</div>
			</div>
			<div class="card stat-card">
				<div class="stat-label">Active Devices</div>
				<div class="stat-value">
					{formatNumber(data.device_count)}
				</div>
			</div>
			<div class="card stat-card">
				<div class="stat-label">Connections</div>
				<div class="stat-value">
					{formatNumber(data.connection_count)}
				</div>
			</div>
		</div>

		<!-- Content grid: table + sidebar -->
		<div class="content-grid">
			<!-- Per-device breakdown table -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Per-Device Breakdown</span>
					<span class="card-badge badge badge-muted">{data.devices.length} devices</span>
				</div>
				<div class="table-wrap">
					<table class="data-table">
						<thead>
							<tr>
								<th
									class="sortable"
									class:sorted={sortField === 'ip'}
									onclick={() => toggleSort('ip')}
								>
									Device{sortArrow('ip')}
								</th>
								<th
									class="sortable"
									class:sorted={sortField === 'total_bytes'}
									onclick={() => toggleSort('total_bytes')}
								>
									Total Data{sortArrow('total_bytes')}
								</th>
								<th
									class="sortable"
									class:sorted={sortField === 'download_bytes'}
									onclick={() => toggleSort('download_bytes')}
								>
									Download{sortArrow('download_bytes')}
								</th>
								<th
									class="sortable"
									class:sorted={sortField === 'upload_bytes'}
									onclick={() => toggleSort('upload_bytes')}
								>
									Upload{sortArrow('upload_bytes')}
								</th>
								<th
									class="sortable"
									class:sorted={sortField === 'connections'}
									onclick={() => toggleSort('connections')}
								>
									Connections{sortArrow('connections')}
								</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedDevices as device (device.ip)}
								<tr>
									<td>
										<a href="/devices/{encodeURIComponent(device.ip)}" class="device-link">
											<IPAddress ip={device.ip} />
											{#if device.hostname}
												<span class="device-hostname">{device.hostname}</span>
											{/if}
										</a>
									</td>
									<td>
										<div class="bytes-cell">
											<span class="mono">{formatBytes(device.total_bytes)}</span>
											<div class="inline-bar">
												<div
													class="inline-bar-fill"
													style="width: {(device.total_bytes / maxDeviceBytes) * 100}%; background: {meta.color};"
												></div>
											</div>
										</div>
									</td>
									<td class="mono">{formatBytes(device.download_bytes)}</td>
									<td class="mono">{formatBytes(device.upload_bytes)}</td>
									<td class="mono">{formatNumber(device.connections)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>

			<!-- Top Domains sidebar -->
			<div class="card sidebar-card">
				<div class="card-header">
					<span class="card-title">Top Domains</span>
				</div>
				{#if topDomains.length > 0}
					<HorizontalBarList
						items={topDomains.map((d) => ({
							key: d.domain,
							label: d.domain,
							value: d.count,
							formattedValue: formatNumber(d.count),
							color: meta.color,
						}))}
						showDot={true}
						labelWidth={160}
						barHeight={10}
					/>
				{:else}
					<p class="text-muted sidebar-empty">No domain data available.</p>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.category-detail {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Header */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-md);
	}

	.header-left {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.back-link {
		font-size: var(--text-sm);
		color: var(--text-muted);
		text-decoration: none;
		transition: color var(--transition-fast);
	}

	.back-link:hover {
		color: var(--accent);
	}

	.category-title {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.category-icon {
		font-size: var(--text-3xl);
		line-height: 1;
	}

	.category-title h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		margin-bottom: var(--space-xs);
	}

	/* Loading state */
	.loading-state {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-md);
		padding: var(--space-3xl);
	}

	/* Stats grid */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-md);
	}

	/* Content grid */
	.content-grid {
		display: grid;
		grid-template-columns: 2fr 1fr;
		gap: var(--space-md);
		align-items: start;
	}

	.sidebar-card {
		position: sticky;
		top: var(--space-md);
	}

	.sidebar-empty {
		padding: var(--space-lg);
		text-align: center;
		font-size: var(--text-sm);
	}

	/* Table styling */
	.table-wrap {
		overflow-x: auto;
	}

	.device-link {
		display: flex;
		flex-direction: column;
		gap: 2px;
		text-decoration: none;
		color: inherit;
	}

	.device-hostname {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* Inline bar in table */
	.bytes-cell {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 120px;
	}

	.inline-bar {
		height: 4px;
		background: var(--bg-tertiary);
		border-radius: 2px;
		overflow: hidden;
	}

	.inline-bar-fill {
		height: 100%;
		border-radius: 2px;
		transition: width 0.4s ease-out;
		min-width: 2px;
	}

	/* Responsive */
	@media (max-width: 1024px) {
		.stats-grid {
			grid-template-columns: 1fr;
		}

		.content-grid {
			grid-template-columns: 1fr;
		}

		.sidebar-card {
			position: static;
		}
	}

	@media (max-width: 768px) {
		.page-header {
			flex-direction: column;
		}
	}
</style>
