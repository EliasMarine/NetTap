<script lang="ts">
	import { getBridgeHealth, getBypassStatus, enableBypass, disableBypass } from '$api/bridge.js';
	import type { BridgeHealth, BypassStatus } from '$api/bridge.js';

	let health = $state<BridgeHealth | null>(null);
	let bypassStatus = $state<BypassStatus | null>(null);
	let loading = $state(true);
	let bypassLoading = $state(false);
	let showBypassConfirm = $state(false);
	// #96: a failed request must read "unknown", never "Down" or "Inactive"
	let healthFailed = $state(false);
	let bypassFailed = $state(false);
	let bypassError = $state('');

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
			case 'not_configured':
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
			case 'not_configured':
				return 'Not Configured';
			case 'down':
				return 'Down';
			default:
				return 'Unknown';
		}
	}

	function linkColor(up: boolean | undefined): string {
		if (up === undefined) return 'var(--text-3)';
		return up ? 'var(--ok)' : 'var(--sev-critical)';
	}

	function bridgeLineColor(status: string | undefined): string {
		switch (status) {
			case 'normal':
				return 'var(--ok)';
			case 'degraded':
				return 'var(--sev-medium)';
			case 'bypass':
				return 'var(--accent)';
			case 'not_configured':
				return 'var(--text-3)';
			case 'down':
				return 'var(--sev-critical)';
			default:
				return 'var(--text-3)';
		}
	}

	// OLD CODE START — no null: the daemon sends null when latency isn't measured
	// function formatLatency(us: number): string {
	// OLD CODE END
	function formatLatency(us: number | null): string {
		if (us == null) return 'Not measured';
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
		// OLD CODE START — #96: the getters faked "down"/"inactive" on failure; they now throw
		// try {
		// 	const [h, bp] = await Promise.all([getBridgeHealth(), getBypassStatus()]);
		// 	health = h;
		// 	bypassStatus = bp;
		// } catch {
		// 	// Keep existing state on error
		// } finally {
		// 	loading = false;
		// }
		// OLD CODE END
		// keep the last good reading on a failed refresh, but say it failed
		const [h, bp] = await Promise.allSettled([getBridgeHealth(), getBypassStatus()]);
		if (h.status === 'fulfilled') health = h.value;
		if (bp.status === 'fulfilled') bypassStatus = bp.value;
		healthFailed = h.status === 'rejected';
		bypassFailed = bp.status === 'rejected';
		loading = false;
	}

	async function handleBypassToggle() {
		if (!showBypassConfirm) {
			showBypassConfirm = true;
			return;
		}

		bypassLoading = true;
		showBypassConfirm = false;
		bypassError = '';
		try {
			// OLD CODE START — #96: a failed toggle ({ result: 'error' }) was ignored
			// if (bypassStatus?.active) {
			// 	await disableBypass();
			// } else {
			// 	await enableBypass();
			// }
			// OLD CODE END
			const wasActive = bypassStatus?.active;
			const res = wasActive ? await disableBypass() : await enableBypass();
			if (res.result === 'error') {
				bypassError = `Couldn't ${wasActive ? 'disable' : 'enable'} bypass: the request failed.`;
			}
			// Refresh data after toggle
			await fetchBridgeData();
		} catch {
			// OLD CODE START — #96: a network error was swallowed
			// // Keep existing state on error
			// OLD CODE END
			bypassError = "Couldn't change bypass mode: the request failed.";
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
		{#if healthFailed}
			<span class="badge badge-muted">Unknown</span>
		{:else if health}
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
	{:else if healthFailed && !health}
		<p class="empty-state">Couldn't check bridge health: the request failed.</p>
	{:else if health && health.health_status === 'not_configured'}
		<!-- Not configured info state -->
		<div class="not-configured-state">
			<div class="info-icon">
				<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
				</svg>
			</div>
			<p class="not-configured-title">Bridge Not Configured</p>
			<p class="not-configured-desc text-muted">
				The network bridge (br0) has not been set up yet. Run the setup wizard to configure your WAN and LAN interfaces.
			</p>
			<a href="/setup" class="btn btn-sm btn-primary">Open Setup Wizard</a>
		</div>
		{#if health.issues && health.issues.length > 0}
			<div class="bridge-issues">
				{#each health.issues as issue}
					<div class="alert alert-info">{issue}</div>
				{/each}
			</div>
		{/if}
	{:else if health}
		{#if healthFailed}
			<div class="alert alert-warning">Couldn't refresh bridge health: showing the last reading.</div>
		{/if}
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
				<span class="stat-value mono" title={health.latency_note || undefined}>{formatLatency(health.latency_us)}</span>
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
				{#if bypassFailed}
					<span class="badge badge-muted">Unknown</span>
				{:else if bypassStatus?.active}
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

			{#if bypassError}
				<div class="alert alert-danger">{bypassError}</div>
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
					<!-- #96: no toggle while the current bypass state is unknown -->
					<button
						class="btn btn-sm {bypassStatus?.active ? 'btn-primary' : 'btn-warning'}"
						onclick={handleBypassToggle}
						disabled={bypassLoading || !bypassStatus}
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
	/* Not configured state */
	.not-configured-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--sp-8);
		gap: var(--sp-4);
		text-align: center;
	}

	.info-icon {
		opacity: 0.7;
	}

	.not-configured-title {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-1);
	}

	.not-configured-desc {
		font-size: var(--text-sm);
		max-width: 360px;
		line-height: 1.5;
	}

	/* Bridge card specific styles */
	.bridge-loading {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--sp-8);
		gap: var(--sp-4);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--line);
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
		padding: var(--sp-6) var(--sp-2);
	}

	.nic-box {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-1);
		padding: var(--sp-4);
		background-color: var(--surface-2);
		border: 2px solid var(--line);
		border-radius: var(--r-lg);
		min-width: 80px;
		transition: border-color 250ms var(--ease);
	}

	.nic-icon {
		color: var(--text-2);
	}

	.nic-label {
		font-size: var(--text-sm);
		font-weight: 700;
		color: var(--text-1);
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
		gap: var(--sp-1);
		padding: 0 var(--sp-2);
		min-width: 100px;
	}

	.bridge-line {
		width: 100%;
		height: 3px;
		border-radius: var(--r-pill);
		transition: background-color 250ms var(--ease);
	}

	.bridge-label {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.bridge-icon {
		margin-top: var(--sp-1);
	}

	/* Stats row */
	.bridge-stats {
		display: flex;
		gap: var(--sp-6);
		flex-wrap: wrap;
		padding: var(--sp-4) 0;
		border-top: 1px solid var(--line);
		border-bottom: 1px solid var(--line);
	}

	.stat-item {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		flex: 1;
		min-width: 80px;
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-2);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.stat-value {
		font-size: var(--text-sm);
		color: var(--text-1);
		font-weight: 600;
	}

	/* Bypass section */
	.bypass-section {
		padding: var(--sp-4) 0;
	}

	.bypass-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--sp-2);
	}

	.bypass-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-1);
	}

	.bypass-warning {
		font-size: var(--text-sm);
		color: var(--sev-medium);
		margin-bottom: var(--sp-2);
		padding: var(--sp-2);
		background-color: color-mix(in srgb, var(--sev-medium) 10%, transparent);
		border-radius: var(--r-md);
		border: 1px solid color-mix(in srgb, var(--sev-medium) 25%, transparent);
	}

	.bypass-since {
		font-size: var(--text-xs);
		margin-bottom: var(--sp-2);
	}

	.bypass-actions {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}

	.confirm-text {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	/* Issues list */
	.bridge-issues {
		padding-top: var(--sp-4);
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	/* Footer */
	.bridge-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
		font-size: var(--text-xs);
	}

	.footer-item {
		display: flex;
		align-items: center;
		gap: var(--sp-1);
	}

	/* Responsive */
	@media (max-width: 640px) {
		.bridge-diagram {
			flex-direction: column;
			gap: var(--sp-2);
		}

		.bridge-line-container {
			transform: rotate(90deg);
			padding: var(--sp-2) 0;
		}

		.bridge-stats {
			flex-direction: column;
			gap: var(--sp-2);
		}

		.bypass-actions {
			flex-wrap: wrap;
		}

		.bridge-footer {
			flex-direction: column;
			gap: var(--sp-2);
			align-items: flex-start;
		}
	}
</style>
