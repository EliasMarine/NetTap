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
	import { fetchCaptureMode } from '$lib/api/capture.js';
	import DhcpGoLive from '$lib/components/golive/DhcpGoLive.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	// ----- Capture mode -----
	// null until /api/capture/mode answers. Bridge polling waits for it, so a
	// DHCP gateway install never hits the bridge endpoints from this page.
	let captureModeName = $state<string | null>(null);
	let modeError = $state('');
	let bridgeFlow = $derived(captureModeName !== null && captureModeName !== 'dhcp_gateway');

	async function loadCaptureMode() {
		modeError = '';
		try {
			// Throws on failure: getCaptureMode() guesses 'bridge', which would start
			// the bridge flow on a DHCP gateway install
			captureModeName = (await fetchCaptureMode()).mode;
		} catch (e) {
			modeError = `Could not read the capture mode: ${e instanceof Error ? e.message : 'unknown error'}`;
		}
	}

	$effect(() => {
		loadCaptureMode();
	});

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
	let bypassError = $state('');

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
		if (!bridgeFlow) return;

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
		bypassError = '';
		try {
			// OLD CODE START — #96: a failed toggle ({ result: 'error' }) was ignored
			// if (health?.bypass_active) {
			// 	await disableBypass();
			// } else {
			// 	await enableBypass();
			// }
			// OLD CODE END
			const wasActive = health?.bypass_active;
			const res = wasActive ? await disableBypass() : await enableBypass();
			if (res.result === 'error') {
				bypassError = `Couldn't ${wasActive ? 'disable' : 'enable'} bypass: the request failed.`;
			}
			// Refresh health
			await fetchHealth();
		} catch {
			// OLD CODE START — #96: a network error was swallowed
			// // Error will show from health refresh
			// OLD CODE END
			bypassError = "Couldn't change bypass mode: the request failed.";
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

	// OLD CODE START — 2026-11-03 redesign: legacy badge classes; the status is a system chip now
	// function statusBadgeClass(status: string): string {
	// 	switch (status) {
	// 		case 'normal':
	// 			return 'badge-success';
	// 		case 'degraded':
	// 			return 'badge-warning';
	// 		case 'bypass':
	// 			return 'badge-warning';
	// 		case 'down':
	// 		case 'not_configured':
	// 			return 'badge-danger';
	// 		default:
	// 			return 'badge-muted';
	// 	}
	// }
	// OLD CODE END
	/** The bridge status chip: the same mapping as the old badges, with the word always shown. */
	function statusChip(status: string): { cls: string; icon: 'check' | 'warn' | null } {
		switch (status) {
			case 'normal':
				return { cls: 'is-ok', icon: 'check' };
			case 'degraded':
			case 'bypass':
				return { cls: 'is-warn', icon: 'warn' };
			case 'down':
			case 'not_configured':
				return { cls: 'is-bad', icon: 'warn' };
			default:
				return { cls: '', icon: null };
		}
	}

	/** "not_configured" reads "Not configured". */
	function statusWord(status: string): string {
		const words = status.replace(/_/g, ' ');
		return words.charAt(0).toUpperCase() + words.slice(1);
	}

	const PHASES = [
		{ n: 1, label: 'Readiness' },
		{ n: 2, label: 'Wiring' },
		{ n: 3, label: 'Monitoring' },
	] as const;
</script>

<svelte:head>
	<title>Go Live | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Go Live</h1>
		<p class="page-sub">Connect NetTap to your network</p>
	</div>
</div>

{#if modeError}
	<div class="grid">
		<Card title="Capture mode" sub="Go Live follows the mode chosen during setup" class="c-12">
			<CardState
				state="error"
				title="Couldn't start Go Live"
				message={modeError}
				actionLabel="Retry"
				onaction={loadCaptureMode}
			/>
		</Card>
	</div>
{:else if captureModeName === null}
	<div class="grid">
		<Card title="Capture mode" sub="Go Live follows the mode chosen during setup" class="c-12">
			<CardState state="loading" title="Loading the capture mode" />
		</Card>
	</div>
{:else if captureModeName === 'dhcp_gateway'}
	<DhcpGoLive />
{:else}
	<!-- Step indicator: the system's pill track. The phase follows the readiness checks, so it is not a control. -->
	<ol class="pills phases" aria-label="Go Live progress">
		{#each PHASES as p (p.n)}
			<li class="pill" aria-current={phase === p.n ? 'step' : undefined}>
				{#if phase > p.n}<Icon name="check" label="Done" />{/if}
				<span>{p.label}</span>
			</li>
		{/each}
	</ol>

	<!-- ==================== PHASE 1: Readiness Check ==================== -->
	{#if phase === 1}
		<div class="grid">
			<Card title="Readiness check" sub="Checked every 3 seconds" class="c-12">
				{#snippet actions()}
					{#if readinessLoading}
						<span class="chip">Checking…</span>
					{:else if readiness?.ready}
						<span class="chip is-ok"><Icon name="check" />Ready</span>
					{:else if !readiness}
						<span class="chip">Unknown</span>
					{:else}
						<span class="chip is-warn"><Icon name="warn" />Not ready</span>
					{/if}
				{/snippet}

				<div class="stack">
					{#if readinessError}
						<div class="notice is-error" role="alert"><Icon name="warn" /><span>{readinessError}</span></div>
					{/if}

					{#if readiness?.checks && readiness.checks.length > 0}
						<ul class="checklist">
							{#each readiness.checks as check}
								<li class="check" class:passed={check.passed}>
									<span class="check-icon"><Icon name={check.passed ? 'check' : 'close'} label={check.passed ? 'Passed' : 'Failed'} /></span>
									<span class="check-body">
										<span class="check-name">{check.name.replace(/_/g, ' ')}</span>
										{#if check.detail}<span class="check-detail">{check.detail}</span>{/if}
									</span>
								</li>
							{/each}
						</ul>
					{:else if !readinessLoading}
						<p class="muted">No readiness checks returned. Is the daemon running?</p>
					{/if}

					<!-- OLD CODE START — #96: a failed readiness check read as "not created yet"
					{#if !bridgeExists}
					OLD CODE END -->
					{#if readiness && !bridgeExists}
						<div class="action-section">
							<p class="muted">The bridge has not been created yet. Create it to proceed.</p>
							{#if createError}
								<div class="notice is-error" role="alert"><Icon name="warn" /><span>{createError}</span></div>
							{/if}
							<div class="actions">
								<button class="btn primary" onclick={handleCreateBridge} disabled={creating}>
									{creating ? 'Creating bridge…' : 'Create bridge'}
								</button>
							</div>
						</div>
					{/if}

					{#if readiness?.message}
						<p class="muted">{readiness.message}</p>
					{/if}
				</div>
			</Card>
		</div>

	<!-- ==================== PHASE 2: Wiring Guide ==================== -->
	{:else if phase === 2}
		<div class="grid">
			<Card title="Cable your network" sub="Link state checked every 3 seconds" class="c-12">
				{#snippet actions()}
					<span class="chip">Waiting for links</span>
				{/snippet}

				<div class="stack">
					<p class="muted">Follow the steps below to connect NetTap inline between your modem and router.</p>

					<!-- Modem → WAN port → NetTap bridge → LAN port → router -->
					<div class="diagram">
						<div class="node">
							<span class="tile"><Icon name="dns" /></span>
							<span class="node-label">ISP modem</span>
						</div>
						<span class="cable" aria-hidden="true"></span>
						<div class="node">
							<span class="tag">{wanIface}</span>
							<span class="node-label">WAN</span>
							<span class="res" class:is-live={wanCarrier} class:is-medium={!wanCarrier}>{wanCarrier ? 'Connected' : 'No carrier'}</span>
						</div>
						<span class="cable" aria-hidden="true"></span>
						<div class="node">
							<span class="tile accent"><Icon name="connections" /></span>
							<span class="node-label">NetTap <span class="mono">br0</span></span>
						</div>
						<span class="cable" aria-hidden="true"></span>
						<div class="node">
							<span class="tag">{lanIface}</span>
							<span class="node-label">LAN</span>
							<span class="res" class:is-live={lanCarrier} class:is-medium={!lanCarrier}>{lanCarrier ? 'Connected' : 'No carrier'}</span>
						</div>
						<span class="cable" aria-hidden="true"></span>
						<div class="node">
							<span class="tile"><Icon name="infra" /></span>
							<span class="node-label">Router</span>
						</div>
					</div>

					<div>
						<h3 class="sub-title">Steps</h3>
						<ol class="steps">
							<li><strong>Disconnect</strong> the Ethernet cable running from your ISP modem to your router.</li>
							<li>
								<strong>Connect</strong> the modem's Ethernet cable to the <span class="tag">{wanIface}</span> port on NetTap (WAN).
							</li>
							<li>
								<strong>Connect</strong> a new Ethernet cable from the <span class="tag">{lanIface}</span> port on NetTap (LAN) to your router's WAN port.
							</li>
							<li><strong>Wait</strong> for both ports above to read Connected. This page moves on by itself.</li>
						</ol>
					</div>
				</div>
			</Card>
		</div>

	<!-- ==================== PHASE 3: Live Monitoring ==================== -->
	{:else if phase === 3}
		{#if health?.bypass_active}
			<div class="notice is-warn">
				<Icon name="warn" />
				<span><strong>Bypass mode is on.</strong> Traffic passes through without inspection. Turn bypass off to resume monitoring.</span>
			</div>
		{/if}

		<div class="notice is-ok">
			<Icon name="check" />
			<!-- OLD CODE: …monitoring your network.</strong> All traffic between your modem and router is analysed for threats and anomalies. (NET-225: overclaimed; encrypted content and bypassing traffic aren't analysed) -->
			<span><strong>NetTap is monitoring your network.</strong> It analyses the traffic that crosses its capture point: connection records, DNS and TLS names, and intrusion-detection rules on anything unencrypted. It can't read encrypted content, and it doesn't see traffic that bypasses the capture point.</span>
		</div>

		<div class="grid">
			<Card title="Bridge health" sub="Packets since the last check · checked every 5 seconds" class="c-12">
				{#snippet actions()}
					{#if health}
						{@const chip = statusChip(health.health_status)}
						<span class="chip {chip.cls}">{#if chip.icon}<Icon name={chip.icon} />{/if}{statusWord(health.health_status)}</span>
					{:else if healthError}
						<span class="chip is-bad"><Icon name="warn" />Error</span>
					{:else}
						<span class="chip">Loading…</span>
					{/if}
				{/snippet}

				<div class="stack">
					{#if healthError}
						<div class="notice is-error" role="alert"><Icon name="warn" /><span>{healthError}</span></div>
					{/if}

					{#if health}
						<div class="stats health-stats">
							<div class="stat">
								<div class="stat-k">WAN link</div>
								<div class="stat-v link" class:up={health.wan_link}>{health.wan_link ? 'Up' : 'Down'}</div>
							</div>
							<div class="stat">
								<div class="stat-k">LAN link</div>
								<div class="stat-v link" class:up={health.lan_link}>{health.lan_link ? 'Up' : 'Down'}</div>
							</div>
							<div class="stat">
								<div class="stat-k">RX packets</div>
								<div class="stat-v">{formatPackets(health.rx_packets_delta)}</div>
							</div>
							<div class="stat">
								<div class="stat-k">TX packets</div>
								<div class="stat-v">{formatPackets(health.tx_packets_delta)}</div>
							</div>
							<div class="stat">
								<div class="stat-k">Latency</div>
								<!-- OLD CODE START — read "null us" now that the daemon doesn't make up a latency
								<span class="health-value">{health.latency_us} us</span>
								OLD CODE END -->
								<div class="stat-v" title={health.latency_note || undefined}>{health.latency_us != null ? `${health.latency_us} us` : 'Not measured'}</div>
							</div>
							<div class="stat">
								<div class="stat-k">Uptime</div>
								<div class="stat-v">{formatUptime(health.uptime_seconds)}</div>
							</div>
							<div class="stat">
								<div class="stat-k">Bridge state</div>
								<div class="stat-v mono">{health.bridge_state}</div>
							</div>
							<div class="stat">
								<div class="stat-k">Bypass</div>
								<div class="stat-v">{health.bypass_active ? 'On' : 'Off'}</div>
							</div>
						</div>

						{#if health.issues.length > 0}
							<div class="issues">
								<h3 class="sub-title">Issues</h3>
								<ul>
									{#each health.issues as issue}
										<li><Icon name="warn" /><span>{issue}</span></li>
									{/each}
								</ul>
							</div>
						{/if}
					{/if}
				</div>
			</Card>
		</div>

		<div class="actions">
			<button class="btn primary" onclick={() => goto('/')}>Go to dashboard</button>

			<!-- #96: no bypass toggle while the bridge state is unknown -->
			{#if health?.bypass_active}
				<button class="btn" onclick={handleBypassToggle} disabled={bypassToggling}>
					{bypassToggling ? 'Turning bypass off…' : 'Disable bypass'}
				</button>
			{:else}
				<button
					class="btn danger"
					onclick={() => { bypassConfirmOpen = true; }}
					disabled={bypassToggling || !health}
				>
					Enable bypass
				</button>
			{/if}
		</div>
		{#if bypassError}
			<div class="notice is-error" role="alert"><Icon name="warn" /><span>{bypassError}</span></div>
		{/if}

		<!-- Bypass confirmation dialog -->
		{#if bypassConfirmOpen}
			<div class="overlay" onclick={() => { bypassConfirmOpen = false; }} role="presentation">
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<div
					class="card dialog"
					role="dialog"
					aria-modal="true"
					aria-labelledby="bypass-title"
					tabindex="-1"
					onclick={(e) => e.stopPropagation()}
				>
					<h2 id="bypass-title" class="card-title">Turn on bypass mode?</h2>
					<p class="muted">
						Bypass mode stops all traffic inspection. Packets pass through the bridge without being analysed.
						Use it only for troubleshooting.
					</p>
					<div class="actions end">
						<button class="btn" onclick={() => { bypassConfirmOpen = false; }}>Cancel</button>
						<button class="btn danger" onclick={handleBypassToggle} disabled={bypassToggling}>
							{bypassToggling ? 'Turning bypass on…' : 'Turn on bypass'}
						</button>
					</div>
				</div>
			</div>
		{/if}
	{/if}
{/if}

<style>
	/* Step indicator: the pill track, read-only. The system styles aria-pressed and
	   aria-current="page"; a step is aria-current="step", so it gets the same light pill here. */
	.phases {
		list-style: none;
		margin: 0;
		align-self: flex-start;
		max-width: 100%;
		overflow-x: auto;
	}

	.phases .pill {
		gap: var(--sp-1);
		cursor: default;
	}

	.phases .pill[aria-current='step'] {
		background: var(--pill-active-bg);
		color: var(--on-light);
	}

	.phases .pill :global(.ic) {
		width: 14px;
		height: 14px;
		stroke-width: 2.2;
	}

	.muted {
		color: var(--text-2);
		font-size: var(--text-sm);
	}

	.sub-title {
		font: 500 var(--text-base)/1.3 var(--font-display);
		margin-bottom: var(--sp-2);
	}

	/* ----- Readiness checklist ----- */
	.checklist {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.check {
		display: flex;
		align-items: flex-start;
		gap: var(--sp-3);
		padding: var(--sp-2) 0;
		border-bottom: 1px solid var(--line);
	}

	.check:last-child {
		border-bottom: 0;
	}

	.check-icon {
		display: inline-flex;
		padding-top: 2px;
		color: var(--sev-critical);
	}

	.check.passed .check-icon {
		color: var(--ok);
	}

	.check-body {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.check-name {
		font-weight: 600;
		font-size: var(--text-sm);
	}

	.check-name::first-letter {
		text-transform: uppercase;
	}

	.check-detail {
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.action-section {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
	}

	/* ----- Wiring diagram ----- */
	.diagram {
		display: flex;
		align-items: center;
		justify-content: center;
		flex-wrap: wrap;
		gap: var(--sp-3);
		padding: var(--sp-5);
		border-radius: var(--r-md);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}

	.node {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-1);
		text-align: center;
	}

	.node-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-2);
	}

	.tile.accent {
		color: var(--accent);
	}

	.cable {
		width: var(--sp-8);
		height: 2px;
		border-radius: var(--r-pill);
		background: var(--line-strong);
	}

	.steps {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		margin: 0;
		padding-left: var(--sp-6);
		font-size: var(--text-sm);
		color: var(--text-2);
		line-height: 1.7;
	}

	.steps strong {
		color: var(--text-1);
	}

	/* ----- Health stats: the system's strip, eight stats in two rows of four ----- */
	.health-stats {
		row-gap: var(--sp-5);
	}

	.health-stats .stat:nth-child(4n + 1) {
		padding-left: 0;
		border-left: 0;
	}

	.link {
		color: var(--sev-critical);
	}

	.link.up {
		color: var(--ok);
	}

	.issues ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.issues li {
		display: flex;
		gap: var(--sp-2);
		font-size: var(--text-sm);
	}

	.issues li :global(.ic) {
		flex: none;
		width: 16px;
		height: 16px;
		margin-top: 2px;
		color: var(--sev-medium);
	}

	.actions.end {
		justify-content: flex-end;
	}

	.btn.danger {
		color: var(--sev-critical);
	}

	/* ----- Bypass confirmation ----- */
	.overlay {
		position: fixed;
		inset: 0;
		z-index: 40;
		display: grid;
		place-items: center;
		padding: var(--sp-4);
		background: var(--scrim);
	}

	.dialog {
		width: min(100%, 480px);
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		box-shadow: var(--shadow-pop);
	}

	@container app (max-width: 760px) {
		.health-stats .stat:nth-child(odd) {
			padding-left: 0;
			border-left: 0;
		}
	}
</style>
