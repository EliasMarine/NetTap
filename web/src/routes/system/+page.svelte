<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { getSystemHealth, getStorageStatus, getSmartHealth } from '$api/system.js';
	import { getTSharkStatus } from '$api/tshark.js';
	import { getCyberChefStatus } from '$api/cyberchef.js';
	import type { SystemHealth, StorageStatus, SmartHealth } from '$api/system.js';
	import type { TSharkStatus } from '$api/tshark.js';
	import type { CyberChefStatus } from '$api/cyberchef.js';
	import BridgeStatus from '$lib/components/BridgeStatus.svelte';
	import { getCaptureMode } from '$api/capture.js';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import Pipeline, { type PipelineStage } from '$lib/components/ui/Pipeline.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { loadFailed } from '$lib/utils/load-failed';

	let systemHealth = $state<SystemHealth | null>(null);
	let storageStatus = $state<StorageStatus | null>(null);
	let smartHealth = $state<SmartHealth | null>(null);
	let tsharkStatus = $state<TSharkStatus | null>(null);
	let cyberchefStatus = $state<CyberChefStatus | null>(null);
	let loading = $state(true);
	// #96: which cards' last request failed; a failure never reads as "Degraded" or "Not Deployed"
	let failed = $state({ health: false, storage: false, smart: false, tshark: false, cyberchef: false });
	// BridgeStatus (and its /api/bridge polling) only makes sense in bridge mode
	let captureModeName = $state<string | null>(null);
	let captureModeFailed = $state(false);

	function formatBytes(bytes: number | null | undefined): string {
		if (bytes == null || !isFinite(bytes) || bytes <= 0) return '—';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const val = bytes / Math.pow(1024, i);
		return `${val.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	}

	function formatUptime(seconds: number): string {
		if (seconds <= 0) return '—';
		const days = Math.floor(seconds / 86400);
		const hours = Math.floor((seconds % 86400) / 3600);
		const minutes = Math.floor((seconds % 3600) / 60);
		const parts: string[] = [];
		if (days > 0) parts.push(`${days}d`);
		if (hours > 0) parts.push(`${hours}h`);
		if (minutes > 0 || parts.length === 0) parts.push(`${minutes}m`);
		return parts.join(' ');
	}

	// OLD CODE START — colour-only warnings; the design system shows state with a word and a
	// shape (the health strip's warn icon), never colour alone
	// function diskUsageColor(percent: number): string {
	// 	if (percent > 85) return 'var(--danger)';
	// 	if (percent > 70) return 'var(--warning)';
	// 	return 'var(--success)';
	// }
	//
	// function tempColor(temp: number): string {
	// 	if (temp > 70) return 'var(--danger)';
	// 	if (temp > 55) return 'var(--warning)';
	// 	return 'var(--success)';
	// }
	// OLD CODE END
	// the old bar turned red above this share
	const DISK_FULL_PERCENT = 85;

	// OLD CODE START — the page refresh contract (PLAN.md §5.5): the top bar's Refresh runs the
	// page loader, which reports what loaded and drops a reply that lands after the page has gone
	// async function fetchAll() {
	// 	loading = true;
	// 	// OLD CODE START — #96: the getters faked "unhealthy" defaults on failure, and one
	// 	// failure blanked every card; they now throw, so each card is settled on its own
	// 	// try {
	// 	// 	const [health, storage, smart, tshark, cyberchef] = await Promise.all([
	// 	// 		getSystemHealth(),
	// 	// 		getStorageStatus(),
	// 	// 		getSmartHealth(),
	// 	// 		getTSharkStatus(),
	// 	// 		getCyberChefStatus(),
	// 	// 	]);
	// 	// 	systemHealth = health;
	// 	// 	storageStatus = storage;
	// 	// 	smartHealth = smart;
	// 	// 	tsharkStatus = tshark;
	// 	// 	cyberchefStatus = cyberchef;
	// 	// } catch {
	// 	// 	// Keep existing state on error
	// 	// } finally {
	// 	// 	loading = false;
	// 	// }
	// 	// OLD CODE END
	// 	const [health, storage, smart, tshark, cyberchef] = await Promise.allSettled([
	// 		getSystemHealth(),
	// 		getStorageStatus(),
	// 		getSmartHealth(),
	// 		getTSharkStatus(),
	// 		getCyberChefStatus(),
	// 	]);
	// 	// a failed refresh keeps the last reading; the card says the refresh failed
	// 	if (health.status === 'fulfilled') systemHealth = health.value;
	// 	if (storage.status === 'fulfilled') storageStatus = storage.value;
	// 	if (smart.status === 'fulfilled') smartHealth = smart.value;
	// 	if (tshark.status === 'fulfilled') tsharkStatus = tshark.value;
	// 	if (cyberchef.status === 'fulfilled') cyberchefStatus = cyberchef.value;
	// 	failed = {
	// 		health: health.status === 'rejected',
	// 		storage: storage.status === 'rejected',
	// 		smart: smart.status === 'rejected',
	// 		tshark: tshark.status === 'rejected',
	// 		cyberchef: cyberchef.status === 'rejected',
	// 	};
	// 	loading = false;
	// }
	//
	// $effect(() => {
	// 	fetchAll();
	// 	getCaptureMode()
	// 		.then((m) => {
	// 			captureModeName = m.mode;
	// 		})
	// 		.catch(() => {
	// 			captureModeFailed = true; // #96: the getter no longer guesses 'bridge'
	// 		});
	// });
	// OLD CODE END
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// the capture mode is read on every load now, so a failed first read can recover
		const results = await Promise.allSettled([
			getSystemHealth(),
			getStorageStatus(),
			getSmartHealth(),
			getTSharkStatus(),
			getCyberChefStatus(),
			getCaptureMode(),
		]);
		if (!guard.current(g)) return 'skipped';
		const [health, storage, smart, tshark, cyberchef, mode] = results;
		// a failed refresh keeps the last reading; the card says the refresh failed
		if (health.status === 'fulfilled') systemHealth = health.value;
		if (storage.status === 'fulfilled') storageStatus = storage.value;
		if (smart.status === 'fulfilled') smartHealth = smart.value;
		if (tshark.status === 'fulfilled') tsharkStatus = tshark.value;
		if (cyberchef.status === 'fulfilled') cyberchefStatus = cyberchef.value;
		if (mode.status === 'fulfilled') captureModeName = mode.value.mode;
		failed = {
			health: health.status === 'rejected',
			storage: storage.status === 'rejected',
			smart: smart.status === 'rejected',
			tshark: tshark.status === 'rejected',
			cyberchef: cyberchef.status === 'rejected',
		};
		// #96: the getter no longer guesses 'bridge'; a reading from an earlier load still stands
		captureModeFailed = mode.status === 'rejected' && captureModeName === null;
		loading = false;
		const failures = results.filter((r) => r.status === 'rejected').length;
		return failures === 0 ? 'ok' : failures === results.length ? 'failed' : 'partial';
	}

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);
	onMount(() => void refresh.run());
	const retry = () => void refresh.run();

	// One stage per part this page reads; a stage with no reading is "unknown", never healthy
	const stages = $derived.by((): PipelineStage[] => {
		const waiting = (key: string, label: string, didFail: boolean): PipelineStage => ({
			key,
			label,
			status: 'unknown',
			detail: didFail ? 'Request failed' : 'Checking…',
		});
		const daemon: PipelineStage =
			systemHealth && !failed.health
				? { key: 'daemon', label: 'NetTap', status: systemHealth.healthy ? 'ok' : 'failing', detail: systemHealth.healthy ? `Up ${formatUptime(systemHealth.uptime)}` : 'Reports a problem' }
				: waiting('daemon', 'NetTap', failed.health);
		const search: PipelineStage =
			systemHealth && !failed.health
				? { key: 'opensearch', label: 'OpenSearch', status: systemHealth.opensearch_reachable ? 'ok' : 'failing', detail: systemHealth.opensearch_reachable ? 'Connected' : 'Not reachable' }
				: waiting('opensearch', 'OpenSearch', failed.health);
		const disk: PipelineStage =
			storageStatus && !failed.storage
				? {
						key: 'storage',
						label: 'Storage',
						status: storageStatus.disk_usage_percent > DISK_FULL_PERCENT ? 'failing' : 'ok',
						detail: `${storageStatus.disk_usage_percent.toFixed(1)}% used · ${formatBytes(storageStatus.disk_free_bytes)} free`,
					}
				: waiting('storage', 'Storage', failed.storage);
		const drive: PipelineStage =
			smartHealth && !failed.smart && smartHealth.healthy !== null
				? { key: 'drive', label: 'Drive', status: smartHealth.healthy ? 'ok' : 'failing', detail: smartHealth.healthy ? 'SMART checks pass' : 'SMART reports a problem' }
				: smartHealth && !failed.smart
					? { key: 'drive', label: 'Drive', status: 'unknown', detail: "Couldn't read the drive" }
					: waiting('drive', 'Drive', failed.smart);
		return [daemon, search, disk, drive];
	});

	const serviceRows = $derived([
		{ key: 'tshark', name: 'TShark', status: tsharkStatus, didFail: failed.tshark },
		{ key: 'cyberchef', name: 'CyberChef', status: cyberchefStatus, didFail: failed.cyberchef },
	]);
</script>

<svelte:head>
	<title>System | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">System</h1>
		<p class="page-sub">Hardware health, storage and service status</p>
	</div>
	<div class="head-actions">
		<a href="/system/updates" class="btn"><Icon name="download" />Software updates</a>
	</div>
</div>

<div class="grid">
	<Card title="System health" sub="Latest reading of each part · updated when the page loads or refreshes" class="c-12 health-card">
		<Pipeline {stages} />
	</Card>

	<Card title="System overview" sub="The NetTap daemon · uptime and last check" class="c-6">
		{#snippet actions()}
			{#if systemHealth && !failed.health}
				<span class={['chip', systemHealth.healthy ? 'is-ok' : 'is-bad']}>{systemHealth.healthy ? 'Healthy' : 'Degraded'}</span>
			{:else if !loading}
				<span class="chip">Unknown</span>
			{/if}
		{/snippet}
		{#if loading && !systemHealth}
			<CardState state="loading" title="Loading system health" />
		{:else if failed.health && !systemHealth}
			<CardState
				state="error"
				title="Couldn't load system health: the request failed."
				message="Check that the NetTap daemon is running, then try again."
				onaction={retry}
			/>
		{:else}
			{#if failed.health}
				<div class="notice is-warn" role="status"><Icon name="warn" />{loadFailed('system health', true)}</div>
			{/if}
			<dl class="facts flush">
				<dt>Uptime</dt>
				<dd class="mono">{systemHealth ? formatUptime(systemHealth.uptime) : '—'}</dd>
				<dt>Last check</dt>
				<dd class="mono">{systemHealth ? new Date(systemHealth.timestamp).toLocaleString() : '—'}</dd>
			</dl>
		{/if}
	</Card>

	<Card title="OpenSearch" sub="The search index NetTap stores its logs in · data indices only" class="c-6">
		{#snippet actions()}
			{#if systemHealth && !failed.health}
				<span class={['chip', systemHealth.opensearch_reachable ? 'is-ok' : 'is-bad']}>
					{systemHealth.opensearch_reachable ? 'Reachable' : 'Unreachable'}
				</span>
			{:else if !loading}
				<span class="chip">Unknown</span>
			{/if}
		{/snippet}
		{#if loading && !systemHealth && !storageStatus}
			<CardState state="loading" title="Loading OpenSearch status" />
		{:else if failed.health && failed.storage && !systemHealth && !storageStatus}
			<CardState
				state="error"
				title="Couldn't check OpenSearch: the system health and storage requests failed."
				message="Check that the NetTap daemon is running, then try again."
				onaction={retry}
			/>
		{:else}
			<dl class="facts flush">
				<dt>Status</dt>
				<dd>
					{#if !systemHealth}
						<span class="dim">—</span>
					{:else if systemHealth.opensearch_reachable}
						Connected
					{:else}
						Disconnected
					{/if}
				</dd>
				<!-- data indices only: the storage manager skips OpenSearch's own "." indices (#39) -->
				<dt>Data indices</dt>
				<!-- #96: the daemon sends indices_error (and null counts) when OpenSearch couldn't be asked -->
				{#if storageStatus?.indices_error}
					<dd class="dim" title={storageStatus.indices_error}>Couldn't read indices</dd>
				{:else}
					<dd class="num">{storageStatus?.total_indices ?? storageStatus?.index_summary?.count ?? '—'}</dd>
				{/if}
			</dl>
			{#if systemHealth && !systemHealth.opensearch_reachable}
				<div class="notice" role="status">
					<Icon name="warn" />
					<div>
						OpenSearch is not reachable. Possible causes:
						<ul class="causes">
							<li>The OpenSearch container is still starting, which can take up to 3 minutes.</li>
							<li>Its credentials aren't configured: check the curlrc mount.</li>
							<li>OpenSearch security needs its bootstrap: see CLAUDE.md.</li>
						</ul>
					</div>
				</div>
			{/if}
		{/if}
	</Card>

	<!-- OLD CODE START — rendered (and polled /api/bridge) in every capture mode (2026-10-30)
	<BridgeStatus />
	OLD CODE END -->
	{#if captureModeName === 'bridge'}
		<div class="c-12"><BridgeStatus /></div>
	{:else if captureModeFailed}
		<Card title="Bridge and failover" sub="Shown in bridge mode only" class="c-12">
			<CardState
				state="error"
				title="Couldn't read the capture mode, so bridge status isn't shown."
				message="Try again in a moment; the rest of this page doesn't depend on it."
				onaction={retry}
			/>
		</Card>
	{/if}

	<Card title="Storage" sub="The data disk · space and how long each kind of data is kept" class="c-12">
		{#snippet actions()}
			{#if failed.storage}
				<span class="chip">Unknown</span>
			{/if}
			{#if storageStatus}
				<span class="chip num">{storageStatus.disk_usage_percent.toFixed(1)}% used</span>
			{/if}
		{/snippet}
		{#if loading && !storageStatus}
			<CardState state="loading" title="Loading storage" />
		{:else if failed.storage && !storageStatus}
			<CardState
				state="error"
				title="Couldn't load storage status: the request failed."
				message="Check that the NetTap daemon is running, then try again."
				onaction={retry}
			/>
		{:else if storageStatus}
			{#if failed.storage}
				<div class="notice is-warn" role="status"><Icon name="warn" />{loadFailed('storage status', true)}</div>
			{/if}
			<Meter value={storageStatus.disk_usage_percent} label="Disk used" />
			<dl class="facts">
				<dt>Total</dt>
				<dd class="mono">{formatBytes(storageStatus.disk_total_bytes)}</dd>
				<dt>Used</dt>
				<dd class="mono">{formatBytes(storageStatus.disk_used_bytes)}</dd>
				<dt>Free</dt>
				<dd class="mono">{formatBytes(storageStatus.disk_free_bytes)}</dd>
			</dl>
			{#if storageStatus.retention}
				<h3 class="eyebrow section-label">Retention policy</h3>
				{#if typeof storageStatus.retention === 'object'}
					<dl class="facts flush">
						{#each Object.entries(storageStatus.retention) as [key, val] (key)}
							<dt>{key}</dt>
							<dd class="mono">{val}</dd>
						{/each}
					</dl>
				{:else}
					<p class="mono">{storageStatus.retention}</p>
				{/if}
			{/if}
		{:else}
			<CardState state="empty" title="Storage data unavailable" message="Disk figures appear here once the daemon reports them." />
		{/if}
	</Card>

	<Card title="Drive health" sub="SMART readings from the data drive" class="c-6">
		{#snippet actions()}
			{#if failed.smart || smartHealth?.healthy === null}
				<span class="chip">Unknown</span>
			{:else if smartHealth}
				<span class={['chip', smartHealth.healthy ? 'is-ok' : 'is-bad']}>{smartHealth.healthy ? 'Healthy' : 'Degraded'}</span>
			{:else if !loading}
				<span class="chip">Unknown</span>
			{/if}
		{/snippet}
		{#if loading && !smartHealth}
			<CardState state="loading" title="Loading drive health" />
		{:else if failed.smart && !smartHealth}
			<CardState
				state="error"
				title="Couldn't load drive health: the request failed."
				message="Check that the NetTap daemon is running, then try again."
				onaction={retry}
			/>
		{:else}
			{#if failed.smart}
				<div class="notice is-warn" role="status"><Icon name="warn" />{loadFailed('drive health', true)}</div>
			{:else if smartHealth?.healthy === null}
				<!-- #96: the daemon reports healthy: null (with error) when the drive can't be read -->
				<div class="notice is-warn" role="status"><Icon name="warn" />Drive health unknown: {smartHealth.error || 'the drive could not be read.'}</div>
			{/if}
			{#if smartHealth && smartHealth.device}
				<dl class="facts flush">
					<dt>Model</dt>
					<dd class="mono">{smartHealth.model || '—'}</dd>
					<dt>Temperature</dt>
					{#if smartHealth.temperature_c != null}
						<dd class="num">{smartHealth.temperature_c}&deg;C</dd>
					{:else}
						<dd class="dim" title="SMART temperature data could not be read. Check /dev mount and SYS_RAWIO capability.">Unavailable</dd>
					{/if}
					<dt>Wear</dt>
					{#if smartHealth.percentage_used != null}
						<dd class="wear">
							<Meter value={smartHealth.percentage_used} label="Drive wear" />
							<span class="num">{smartHealth.percentage_used}%</span>
						</dd>
					{:else}
						<dd class="dim" title="SMART wear level data could not be read. Check /dev mount and SYS_RAWIO capability.">Unavailable</dd>
					{/if}
					<dt>Power-on hours</dt>
					{#if smartHealth.power_on_hours != null}
						<dd class="num">{smartHealth.power_on_hours.toLocaleString()}</dd>
					{:else}
						<dd class="dim" title="SMART power-on hours data could not be read. Check /dev mount and SYS_RAWIO capability.">Unavailable</dd>
					{/if}
					<dt>Total written</dt>
					<dd class="mono">{smartHealth.total_bytes_written != null ? formatBytes(smartHealth.total_bytes_written) : '—'}</dd>
					<dt>Total read</dt>
					<dd class="mono">{smartHealth.total_bytes_read != null ? formatBytes(smartHealth.total_bytes_read) : '—'}</dd>
					{#if smartHealth.device_type === 'nvme'}
						<dt>Media errors</dt>
						<dd class="num">
							{#if smartHealth.media_errors == null}
								—
							{:else if smartHealth.media_errors > 0}
								<span class="chip is-warn">{smartHealth.media_errors.toLocaleString()} found</span>
							{:else}
								0
							{/if}
						</dd>
					{/if}
					{#if smartHealth.device_type === 'sata'}
						<dt>Reallocated sectors</dt>
						<dd class="num">
							{#if smartHealth.reallocated_sectors == null}
								—
							{:else if smartHealth.reallocated_sectors > 0}
								<span class="chip is-warn">{smartHealth.reallocated_sectors.toLocaleString()} found</span>
							{:else}
								0
							{/if}
						</dd>
					{/if}
					<dt>Serial</dt>
					<dd class="mono">{smartHealth.serial || '—'}</dd>
					<dt>Type</dt>
					<dd>
						{#if smartHealth.device_type === 'nvme'}
							<span class="tag">NVMe</span>
						{:else if smartHealth.device_type === 'sata'}
							<span class="tag">SATA</span>
						{:else}
							<span class="dim">—</span>
						{/if}
					</dd>
					{#if smartHealth.timestamp}
						<dt>Last updated</dt>
						<dd class="dim">{new Date(smartHealth.timestamp).toLocaleString()}</dd>
					{/if}
				</dl>
				{#if smartHealth.temperature_c == null && smartHealth.power_on_hours == null && smartHealth.percentage_used == null}
					<div class="notice" role="status">
						<Icon name="warn" />
						<div>
							SMART metrics are unavailable. The device was detected but no data could be read.
							Check that the /dev volume is mounted without :ro in Docker Compose, as NVMe drives require write access for admin commands.
							<a href="/api/smart/diagnostics" target="_blank" rel="noopener" class="link">View diagnostics</a>
						</div>
					</div>
				{/if}
				{#each smartHealth.warnings ?? [] as warning}
					<div class="notice is-warn" role="status"><Icon name="warn" />{warning}</div>
				{/each}
			{:else if !failed.smart && smartHealth?.healthy !== null}
				<CardState state="empty" title="SMART data unavailable" message="Drive health monitoring requires smartmontools." />
			{/if}
		{/if}
	</Card>

	<Card title="Services" sub="Optional analysis tools · installed version" class="c-6">
		{#snippet actions()}
			{#if cyberchefStatus?.available}
				<a href="/system/cyberchef" class="link">Open CyberChef</a>
			{/if}
		{/snippet}
		{#if loading && !tsharkStatus && !cyberchefStatus}
			<CardState state="loading" title="Loading services" />
		{:else}
			<dl class="facts flush">
				{#each serviceRows as row (row.key)}
					<dt>{row.name}</dt>
					<dd class="service">
						{#if row.didFail}
							<span class="dim">couldn't check</span>
							<span class="chip" title="The status request failed">Unknown</span>
						{:else if row.status}
							{#if row.status.version}
								<span class="mono">{row.status.version}</span>
							{:else if !row.status.available}
								<span class="mono dim">not deployed</span>
							{/if}
							<span class={['chip', row.status.available && 'is-ok']}>{row.status.available ? 'Available' : 'Not deployed'}</span>
						{:else}
							<span class="chip">Checking…</span>
						{/if}
					</dd>
				{/each}
			</dl>
		{/if}
	</Card>
</div>

<style>
	/* the four health stages fill the row on desktop; the system's tablet and phone rules still apply */
	@container app (min-width: 1101px) {
		:global(.health-card .pipe) { grid-template-columns: repeat(4, minmax(0, 1fr)); }
	}
	.facts.flush { border-top: 0; padding-top: 0; }
	:global(.meter) + .facts { margin-top: var(--sp-4); }
	/* block siblings: the margins collapse with the card head's and with each other */
	.notice { margin-block: var(--sp-4); }
	.notice:last-child { margin-bottom: 0; }
	.causes { margin: var(--sp-1) 0 0; padding-left: var(--sp-5); }
	.section-label { margin: var(--sp-5) 0 var(--sp-2); }
	.wear { display: flex; align-items: center; gap: var(--sp-2); justify-content: flex-end; }
	.wear :global(.meter) { flex: 1; max-width: 120px; }
	.service { display: flex; align-items: center; gap: var(--sp-2); justify-content: flex-end; }
</style>
