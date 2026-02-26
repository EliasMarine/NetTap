<script lang="ts">
	import { getBridgeHealth, getBypassStatus, enableBypass, disableBypass } from '$api/bridge.js';
	import type { BridgeHealth, BypassStatus } from '$api/bridge.js';

	let health = $state<BridgeHealth | null>(null);
	let bypassStatus = $state<BypassStatus | null>(null);
	let loading = $state(true);
	let bypassLoading = $state(false);
	let showBypassConfirm = $state(false);

	// ---------------------------------------------------------------------------
	// Formatting helpers (exported for testing via bridge-status-utils)
	// ---------------------------------------------------------------------------

	function healthBadgeClass(status: string): string {
		switch (status) {
			case 'normal':
				return 'badge badge-success';
			case 'degraded':
				return 'badge badge-warning';
			case 'bypass':
				return 'badge badge-info';
			case 'down':
				return 'badge badge-danger';
			default:
				return 'badge';
		}
	}

	function healthBadgeLabel(status: string): string {
		switch (status) {
			case 'normal':
				return 'Normal';
			case 'degraded':
				return 'Degraded';
			case 'bypass':
				return 'Bypass';
			case 'down':
				return 'Down';
			default:
				return 'Unknown';
		}
	}

	function linkColor(up: boolean | undefined): string {
		if (up === undefined) return 'var(--text-muted)';
		return up ? 'var(--success)' : 'var(--danger)';
	}

	function bridgeLineColor(status: string | undefined): string {
		switch (status) {
			case 'normal':
				return 'var(--success)';
			case 'degraded':
				return 'var(--warning)';
			case 'bypass':
				return 'var(--accent)';
			case 'down':
				return 'var(--danger)';
			default:
				return 'var(--text-muted)';
		}
	}

	function formatLatency(us: number): string {
		if (us <= 0) return '--';
		if (us < 1000) return `${us} us`;
		if (us < 1_000_000) return `${(us / 1000).toFixed(1)} ms`;
		return `${(us / 1_000_000).toFixed(2)} s`;
	}

	function formatByteRate(bytes: number): string {
		if (bytes <= 0) return '0 B/s';
		const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
		const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
		const val = bytes / Math.pow(1024, i);
		return `${val.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	}

	function formatUptime(seconds: number): string {
		if (seconds <= 0) return '--';
		const days = Math.floor(seconds / 86400);
		const hours = Math.floor((seconds % 86400) / 3600);
		const minutes = Math.floor((seconds % 3600) / 60);
		const parts: string[] = [];
		if (days > 0) parts.push(`${days}d`);
		if (hours > 0) parts.push(`${hours}h`);
		if (minutes > 0 || parts.length === 0) parts.push(`${minutes}m`);
		return parts.join(' ');
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchBridgeData() {
		loading = true;
		try {
			const [h, bp] = await Promise.all([getBridgeHealth(), getBypassStatus()]);
			health = h;
			bypassStatus = bp;
		} catch {
			// Keep existing state on error
		} finally {
			loading = false;
		}
	}

	async function handleBypassToggle() {
		if (!showBypassConfirm) {
			showBypassConfirm = true;
			return;
		}

		bypassLoading = true;
		showBypassConfirm = false;
		try {
			if (bypassStatus?.active) {
				await disableBypass();
			} else {
				await enableBypass();
			}
			// Refresh data after toggle
			await fetchBridgeData();
		} catch {
			// Keep existing state on error
		} finally {
			bypassLoading = false;
		}
	}

	function cancelBypassToggle() {
		showBypassConfirm = false;
	}

	// Auto-refresh every 15 seconds
	$effect(() => {
		fetchBridgeData();
		const interval = setInterval(fetchBridgeData, 15_000);
		return () => clearInterval(interval);
	});
</script>

<div class="bridge-card card">
	<div class="card-header">
		<span class="card-title">Bridge & Failover</span>
		{#if health}
			<span class={healthBadgeClass(health.health_status)}>
				{healthBadgeLabel(health.health_status)}
			</span>
		{:else if loading}
			<span class="badge">Loading...</span>
		{:else}
			<span class="badge">Unknown</span>
		{/if}
	</div>

	{#if loading && !health}
		<div class="bridge-loading">
			<div class="spinner"></div>
			<p class="text-muted">Checking bridge status...</p>
		</div>
	{:else if health}
		<!-- Network diagram -->
		<div class="bridge-diagram">
			<div class="nic-box" style="border-color: {linkColor(health.wan_link)}">
				<div class="nic-icon">
					<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
						<line x1="1" y1="10" x2="23" y2="10" />
					</svg>
				</div>
				<span class="nic-label">WAN</span>
				<span class="nic-status" style="color: {linkColor(health.wan_link)}">
					{health.wan_link ? 'Link Up' : 'Link Down'}
				</span>
			</div>

			<div class="bridge-line-container">
				<div class="bridge-line" style="background-color: {bridgeLineColor(health.health_status)}"></div>
				<span class="bridge-label" style="color: {bridgeLineColor(health.health_status)}">
					{#if health.bypass_active}
						Bypass
					{:else if health.bridge_state === 'up'}
						Normal
					{:else if health.bridge_state === 'down'}
						Down
					{:else}
						Unknown
					{/if}
				</span>
				<div class="bridge-icon">
					<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke={bridgeLineColor(health.health_status)} stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
						<line x1="4" y1="22" x2="4" y2="15" />
					</svg>
				</div>
			</div>

			<div class="nic-box" style="border-color: {linkColor(health.lan_link)}">
				<div class="nic-icon">
					<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
						<line x1="1" y1="10" x2="23" y2="10" />
					</svg>
				</div>
				<span class="nic-label">LAN</span>
				<span class="nic-status" style="color: {linkColor(health.lan_link)}">
					{health.lan_link ? 'Link Up' : 'Link Down'}
				</span>
			</div>
		</div>

		<!-- Stats row -->
		<div class="bridge-stats">
			<div class="stat-item">
				<span class="stat-label">Latency</span>
				<span class="stat-value mono">{formatLatency(health.latency_us)}</span>
			</div>
			<div class="stat-item">
				<span class="stat-label">RX Rate</span>
				<span class="stat-value mono">{formatByteRate(health.rx_bytes_delta)}</span>
			</div>
			<div class="stat-item">
				<span class="stat-label">TX Rate</span>
				<span class="stat-value mono">{formatByteRate(health.tx_bytes_delta)}</span>
			</div>
			<div class="stat-item">
				<span class="stat-label">Uptime</span>
				<span class="stat-value mono">{formatUptime(health.uptime_seconds)}</span>
			</div>
		</div>

		<!-- Bypass control section -->
		<div class="bypass-section">
			<div class="bypass-header">
				<span class="bypass-title">Bypass Mode</span>
				{#if bypassStatus?.active}
					<span class="badge badge-warning">Active</span>
				{:else}
					<span class="badge badge-success">Inactive</span>
				{/if}
			</div>

			{#if bypassStatus?.active}
				<p class="bypass-warning">
					Capture services are stopped. Traffic flows through without monitoring.
				</p>
				{#if bypassStatus.activated_at}
					<p class="bypass-since text-muted">
						Since: {new Date(bypassStatus.activated_at).toLocaleString()}
					</p>
				{/if}
			{/if}

			<div class="bypass-actions">
				{#if showBypassConfirm}
					<span class="confirm-text">
						{bypassStatus?.active ? 'Disable bypass and resume capture?' : 'Enable bypass? Capture will stop.'}
					</span>
					<button
						class="btn btn-sm btn-danger"
						onclick={handleBypassToggle}
						disabled={bypassLoading}
					>
						Confirm
					</button>
					<button
						class="btn btn-sm btn-secondary"
						onclick={cancelBypassToggle}
						disabled={bypassLoading}
					>
						Cancel
					</button>
				{:else}
					<button
						class="btn btn-sm {bypassStatus?.active ? 'btn-primary' : 'btn-warning'}"
						onclick={handleBypassToggle}
						disabled={bypassLoading}
					>
						{#if bypassLoading}
							Updating...
						{:else if bypassStatus?.active}
							Disable Bypass
						{:else}
							Enable Bypass
						{/if}
					</button>
				{/if}
			</div>
		</div>

		<!-- Issues list -->
		{#if health.issues && health.issues.length > 0}
			<div class="bridge-issues">
				{#each health.issues as issue}
					<div class="alert alert-warning">{issue}</div>
				{/each}
			</div>
		{/if}

		<!-- Watchdog indicator -->
		<div class="bridge-footer">
			<span class="footer-item text-muted">
				Watchdog: <span class={health.watchdog_active ? 'text-success' : 'text-danger'}>
					{health.watchdog_active ? 'Active' : 'Inactive'}
				</span>
			</span>
			{#if health.last_check}
				<span class="footer-item text-muted">
					Last check: {new Date(health.last_check).toLocaleTimeString()}
				</span>
			{/if}
		</div>
	{:else}
		<p class="text-muted">Bridge health data unavailable</p>
	{/if}
</div>

<style>
	/* Bridge card specific styles */
	.bridge-loading {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-xl);
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

	/* Network diagram */
	.bridge-diagram {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0;
		padding: var(--space-lg) var(--space-sm);
	}

	.nic-box {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-xs);
		padding: var(--space-md);
		background-color: var(--bg-tertiary);
		border: 2px solid var(--border-default);
		border-radius: var(--radius-lg);
		min-width: 80px;
		transition: border-color var(--transition-normal);
	}

	.nic-icon {
		color: var(--text-secondary);
	}

	.nic-label {
		font-size: var(--text-sm);
		font-weight: 700;
		color: var(--text-primary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.nic-status {
		font-size: var(--text-xs);
		font-weight: 500;
	}

	.bridge-line-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-xs);
		padding: 0 var(--space-sm);
		min-width: 100px;
	}

	.bridge-line {
		width: 100%;
		height: 3px;
		border-radius: var(--radius-full);
		transition: background-color var(--transition-normal);
	}

	.bridge-label {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.bridge-icon {
		margin-top: var(--space-xs);
	}

	/* Stats row */
	.bridge-stats {
		display: flex;
		gap: var(--space-lg);
		flex-wrap: wrap;
		padding: var(--space-md) 0;
		border-top: 1px solid var(--border-muted);
		border-bottom: 1px solid var(--border-muted);
	}

	.stat-item {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		flex: 1;
		min-width: 80px;
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.stat-value {
		font-size: var(--text-sm);
		color: var(--text-primary);
		font-weight: 600;
	}

	/* Bypass section */
	.bypass-section {
		padding: var(--space-md) 0;
	}

	.bypass-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-sm);
	}

	.bypass-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.bypass-warning {
		font-size: var(--text-sm);
		color: var(--warning);
		margin-bottom: var(--space-sm);
		padding: var(--space-sm);
		background-color: color-mix(in srgb, var(--warning) 10%, transparent);
		border-radius: var(--radius-md);
		border: 1px solid color-mix(in srgb, var(--warning) 25%, transparent);
	}

	.bypass-since {
		font-size: var(--text-xs);
		margin-bottom: var(--space-sm);
	}

	.bypass-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.confirm-text {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	/* Issues list */
	.bridge-issues {
		padding-top: var(--space-md);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	/* Footer */
	.bridge-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-muted);
		font-size: var(--text-xs);
	}

	.footer-item {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	/* Responsive */
	@media (max-width: 640px) {
		.bridge-diagram {
			flex-direction: column;
			gap: var(--space-sm);
		}

		.bridge-line-container {
			transform: rotate(90deg);
			padding: var(--space-sm) 0;
		}

		.bridge-stats {
			flex-direction: column;
			gap: var(--space-sm);
		}

		.bypass-actions {
			flex-wrap: wrap;
		}

		.bridge-footer {
			flex-direction: column;
			gap: var(--space-sm);
			align-items: flex-start;
		}
	}
</style>
