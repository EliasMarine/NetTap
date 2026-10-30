<script lang="ts">
	/**
	 * Device Inventory v2 — Card-based network device dashboard.
	 *
	 * Shows only DHCP-leased devices grouped by category (computer, phone, IoT,
	 * infrastructure, unknown) with hero stats, search, and category filters.
	 */

	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { getDevices } from '$api/devices';
	import type { Device } from '$api/devices';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = $state(true);
	let devices = $state<Device[]>([]);
	let searchQuery = $state('');
	let categoryFilter = $state('all');
	let viewMode = $state<'grid' | 'list'>('grid');
	let autoRefresh = $state(false);

	// List view sort state
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

	function sortArrow(field: string): string {
		if (sortField !== field) return '';
		return sortDir === 'asc' ? ' \u25B2' : ' \u25BC';
	}
	let autoRefreshTimer: ReturnType<typeof setInterval> | null = null;
	let lastUpdated = $state('');

	// ---------------------------------------------------------------------------
	// Category config
	// ---------------------------------------------------------------------------

	const CATEGORIES = [
		{ key: 'all', label: 'All', icon: '' },
		{ key: 'computer', label: 'Computers', icon: '\u{1F4BB}' },
		{ key: 'phone', label: 'Phones', icon: '\u{1F4F1}' },
		{ key: 'media', label: 'Media', icon: '\u{1F4FA}' },
		{ key: 'iot', label: 'IoT', icon: '\u{1F4E1}' },
		{ key: 'infrastructure', label: 'Infra', icon: '\u{1F5A7}' },
		{ key: 'unknown', label: 'Unknown', icon: '\u{2753}' },
	];

	const CATEGORY_COLORS: Record<string, string> = {
		computer: 'var(--cyan)', phone: 'var(--green)', media: 'var(--purple)',
		iot: 'var(--orange)', infrastructure: 'var(--blue)', unknown: 'var(--text-dim)',
	};

	const CATEGORY_ICONS: Record<string, string> = {
		computer: '\u{1F4BB}', phone: '\u{1F4F1}', media: '\u{1F4FA}',
		iot: '\u{1F4E1}', infrastructure: '\u{1F5A7}', unknown: '\u{2753}',
	};

	// ---------------------------------------------------------------------------
	// Fetching
	// ---------------------------------------------------------------------------

	async function fetchDevices() {
		loading = true;
		try {
			const res = await getDevices({ sort: 'bytes', order: 'desc', limit: 200 });
			devices = res.devices;
			lastUpdated = new Date().toLocaleTimeString();
		} catch {
			devices = [];
		} finally {
			loading = false;
		}
	}

	$effect(() => { fetchDevices(); });

	$effect(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		if (autoRefresh) {
			autoRefreshTimer = setInterval(() => fetchDevices(), 30_000);
		}
		return () => { if (autoRefreshTimer) clearInterval(autoRefreshTimer); };
	});

	onDestroy(() => { if (autoRefreshTimer) clearInterval(autoRefreshTimer); });

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let filteredDevices = $derived.by(() => {
		let list = [...devices];

		// Category filter
		if (categoryFilter !== 'all') {
			list = list.filter((d) => (d.category ?? 'unknown') === categoryFilter);
		}

		// Search filter
		if (searchQuery.trim()) {
			const q = searchQuery.trim().toLowerCase();
			list = list.filter((d) =>
				d.ip.toLowerCase().includes(q) ||
				(d.hostname && d.hostname.toLowerCase().includes(q)) ||
				(d.manufacturer && d.manufacturer.toLowerCase().includes(q)) ||
				(d.unifi_name && d.unifi_name.toLowerCase().includes(q)),
			);
		}

		return list;
	});

	// Category counts
	let categoryCounts = $derived.by(() => {
		const counts: Record<string, number> = { all: devices.length };
		for (const d of devices) {
			const cat = d.category ?? 'unknown';
			counts[cat] = (counts[cat] ?? 0) + 1;
		}
		return counts;
	});

	// Hero stats
	let onlineCount = $derived(devices.filter((d) => d.last_seen && (Date.now() - new Date(d.last_seen).getTime()) < 5 * 60 * 1000).length);
	let newCount = $derived(devices.filter((d) => d.first_seen && (Date.now() - new Date(d.first_seen).getTime()) < 24 * 60 * 60 * 1000).length);
	let topConsumer = $derived(devices.length > 0 ? devices[0] : null);

	// Max bytes for bar widths
	let maxBytes = $derived(devices.length > 0 ? Math.max(...devices.map((d) => d.total_bytes), 1) : 1);

	// Sorted list for table view
	let sortedDevices = $derived.by(() => {
		return [...filteredDevices].sort((a, b) => {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			const av = (a as any)[sortField] ?? 0;
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			const bv = (b as any)[sortField] ?? 0;
			const cmp = av < bv ? -1 : av > bv ? 1 : 0;
			return sortDir === 'asc' ? cmp : -cmp;
		});
	});

	// ---------------------------------------------------------------------------
	// Helpers
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

	function isOnline(d: Device): boolean {
		return !!d.last_seen && (Date.now() - new Date(d.last_seen).getTime()) < 5 * 60 * 1000;
	}

	function isIdle(d: Device): boolean {
		if (!d.last_seen) return false;
		const diff = Date.now() - new Date(d.last_seen).getTime();
		return diff >= 5 * 60 * 1000 && diff < 60 * 60 * 1000;
	}

	function timeAgo(dateStr: string): string {
		if (!dateStr) return '--';
		const diff = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	function catColor(d: Device): string {
		return CATEGORY_COLORS[d.category ?? 'unknown'] ?? 'var(--text-dim)';
	}

	function catIcon(d: Device): string {
		return CATEGORY_ICONS[d.category ?? 'unknown'] ?? '\u{2753}';
	}
</script>

<svelte:head>
	<title>Devices | NetTap</title>
</svelte:head>

<div class="devices-page">
	<!-- Page Header -->
	<div class="page-header">
		<div>
			<h1>Device Inventory</h1>
			<p class="subtitle">{devices.length} DHCP-leased devices{lastUpdated ? ` \u00b7 Updated ${lastUpdated}` : ''}</p>
		</div>
		<div class="header-controls">
			<button class="auto-btn" class:active={autoRefresh} onclick={() => (autoRefresh = !autoRefresh)}>
				<span class="auto-dot"></span> {autoRefresh ? 'Auto ON' : 'Auto OFF'}
			</button>
			<button class="refresh-btn" onclick={() => fetchDevices()}>Refresh</button>
		</div>
	</div>

	{#if loading && devices.length === 0}
		<div class="loading-state">
			<div class="loading-spinner"></div>
			<span class="text-muted">Discovering devices...</span>
		</div>
	{:else}
		<!-- Hero Stats -->
		<div class="stats-grid">
			<div class="stat-card stat-accent">
				<div class="stat-label">Total Devices</div>
				<div class="stat-value accent">{devices.length}</div>
				<div class="stat-sub">DHCP-leased</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Online Now</div>
				<div class="stat-value" style="color: var(--green);">{onlineCount}</div>
				<div class="stat-sub">last 5 min</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">New (24h)</div>
				<div class="stat-value" style="color: var(--amber);">{newCount}</div>
				<div class="stat-sub">first seen today</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Top Consumer</div>
				<div class="stat-value" style="font-size: var(--text-lg);">{topConsumer ? formatBytes(topConsumer.total_bytes) : '--'}</div>
				<div class="stat-sub">{topConsumer?.unifi_name ?? topConsumer?.hostname ?? topConsumer?.ip ?? '--'}</div>
			</div>
		</div>

		<!-- Category Filter + Search -->
		<div class="filter-bar">
			<div class="category-pills">
				{#each CATEGORIES as cat}
					<button
						class="cat-pill"
						class:active={categoryFilter === cat.key}
						onclick={() => (categoryFilter = cat.key)}
					>
						{#if cat.icon}<span class="cat-pill-icon">{cat.icon}</span>{/if}
						{cat.label}
						<span class="cat-pill-count">{categoryCounts[cat.key] ?? 0}</span>
					</button>
				{/each}
			</div>
			<div class="filter-right">
				<div class="view-toggle">
					<button class="view-btn" class:active={viewMode === 'grid'} onclick={() => (viewMode = 'grid')} title="Grid view">&#x25A6;</button>
					<button class="view-btn" class:active={viewMode === 'list'} onclick={() => (viewMode = 'list')} title="List view">&#x2630;</button>
				</div>
				<div class="search-wrap">
					<input type="text" class="search-input" placeholder="Search by IP, hostname, or vendor..." bind:value={searchQuery} />
				</div>
			</div>
		</div>

		<!-- Device Cards Grid -->
		{#if filteredDevices.length === 0}
			<div class="empty-state">
				{#if searchQuery || categoryFilter !== 'all'}
					<p class="empty-text">No devices matching your filter.</p>
					<button class="reset-btn" onclick={() => { searchQuery = ''; categoryFilter = 'all'; }}>Reset filters</button>
				{:else}
					<p class="empty-text">No DHCP-leased devices found.</p>
					<p class="empty-hint">Devices appear when they obtain an IP from the network's DHCP server.</p>
				{/if}
			</div>
		{:else if viewMode === 'grid'}
			<!-- Grid View -->
			<div class="device-grid">
				{#each filteredDevices as device, i (`grid-${device.ip}-${i}`)}
					<button
						class="device-card"
						style="border-left-color: {catColor(device)}; animation-delay: {i * 30}ms;"
						onclick={() => goto(`/devices/${encodeURIComponent(device.ip)}`)}
						type="button"
					>
						<div class="dc-header">
							<span class="dc-status" class:online={isOnline(device)} class:idle={isIdle(device)}></span>
							<span class="dc-icon">{catIcon(device)}</span>
							<div class="dc-identity">
								{#if device.unifi_name}
									<span class="dc-name">{device.unifi_name} <span class="badge badge-muted" style="font-size: 10px;">UniFi</span></span>
									<span class="dc-hostname">{device.hostname ?? device.ip}</span>
								{:else}
									<span class="dc-ip mono">{device.ip}</span>
									{#if device.hostname}
										<span class="dc-hostname">{device.hostname}</span>
									{/if}
								{/if}
							</div>
						</div>

						<div class="dc-meta">
							{#if device.os_hint}<span>{device.os_hint}</span>{/if}
							{#if device.manufacturer}<span class="dc-sep">&middot;</span><span>{device.manufacturer}</span>{/if}
						</div>

						<div class="dc-bandwidth">
							<div class="dc-bar-track">
								<div class="dc-bar-fill" style="width: {(device.total_bytes / maxBytes) * 100}%; background: {catColor(device)};"></div>
							</div>
							<span class="dc-bar-value mono">{formatBytes(device.total_bytes)}</span>
						</div>

						<div class="dc-stats">
							<span class="mono">{formatNumber(device.connection_count)} conn</span>
							{#if device.alert_count > 0}
								<span class="dc-alerts">{formatNumber(device.alert_count)} alerts</span>
							{/if}
							<span class="dc-lastseen">{timeAgo(device.last_seen)}</span>
						</div>

						{#if device.mac}
							<div class="dc-mac mono">{device.mac}</div>
						{/if}
					</button>
				{/each}
			</div>
		{:else}
			<!-- List View -->
			<div class="list-card">
				<div class="table-wrap">
					<table class="data-table">
						<thead>
							<tr>
								<th></th>
								<th class="sortable" class:sorted={sortField === 'ip'} onclick={() => toggleSort('ip')}>IP Address{sortArrow('ip')}</th>
								<th class="sortable" class:sorted={sortField === 'hostname'} onclick={() => toggleSort('hostname')}>Hostname{sortArrow('hostname')}</th>
								<th>Category</th>
								<th>OS</th>
								<th>Manufacturer</th>
								<th class="sortable" class:sorted={sortField === 'total_bytes'} onclick={() => toggleSort('total_bytes')}>Bandwidth{sortArrow('total_bytes')}</th>
								<th class="sortable" class:sorted={sortField === 'connection_count'} onclick={() => toggleSort('connection_count')}>Connections{sortArrow('connection_count')}</th>
								<th class="sortable" class:sorted={sortField === 'alert_count'} onclick={() => toggleSort('alert_count')}>Alerts{sortArrow('alert_count')}</th>
								<th class="sortable" class:sorted={sortField === 'last_seen'} onclick={() => toggleSort('last_seen')}>Last Seen{sortArrow('last_seen')}</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedDevices as device, i (`list-${device.ip}-${i}`)}
								<tr class="list-row" onclick={() => goto(`/devices/${encodeURIComponent(device.ip)}`)}>
									<td><span class="dc-status" class:online={isOnline(device)} class:idle={isIdle(device)}></span></td>
									<td class="mono" style="font-size: var(--text-sm); font-weight: 500;">{device.ip}</td>
									<td style="font-size: var(--text-sm); color: var(--text-secondary);">
									{#if device.unifi_name}
										<div>{device.unifi_name} <span class="badge badge-muted" style="font-size: 10px;">UniFi</span></div>
										<div style="font-size: var(--text-xs); color: var(--text-muted);">{device.hostname ?? '--'}</div>
									{:else}
										{device.hostname ?? '--'}
									{/if}
								</td>
									<td>
										<span class="cat-badge" style="color: {catColor(device)}; background: color-mix(in srgb, {catColor(device)} 12%, transparent);">
											{catIcon(device)} {(device.category ?? 'unknown').replace(/^\w/, (c: string) => c.toUpperCase())}
										</span>
									</td>
									<td style="font-size: var(--text-xs); color: var(--text-muted);">{device.os_hint ?? '--'}</td>
									<td style="font-size: var(--text-xs); color: var(--text-muted);">{device.manufacturer ?? '--'}</td>
									<td class="mono" style="font-size: var(--text-sm);">{formatBytes(device.total_bytes)}</td>
									<td class="mono" style="font-size: var(--text-sm);">{formatNumber(device.connection_count)}</td>
									<td class="mono" style="font-size: var(--text-sm); {device.alert_count > 0 ? 'color: var(--amber); font-weight: 600;' : ''}">{device.alert_count > 0 ? formatNumber(device.alert_count) : '--'}</td>
									<td style="font-size: var(--text-xs); color: var(--text-muted); white-space: nowrap;">{timeAgo(device.last_seen)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	.devices-page { display: flex; flex-direction: column; gap: var(--space-lg); }

	/* Header */
	.page-header { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: var(--space-md); }
	h1 { font-size: var(--text-2xl); font-weight: 700; letter-spacing: -0.02em; }
	.subtitle { font-size: var(--text-sm); color: var(--text-muted); margin-top: 2px; }
	.header-controls { display: flex; align-items: center; gap: var(--space-sm); }
	.auto-btn { display: flex; align-items: center; gap: 6px; padding: 6px 12px; background: var(--bg-tertiary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); color: var(--text-muted); font-size: var(--text-xs); font-family: var(--font-sans); cursor: pointer; transition: all var(--transition-fast); }
	.auto-btn.active { border-color: var(--cyan); color: var(--cyan); background: rgba(0,212,255,0.06); }
	.auto-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-dim); }
	.auto-btn.active .auto-dot { background: var(--cyan); box-shadow: 0 0 6px rgba(0,212,255,0.5); }
	.refresh-btn { padding: 6px 14px; background: var(--bg-tertiary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); color: var(--text-secondary); font-size: var(--text-xs); font-family: var(--font-sans); cursor: pointer; transition: all var(--transition-fast); }
	.refresh-btn:hover { border-color: var(--border-default); color: var(--text-primary); }

	/* Loading / Empty */
	.loading-state { display: flex; align-items: center; justify-content: center; gap: var(--space-md); padding: var(--space-3xl); }
	.empty-state { text-align: center; padding: var(--space-3xl); }
	.empty-text { font-size: var(--text-lg); color: var(--text-primary); margin-bottom: var(--space-sm); }
	.empty-hint { font-size: var(--text-sm); color: var(--text-muted); }
	.reset-btn { margin-top: var(--space-md); padding: 6px 16px; background: var(--bg-tertiary); border: 1px solid var(--border-dim); border-radius: var(--radius-sm); color: var(--text-secondary); font-size: var(--text-xs); cursor: pointer; font-family: var(--font-sans); }

	/* Stats */
	.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-md); }
	.stat-card { background: var(--bg-secondary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); padding: var(--space-md); position: relative; overflow: hidden; }
	.stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--border-dim); }
	.stat-accent::before { background: var(--cyan); box-shadow: 0 0 10px rgba(0,212,255,0.3); }
	.stat-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 500; margin-bottom: 6px; }
	.stat-value { font-family: var(--font-mono); font-size: var(--text-3xl); font-weight: 600; color: var(--text-primary); letter-spacing: -0.02em; line-height: 1; }
	.stat-value.accent { color: var(--cyan); }
	.stat-sub { font-size: 10px; color: var(--text-dim); margin-top: 6px; font-family: var(--font-mono); }

	/* Filter Bar */
	.filter-bar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md); flex-wrap: wrap; }
	.category-pills { display: flex; gap: 4px; flex-wrap: wrap; }
	.cat-pill { display: flex; align-items: center; gap: 6px; padding: 6px 14px; border: 1px solid var(--border-dim); background: var(--bg-secondary); color: var(--text-muted); font-size: var(--text-xs); font-weight: 500; border-radius: var(--radius-md); cursor: pointer; font-family: var(--font-sans); transition: all var(--transition-fast); }
	.cat-pill:hover { border-color: var(--border-default); color: var(--text-secondary); }
	.cat-pill.active { background: var(--cyan); color: var(--bg-void); border-color: var(--cyan); font-weight: 600; }
	.cat-pill-icon { font-size: 14px; }
	.cat-pill-count { font-family: var(--font-mono); font-size: 10px; opacity: 0.7; }
	.filter-right { display: flex; align-items: center; gap: var(--space-sm); }
	.view-toggle { display: flex; gap: 2px; background: var(--bg-tertiary); border-radius: var(--radius-md); padding: 2px; border: 1px solid var(--border-dim); }
	.view-btn { width: 32px; height: 28px; border: none; background: transparent; color: var(--text-muted); font-size: 14px; border-radius: 5px; cursor: pointer; transition: all var(--transition-fast); display: flex; align-items: center; justify-content: center; }
	.view-btn:hover { color: var(--text-primary); background: var(--bg-elevated); }
	.view-btn.active { background: var(--cyan); color: var(--bg-void); }
	.search-wrap { max-width: 300px; flex: 1; }
	.search-input { width: 100%; padding: 7px 14px; background: var(--bg-input); border: 1px solid var(--border-dim); border-radius: var(--radius-md); color: var(--text-primary); font-family: var(--font-mono); font-size: var(--text-xs); outline: none; transition: border-color var(--transition-fast); }
	.search-input::placeholder { color: var(--text-dim); }
	.search-input:focus { border-color: var(--accent); }

	/* Device Cards Grid */
	.device-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-md); }

	.device-card {
		display: flex; flex-direction: column; gap: var(--space-sm);
		padding: var(--space-md);
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-left: 3px solid var(--text-dim);
		border-radius: var(--radius-md);
		cursor: pointer;
		text-align: left;
		font: inherit; color: inherit;
		transition: all var(--transition-fast);
		animation: cardIn 0.3s ease both;
	}

	.device-card:hover { border-color: var(--border-bright); background: var(--bg-tertiary); transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.3); }

	@keyframes cardIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

	/* Card internals */
	.dc-header { display: flex; align-items: center; gap: var(--space-sm); }
	.dc-status { width: 8px; height: 8px; border-radius: 50%; background: var(--text-dim); flex-shrink: 0; }
	.dc-status.online { background: var(--green); box-shadow: 0 0 6px rgba(0,230,118,0.5); }
	.dc-status.idle { background: var(--amber); }
	.dc-icon { font-size: 16px; flex-shrink: 0; }
	.dc-identity { min-width: 0; overflow: hidden; }
	.dc-ip { font-size: var(--text-sm); font-weight: 600; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: color var(--transition-fast); }
	.device-card:hover .dc-ip { color: var(--accent); }
	.dc-name { font-size: var(--text-sm); font-weight: 600; display: flex; align-items: center; gap: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: color var(--transition-fast); }
	.device-card:hover .dc-name { color: var(--accent); }
	.dc-hostname { font-size: var(--text-xs); color: var(--text-muted); display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

	.dc-meta { font-size: var(--text-xs); color: var(--text-dim); display: flex; align-items: center; gap: 4px; }
	.dc-sep { color: var(--text-dim); }

	.dc-bandwidth { display: flex; align-items: center; gap: var(--space-sm); }
	.dc-bar-track { flex: 1; height: 6px; background: var(--bg-tertiary); border-radius: 3px; overflow: hidden; }
	.dc-bar-fill { height: 100%; border-radius: 3px; opacity: 0.7; transition: width var(--transition-slow); }
	.device-card:hover .dc-bar-fill { opacity: 1; }
	.dc-bar-value { font-size: var(--text-xs); color: var(--text-secondary); white-space: nowrap; min-width: 50px; text-align: right; }

	.dc-stats { display: flex; align-items: center; gap: var(--space-sm); font-size: 10px; color: var(--text-dim); flex-wrap: wrap; }
	.dc-alerts { color: var(--amber); font-weight: 600; }
	.dc-lastseen { margin-left: auto; }

	.dc-mac { font-size: 10px; color: var(--text-dim); opacity: 0; transition: opacity var(--transition-fast); }
	.device-card:hover .dc-mac { opacity: 1; }

	/* Responsive */
	@media (max-width: 1280px) { .device-grid { grid-template-columns: repeat(3, 1fr); } }
	@media (max-width: 1024px) { .device-grid { grid-template-columns: repeat(2, 1fr); } .stats-grid { grid-template-columns: repeat(2, 1fr); } }
	/* List View */
	.list-card { background: var(--bg-secondary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); overflow: hidden; }
	.table-wrap { overflow-x: auto; }
	.data-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
	.data-table th { padding: var(--space-sm) var(--space-md); text-align: left; font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; background: var(--bg-tertiary); border-bottom: 1px solid var(--border-dim); white-space: nowrap; }
	.data-table th.sortable { cursor: pointer; user-select: none; transition: color var(--transition-fast); }
	.data-table th.sortable:hover { color: var(--text-primary); }
	.data-table th.sorted { color: var(--accent); }
	.data-table td { padding: var(--space-sm) var(--space-md); border-bottom: 1px solid var(--border-dim); vertical-align: middle; }
	.data-table tbody tr { transition: background var(--transition-fast); }
	.data-table tbody tr:hover { background: var(--bg-tertiary); }
	.data-table tbody tr:last-child td { border-bottom: none; }
	.list-row { cursor: pointer; }
	.cat-badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: var(--radius-sm); font-size: 10px; font-weight: 600; white-space: nowrap; }

	@media (max-width: 768px) { .device-grid { grid-template-columns: 1fr; } .stats-grid { grid-template-columns: 1fr; } }
</style>
