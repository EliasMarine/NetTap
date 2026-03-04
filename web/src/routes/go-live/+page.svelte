<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		getBridgeReadiness,
		getBridgeHealth,
		createBridge,
		enableBypass,
		disableBypass,
		type BridgeReadiness,
		type BridgeHealth,
	} from '$lib/api/bridge.js';

	// ----- Phase state -----
	// Phase 1 = readiness checks, Phase 2 = wiring guide, Phase 3 = live monitoring
	let phase = $state<1 | 2 | 3>(1);

	// ----- NIC names from localStorage -----
	let wanIface = $state('');
	let lanIface = $state('');

	// ----- Readiness state -----
	let readiness = $state<BridgeReadiness | null>(null);
	let readinessLoading = $state(true);
	let readinessError = $state('');

	// ----- Bridge creation state -----
	let creating = $state(false);
	let createError = $state('');

	// ----- Health state (Phase 3) -----
	let health = $state<BridgeHealth | null>(null);
	let healthError = $state('');

	// ----- Bypass state -----
	let bypassToggling = $state(false);
	let bypassConfirmOpen = $state(false);

	// ----- Interval IDs for cleanup -----
	let readinessInterval: ReturnType<typeof setInterval> | undefined;
	let healthInterval: ReturnType<typeof setInterval> | undefined;

	// ----- Load NIC names from localStorage on mount -----
	$effect(() => {
		if (typeof window !== 'undefined') {
			wanIface = localStorage.getItem('nettap_wan_iface') || 'eth0';
			lanIface = localStorage.getItem('nettap_lan_iface') || 'eth1';
		}
	});

	// ----- Determine phase from readiness data -----
	let bridgeExists = $derived(
		readiness?.checks?.some((c) => c.name === 'bridge_exists' && c.passed) ?? false
	);
	let wanCarrier = $derived(
		readiness?.checks?.some((c) => c.name === 'wan_carrier' && c.passed) ?? false
	);
	let lanCarrier = $derived(
		readiness?.checks?.some((c) => c.name === 'lan_carrier' && c.passed) ?? false
	);

	function determinePhase(r: BridgeReadiness): 1 | 2 | 3 {
		const bridge = r.checks?.some((c) => c.name === 'bridge_exists' && c.passed);
		const wan = r.checks?.some((c) => c.name === 'wan_carrier' && c.passed);
		const lan = r.checks?.some((c) => c.name === 'lan_carrier' && c.passed);

		if (!bridge) return 1;
		if (!wan || !lan) return 2;
		return 3;
	}

	// ----- Readiness polling (Phases 1 & 2) -----
	async function fetchReadiness() {
		try {
			readiness = await getBridgeReadiness();
			readinessError = '';
			const newPhase = determinePhase(readiness);
			if (newPhase !== phase) {
				phase = newPhase;
			}
		} catch {
			readinessError = 'Failed to check readiness';
		}
		readinessLoading = false;
	}

	$effect(() => {
		// Initial fetch
		fetchReadiness();

		// Poll every 3s during phases 1 and 2
		readinessInterval = setInterval(fetchReadiness, 3000);

		return () => {
			if (readinessInterval) clearInterval(readinessInterval);
		};
	});

	// ----- Health polling (Phase 3 only) -----
	async function fetchHealth() {
		try {
			health = await getBridgeHealth();
			healthError = '';
		} catch {
			healthError = 'Failed to fetch bridge health';
		}
	}

	$effect(() => {
		if (phase === 3) {
			fetchHealth();
			healthInterval = setInterval(fetchHealth, 5000);
		} else {
			if (healthInterval) clearInterval(healthInterval);
		}

		return () => {
			if (healthInterval) clearInterval(healthInterval);
		};
	});

	// ----- Actions -----
	async function handleCreateBridge() {
		creating = true;
		createError = '';
		try {
			const result = await createBridge(wanIface, lanIface);
			if (!result.created && result.errors.length > 0) {
				createError = result.errors.join(', ');
			} else {
				// Refresh readiness immediately
				await fetchReadiness();
			}
		} catch {
			createError = 'Failed to create bridge';
		}
		creating = false;
	}

	async function handleBypassToggle() {
		bypassToggling = true;
		try {
			if (health?.bypass_active) {
				await disableBypass();
			} else {
				await enableBypass();
			}
			// Refresh health
			await fetchHealth();
		} catch {
			// Error will show from health refresh
		}
		bypassToggling = false;
		bypassConfirmOpen = false;
	}

	// ----- Formatting helpers -----
	function formatUptime(seconds: number): string {
		if (seconds < 60) return `${seconds}s`;
		if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
		const h = Math.floor(seconds / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		return `${h}h ${m}m`;
	}

	function formatPackets(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return String(n);
	}

	function statusBadgeClass(status: string): string {
		switch (status) {
			case 'normal':
				return 'badge-success';
			case 'degraded':
				return 'badge-warning';
			case 'bypass':
				return 'badge-warning';
			case 'down':
			case 'not_configured':
				return 'badge-danger';
			default:
				return 'badge-muted';
		}
	}
</script>

<svelte:head>
	<title>Go Live | NetTap</title>
</svelte:head>

<div class="go-live-page">
	<div class="page-header">
		<h1>Go Live</h1>
		<p class="text-muted">Connect your NetTap appliance to the network</p>
	</div>

	<!-- Phase indicator -->
	<div class="phase-indicator">
		<div class="phase-step" class:active={phase >= 1} class:completed={phase > 1}>
			<span class="phase-num">1</span>
			<span class="phase-label">Readiness</span>
		</div>
		<div class="phase-connector" class:active={phase > 1}></div>
		<div class="phase-step" class:active={phase >= 2} class:completed={phase > 2}>
			<span class="phase-num">2</span>
			<span class="phase-label">Wiring</span>
		</div>
		<div class="phase-connector" class:active={phase > 2}></div>
		<div class="phase-step" class:active={phase >= 3}>
			<span class="phase-num">3</span>
			<span class="phase-label">Monitoring</span>
		</div>
	</div>

	<!-- ==================== PHASE 1: Readiness Check ==================== -->
	{#if phase === 1}
		<div class="card phase-card">
			<div class="card-header">
				<h2 class="card-title">Readiness Check</h2>
				{#if readinessLoading}
					<span class="badge badge-muted">Checking...</span>
				{:else if readiness?.ready}
					<span class="badge badge-success">Ready</span>
				{:else}
					<span class="badge badge-warning">Not Ready</span>
				{/if}
			</div>

			{#if readinessError}
				<div class="alert alert-danger">{readinessError}</div>
			{/if}

			{#if readiness?.checks && readiness.checks.length > 0}
				<ul class="checklist">
					{#each readiness.checks as check}
						<li class="checklist-item" class:passed={check.passed} class:failed={!check.passed}>
							<span class="check-icon">{check.passed ? '\u2713' : '\u2717'}</span>
							<div class="check-content">
								<span class="check-name">{check.name.replace(/_/g, ' ')}</span>
								<span class="check-detail text-muted">{check.detail}</span>
							</div>
						</li>
					{/each}
				</ul>
			{:else if !readinessLoading}
				<p class="text-muted">No readiness checks returned. Is the daemon running?</p>
			{/if}

			{#if !bridgeExists}
				<div class="action-section">
					<p class="text-muted">The bridge has not been created yet. Create it to proceed.</p>
					{#if createError}
						<div class="alert alert-danger" style="margin-bottom: var(--space-md);">{createError}</div>
					{/if}
					<button
						class="btn btn-primary btn-lg"
						onclick={handleCreateBridge}
						disabled={creating}
					>
						{#if creating}
							Creating Bridge...
						{:else}
							Create Bridge
						{/if}
					</button>
				</div>
			{/if}

			{#if readiness?.message}
				<p class="readiness-message text-muted">{readiness.message}</p>
			{/if}
		</div>

	<!-- ==================== PHASE 2: Wiring Guide ==================== -->
	{:else if phase === 2}
		<div class="card phase-card">
			<div class="card-header">
				<h2 class="card-title">Cable Your Network</h2>
				<span class="badge badge-accent">Waiting for links</span>
			</div>

			<p class="text-muted" style="margin-bottom: var(--space-lg);">
				Follow the steps below to physically connect NetTap inline between your modem and router.
			</p>

			<!-- Network diagram -->
			<div class="network-diagram">
				<div class="diagram-device">
					<div class="device-icon">&#127760;</div>
					<div class="device-label">ISP Modem</div>
				</div>
				<div class="diagram-cable">
					<div class="cable-line"></div>
				</div>
				<div class="diagram-device nic-device">
					<div class="carrier-dot" class:carrier-up={wanCarrier} class:carrier-down={!wanCarrier}></div>
					<div class="device-label mono">{wanIface}</div>
					<div class="device-sublabel">WAN</div>
				</div>
				<div class="diagram-bridge">
					<div class="bridge-label">NetTap br0</div>
				</div>
				<div class="diagram-device nic-device">
					<div class="carrier-dot" class:carrier-up={lanCarrier} class:carrier-down={!lanCarrier}></div>
					<div class="device-label mono">{lanIface}</div>
					<div class="device-sublabel">LAN</div>
				</div>
				<div class="diagram-cable">
					<div class="cable-line"></div>
				</div>
				<div class="diagram-device">
					<div class="device-icon">&#128225;</div>
					<div class="device-label">Router</div>
				</div>
			</div>

			<!-- Instructions -->
			<div class="wiring-steps">
				<h3>Steps</h3>
				<ol>
					<li>
						<strong>Disconnect</strong> the Ethernet cable running from your ISP modem to your router.
					</li>
					<li>
						<strong>Connect</strong> the modem's Ethernet cable to the <span class="mono badge badge-accent">{wanIface}</span> port on NetTap (WAN).
					</li>
					<li>
						<strong>Connect</strong> a new Ethernet cable from the <span class="mono badge badge-accent">{lanIface}</span> port on NetTap (LAN) to your router's WAN port.
					</li>
					<li>
						<strong>Wait</strong> for both carrier indicators above to turn green. This page will advance automatically.
					</li>
				</ol>
			</div>

			<!-- Carrier status -->
			<div class="carrier-status">
				<div class="carrier-item">
					<span class="carrier-dot-inline" class:carrier-up={wanCarrier} class:carrier-down={!wanCarrier}></span>
					<span>WAN ({wanIface}): <strong>{wanCarrier ? 'Connected' : 'No carrier'}</strong></span>
				</div>
				<div class="carrier-item">
					<span class="carrier-dot-inline" class:carrier-up={lanCarrier} class:carrier-down={!lanCarrier}></span>
					<span>LAN ({lanIface}): <strong>{lanCarrier ? 'Connected' : 'No carrier'}</strong></span>
				</div>
			</div>
		</div>

	<!-- ==================== PHASE 3: Live Monitoring ==================== -->
	{:else if phase === 3}
		<!-- Bypass warning banner -->
		{#if health?.bypass_active}
			<div class="alert alert-warning" style="margin-bottom: var(--space-md);">
				<strong>Bypass mode is active.</strong> Traffic is passing through without inspection. Disable bypass to resume monitoring.
			</div>
		{/if}

		<!-- Success banner -->
		<div class="alert alert-success" style="margin-bottom: var(--space-lg);">
			<strong>Your network is being monitored by NetTap.</strong>
			All traffic between your modem and router is being analyzed for threats and anomalies.
		</div>

		<!-- Health card -->
		<div class="card phase-card">
			<div class="card-header">
				<h2 class="card-title">Bridge Health</h2>
				{#if health}
					<span class="badge {statusBadgeClass(health.health_status)}">
						{health.health_status.toUpperCase()}
					</span>
				{:else if healthError}
					<span class="badge badge-danger">Error</span>
				{:else}
					<span class="badge badge-muted">Loading...</span>
				{/if}
			</div>

			{#if healthError}
				<div class="alert alert-danger">{healthError}</div>
			{/if}

			{#if health}
				<div class="grid grid-cols-4 health-grid">
					<div class="health-stat">
						<span class="health-label">WAN Link</span>
						<span class="health-value" class:text-success={health.wan_link} class:text-danger={!health.wan_link}>
							{health.wan_link ? 'UP' : 'DOWN'}
						</span>
					</div>
					<div class="health-stat">
						<span class="health-label">LAN Link</span>
						<span class="health-value" class:text-success={health.lan_link} class:text-danger={!health.lan_link}>
							{health.lan_link ? 'UP' : 'DOWN'}
						</span>
					</div>
					<div class="health-stat">
						<span class="health-label">RX Packets</span>
						<span class="health-value">{formatPackets(health.rx_packets_delta)}</span>
					</div>
					<div class="health-stat">
						<span class="health-label">TX Packets</span>
						<span class="health-value">{formatPackets(health.tx_packets_delta)}</span>
					</div>
					<div class="health-stat">
						<span class="health-label">Latency</span>
						<span class="health-value">{health.latency_us} us</span>
					</div>
					<div class="health-stat">
						<span class="health-label">Uptime</span>
						<span class="health-value">{formatUptime(health.uptime_seconds)}</span>
					</div>
					<div class="health-stat">
						<span class="health-label">Bridge State</span>
						<span class="health-value">{health.bridge_state}</span>
					</div>
					<div class="health-stat">
						<span class="health-label">Bypass</span>
						<span class="health-value" class:text-warning={health.bypass_active}>
							{health.bypass_active ? 'ACTIVE' : 'Off'}
						</span>
					</div>
				</div>

				{#if health.issues.length > 0}
					<div class="issues-section">
						<h3>Issues</h3>
						<ul>
							{#each health.issues as issue}
								<li class="text-warning">{issue}</li>
							{/each}
						</ul>
					</div>
				{/if}
			{/if}
		</div>

		<!-- Action buttons -->
		<div class="action-buttons">
			<button class="btn btn-primary btn-lg" onclick={() => goto('/')}>
				Go to Dashboard
			</button>

			{#if health?.bypass_active}
				<button
					class="btn btn-lg"
					onclick={handleBypassToggle}
					disabled={bypassToggling}
				>
					{bypassToggling ? 'Disabling...' : 'Disable Bypass'}
				</button>
			{:else}
				<button
					class="btn btn-danger btn-lg"
					onclick={() => { bypassConfirmOpen = true; }}
					disabled={bypassToggling}
				>
					Enable Bypass
				</button>
			{/if}
		</div>

		<!-- Bypass confirmation dialog -->
		{#if bypassConfirmOpen}
			<div class="modal-overlay" onclick={() => { bypassConfirmOpen = false; }} role="presentation">
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="modal-card card" onclick={(e) => e.stopPropagation()}>
					<h3 class="card-title">Enable Bypass Mode?</h3>
					<p class="text-muted" style="margin: var(--space-md) 0;">
						Bypass mode stops all traffic inspection. Packets will pass through the bridge without being analyzed.
						Use this only for troubleshooting.
					</p>
					<div class="modal-actions">
						<button class="btn" onclick={() => { bypassConfirmOpen = false; }}>Cancel</button>
						<button
							class="btn btn-danger"
							onclick={handleBypassToggle}
							disabled={bypassToggling}
						>
							{bypassToggling ? 'Enabling...' : 'Confirm Bypass'}
						</button>
					</div>
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	.go-live-page {
		max-width: 800px;
		margin: 0 auto;
		padding: var(--space-xl) var(--space-md);
	}

	.page-header {
		margin-bottom: var(--space-xl);
	}

	.page-header h1 {
		font-size: var(--text-3xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	/* ----- Phase indicator ----- */
	.phase-indicator {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0;
		margin-bottom: var(--space-xl);
	}

	.phase-step {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
		border-radius: var(--radius-full);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		transition: all var(--transition-normal);
	}

	.phase-step.active {
		border-color: var(--accent);
		background-color: var(--accent-muted);
	}

	.phase-step.completed {
		border-color: var(--success);
		background-color: var(--success-muted);
	}

	.phase-num {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border-radius: var(--radius-full);
		background-color: var(--bg-tertiary);
		font-size: var(--text-xs);
		font-weight: 700;
	}

	.phase-step.active .phase-num {
		background-color: var(--accent);
		color: #fff;
	}

	.phase-step.completed .phase-num {
		background-color: var(--success);
		color: #fff;
	}

	.phase-label {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-secondary);
	}

	.phase-step.active .phase-label {
		color: var(--accent);
	}

	.phase-step.completed .phase-label {
		color: var(--success);
	}

	.phase-connector {
		width: 40px;
		height: 2px;
		background-color: var(--border-default);
		transition: background-color var(--transition-normal);
	}

	.phase-connector.active {
		background-color: var(--success);
	}

	/* ----- Phase card ----- */
	.phase-card {
		margin-bottom: var(--space-lg);
	}

	/* ----- Checklist (Phase 1) ----- */
	.checklist {
		list-style: none;
		padding: 0;
		margin: var(--space-md) 0;
	}

	.checklist-item {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.checklist-item:last-child {
		border-bottom: none;
	}

	.check-icon {
		font-size: var(--text-lg);
		line-height: 1;
		flex-shrink: 0;
		width: 24px;
		text-align: center;
	}

	.checklist-item.passed .check-icon {
		color: var(--success);
	}

	.checklist-item.failed .check-icon {
		color: var(--danger);
	}

	.check-content {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.check-name {
		font-weight: 600;
		text-transform: capitalize;
	}

	.check-detail {
		font-size: var(--text-sm);
	}

	.action-section {
		margin-top: var(--space-lg);
		padding-top: var(--space-lg);
		border-top: 1px solid var(--border-default);
	}

	.readiness-message {
		margin-top: var(--space-md);
		font-size: var(--text-sm);
		font-style: italic;
	}

	/* ----- Network diagram (Phase 2) ----- */
	.network-diagram {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-xs);
		padding: var(--space-xl) var(--space-md);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		margin-bottom: var(--space-lg);
		overflow-x: auto;
	}

	.diagram-device {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-xs);
		min-width: 70px;
	}

	.device-icon {
		font-size: var(--text-2xl);
	}

	.device-label {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.device-sublabel {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
	}

	.nic-device {
		position: relative;
		padding: var(--space-sm);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background-color: var(--bg-secondary);
	}

	.diagram-cable {
		flex: 0 0 30px;
		display: flex;
		align-items: center;
	}

	.cable-line {
		width: 100%;
		height: 2px;
		background-color: var(--border-default);
	}

	.diagram-bridge {
		padding: var(--space-sm) var(--space-md);
		border: 2px solid var(--accent);
		border-radius: var(--radius-md);
		background-color: var(--accent-muted);
	}

	.bridge-label {
		font-size: var(--text-sm);
		font-weight: 700;
		color: var(--accent);
		font-family: var(--font-mono);
	}

	.carrier-dot {
		width: 10px;
		height: 10px;
		border-radius: var(--radius-full);
		position: absolute;
		top: -5px;
		right: -5px;
	}

	.carrier-dot.carrier-up {
		background-color: var(--success);
		box-shadow: 0 0 6px var(--success);
	}

	.carrier-dot.carrier-down {
		background-color: var(--danger);
		box-shadow: 0 0 6px var(--danger);
	}

	.carrier-dot-inline {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: var(--radius-full);
		flex-shrink: 0;
	}

	.carrier-dot-inline.carrier-up {
		background-color: var(--success);
		box-shadow: 0 0 6px var(--success);
	}

	.carrier-dot-inline.carrier-down {
		background-color: var(--danger);
		box-shadow: 0 0 6px var(--danger);
	}

	/* ----- Wiring steps ----- */
	.wiring-steps {
		margin-bottom: var(--space-lg);
	}

	.wiring-steps h3 {
		font-size: var(--text-lg);
		font-weight: 600;
		margin-bottom: var(--space-sm);
	}

	.wiring-steps ol {
		padding-left: var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.wiring-steps li {
		font-size: var(--text-sm);
		line-height: var(--leading-relaxed);
		color: var(--text-secondary);
	}

	.carrier-status {
		display: flex;
		gap: var(--space-lg);
		padding: var(--space-md);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.carrier-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	/* ----- Health grid (Phase 3) ----- */
	.health-grid {
		margin: var(--space-md) 0;
	}

	.health-stat {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		padding: var(--space-sm);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-muted);
		border-radius: var(--radius-md);
	}

	.health-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		font-weight: 600;
	}

	.health-value {
		font-size: var(--text-lg);
		font-weight: 700;
		font-family: var(--font-mono);
	}

	.issues-section {
		margin-top: var(--space-md);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-default);
	}

	.issues-section h3 {
		font-size: var(--text-base);
		font-weight: 600;
		margin-bottom: var(--space-sm);
	}

	.issues-section ul {
		list-style: disc;
		padding-left: var(--space-lg);
	}

	.issues-section li {
		font-size: var(--text-sm);
		margin-bottom: var(--space-xs);
	}

	/* ----- Action buttons ----- */
	.action-buttons {
		display: flex;
		gap: var(--space-md);
		margin-top: var(--space-lg);
	}

	/* ----- Bypass confirmation modal ----- */
	.modal-overlay {
		position: fixed;
		inset: 0;
		background-color: var(--bg-overlay);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.modal-card {
		max-width: 480px;
		width: 90%;
	}

	.modal-actions {
		display: flex;
		gap: var(--space-sm);
		justify-content: flex-end;
		margin-top: var(--space-md);
	}

	/* ----- Responsive ----- */
	@media (max-width: 640px) {
		.phase-indicator {
			flex-wrap: wrap;
			gap: var(--space-xs);
		}

		.phase-connector {
			display: none;
		}

		.network-diagram {
			flex-direction: column;
			gap: var(--space-sm);
		}

		.diagram-cable {
			width: 2px;
			height: 20px;
			flex: 0 0 20px;
		}

		.cable-line {
			width: 2px;
			height: 100%;
		}

		.carrier-status {
			flex-direction: column;
			gap: var(--space-sm);
		}

		.action-buttons {
			flex-direction: column;
		}
	}
</style>
