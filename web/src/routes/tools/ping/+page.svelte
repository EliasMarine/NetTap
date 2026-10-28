<script lang="ts">
	/**
	 * Ping & Traceroute — Test reachability, measure latency, trace routes.
	 *
	 * Layout:
	 *   - Back button to /tools
	 *   - Target + Count inputs, Ping & Traceroute buttons
	 *   - Tab switcher (Ping Results / Traceroute)
	 *   - Ping: 4-stat cards, RTT bar chart, reply table
	 *   - Traceroute: visual hop path, hop table
	 *   - Reads URL query params: ?target=X&tab=traceroute
	 */

	import { page } from '$app/stores';
	import { ping, traceroute } from '$api/tools';
	import type { PingResult, TracerouteResult } from '$api/tools';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let target = $state('');
	let count = $state(4);
	let activeTab = $state<'ping' | 'traceroute'>('ping');

	let pingResult = $state<PingResult | null>(null);
	let traceResult = $state<TracerouteResult | null>(null);
	let pingLoading = $state(false);
	let traceLoading = $state(false);
	let pingError = $state('');
	let traceError = $state('');

	// ---------------------------------------------------------------------------
	// Read URL query params on load
	// ---------------------------------------------------------------------------

	$effect(() => {
		const params = $page.url.searchParams;
		const t = params.get('target');
		const tab = params.get('tab');
		if (t) target = t;
		if (tab === 'traceroute') activeTab = 'traceroute';
	});

	// ---------------------------------------------------------------------------
	// Actions
	// ---------------------------------------------------------------------------

	async function runPing() {
		const trimmed = target.trim();
		if (!trimmed) return;
		pingLoading = true;
		pingError = '';
		pingResult = null;
		activeTab = 'ping';
		try {
			pingResult = await ping(trimmed, count);
			if (pingResult.error) pingError = pingResult.error;
		} catch (e) {
			pingError = e instanceof Error ? e.message : 'Ping failed';
		} finally {
			pingLoading = false;
		}
	}

	async function runTraceroute() {
		const trimmed = target.trim();
		if (!trimmed) return;
		traceLoading = true;
		traceError = '';
		traceResult = null;
		activeTab = 'traceroute';
		try {
			traceResult = await traceroute(trimmed, 30);
			if (traceResult.error) traceError = traceResult.error;
		} catch (e) {
			traceError = e instanceof Error ? e.message : 'Traceroute failed';
		} finally {
			traceLoading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') runPing();
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function rttColor(ms: number): string {
		if (ms < 50) return 'good';
		if (ms < 200) return 'medium';
		return 'bad';
	}

	function traceRttColor(ms: number): string {
		if (ms < 10) return 'good';
		if (ms < 100) return 'medium';
		return 'bad';
	}

	function barHeight(ms: number, maxMs: number): number {
		if (maxMs <= 0) return 10;
		return Math.max(10, Math.round((ms / maxMs) * 80));
	}

	let maxRtt = $derived(
		pingResult?.replies?.length
			? Math.max(...pingResult.replies.map((r) => r.time_ms))
			: 1
	);
</script>

<svelte:head>
	<title>Ping & Traceroute | NetTap</title>
</svelte:head>

<div class="ping-page">
	<!-- Back button -->
	<div class="back-nav">
		<a href="/tools" class="btn btn-secondary btn-sm">
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
			</svg>
			Back to Tools
		</a>
	</div>

	<!-- Page header -->
	<div class="page-header">
		<h1>Ping & Traceroute</h1>
		<p class="page-desc">Test reachability, measure latency, and trace packet routes</p>
	</div>

	<!-- Input card -->
	<div class="input-card">
		<div class="input-row">
			<div class="input-group">
				<span class="input-label">Target</span>
				<input
					type="text"
					class="input-field"
					placeholder="IP or hostname"
					bind:value={target}
					onkeydown={handleKeydown}
				/>
			</div>
			<div class="input-group input-sm">
				<span class="input-label">Count</span>
				<input
					type="number"
					class="input-field"
					bind:value={count}
					min="1"
					max="10"
				/>
			</div>
			<button class="btn btn-primary" onclick={runPing} disabled={pingLoading || !target.trim()}>
				{#if pingLoading}
					<span class="spinner"></span>
				{:else}
					<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M22 12h-4l-3 9L9 3l-3 9H2" />
					</svg>
				{/if}
				Ping
			</button>
			<button class="btn btn-secondary" onclick={runTraceroute} disabled={traceLoading || !target.trim()}>
				{#if traceLoading}
					<span class="spinner"></span>
				{:else}
					<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
					</svg>
				{/if}
				Traceroute
			</button>
		</div>
	</div>

	<!-- Tabs -->
	<div class="tabs">
		<button class="tab" class:active={activeTab === 'ping'} onclick={() => activeTab = 'ping'}>
			Ping Results
		</button>
		<button class="tab" class:active={activeTab === 'traceroute'} onclick={() => activeTab = 'traceroute'}>
			Traceroute
		</button>
	</div>

	<!-- ========== PING TAB ========== -->
	{#if activeTab === 'ping'}
		{#if pingLoading}
			<div class="card loading-card">
				<div class="skeleton-grid four-col">
					{#each Array(4) as _}
						<div class="skeleton skeleton-stat"></div>
					{/each}
				</div>
				<div class="skeleton skeleton-chart"></div>
			</div>
		{:else if pingError}
			<div class="empty-state">
				<div class="empty-icon">
					<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
					</svg>
				</div>
				<h3>Ping Failed</h3>
				<p class="text-muted">{pingError}</p>
			</div>
		{:else if pingResult}
			<!-- Stats -->
			<div class="stats-grid">
				<div class="stat-card">
					<span class="stat-value" class:green={pingResult.packet_loss_pct === 0} class:amber={pingResult.packet_loss_pct > 0 && pingResult.packet_loss_pct < 100} class:red={pingResult.packet_loss_pct === 100}>
						{pingResult.packet_loss_pct}%
					</span>
					<span class="stat-label">Packet Loss</span>
				</div>
				<div class="stat-card">
					<span class="stat-value cyan">{pingResult.rtt_avg.toFixed(1)}ms</span>
					<span class="stat-label">Avg RTT</span>
				</div>
				<div class="stat-card">
					<span class="stat-value blue">{pingResult.rtt_min.toFixed(1)}ms</span>
					<span class="stat-label">Min RTT</span>
				</div>
				<div class="stat-card">
					<span class="stat-value amber">{pingResult.rtt_max.toFixed(1)}ms</span>
					<span class="stat-label">Max RTT</span>
				</div>
			</div>

			<!-- RTT bar chart -->
			{#if pingResult.replies.length > 0}
				<div class="rtt-chart">
					<div class="rtt-chart-title">Round-Trip Time (ms)</div>
					<div class="rtt-bars">
						{#each pingResult.replies as reply}
							<div class="rtt-bar-wrapper">
								<div class="rtt-bar-value">{reply.time_ms.toFixed(1)}</div>
								<div
									class="rtt-bar {rttColor(reply.time_ms)}"
									style="height: {barHeight(reply.time_ms, maxRtt)}px;"
								></div>
								<span class="rtt-bar-seq">#{reply.seq}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Reply table -->
			{#if pingResult.replies.length > 0}
				<div class="data-table">
					<table>
						<thead>
							<tr>
								<th>Seq</th>
								<th>From</th>
								<th>Bytes</th>
								<th>TTL</th>
								<th>Time</th>
							</tr>
						</thead>
						<tbody>
							{#each pingResult.replies as reply}
								<tr>
									<td class="text-muted">{reply.seq}</td>
									<td class="blue">{reply.from}</td>
									<td>{reply.bytes}</td>
									<td>{reply.ttl}</td>
									<td class="rtt-{rttColor(reply.time_ms)}">{reply.time_ms.toFixed(1)} ms</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{:else}
			<div class="empty-state">
				<div class="empty-icon">
					<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<path d="M22 12h-4l-3 9L9 3l-3 9H2" />
					</svg>
				</div>
				<h3>No Results Yet</h3>
				<p class="text-muted">Enter a target and click Ping or Traceroute to begin.</p>
			</div>
		{/if}
	{/if}

	<!-- ========== TRACEROUTE TAB ========== -->
	{#if activeTab === 'traceroute'}
		{#if traceLoading}
			<div class="card loading-card">
				<div class="skeleton skeleton-chart"></div>
				<div class="skeleton skeleton-table"></div>
			</div>
		{:else if traceError}
			<div class="empty-state">
				<div class="empty-icon">
					<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
					</svg>
				</div>
				<h3>Traceroute Failed</h3>
				<p class="text-muted">{traceError}</p>
			</div>
		{:else if traceResult && traceResult.hops.length > 0}
			<!-- Visual hop path -->
			<div class="hop-path">
				<div class="hop-node">
					<div class="hop-label">NetTap</div>
					<div class="hop-dot start"></div>
					<div class="hop-rtt-label">0ms</div>
				</div>
				{#each traceResult.hops as hop}
					<div class="hop-line" class:active={hop.host !== '* * *'}></div>
					<div class="hop-node">
						<div class="hop-label" class:timeout={hop.host === '* * *'}>
							{hop.host === '* * *' ? '* * *' : (hop.host || hop.ip)}
						</div>
						<div class="hop-dot" class:timeout={hop.host === '* * *'} class:end={hop.hop === traceResult.total_hops}></div>
						<div class="hop-rtt-label">
							{#if hop.rtts.length > 0 && hop.rtts[0] > 0}
								{hop.rtts[0].toFixed(1)}ms
							{:else}
								timeout
							{/if}
						</div>
					</div>
				{/each}
			</div>

			<!-- Traceroute table -->
			<div class="data-table">
				<table>
					<thead>
						<tr>
							<th>Hop</th>
							<th>Host</th>
							<th>IP</th>
							<th>RTT 1</th>
							<th>RTT 2</th>
							<th>RTT 3</th>
						</tr>
					</thead>
					<tbody>
						{#each traceResult.hops as hop}
							<tr>
								<td class="text-muted">{hop.hop}</td>
								{#if hop.host === '* * *'}
									<td class="timeout">* * *</td>
									<td class="timeout">--</td>
									<td class="timeout">*</td>
									<td class="timeout">*</td>
									<td class="timeout">*</td>
								{:else}
									<td>{hop.host}</td>
									<td class="blue">{hop.ip}</td>
									{#each [0, 1, 2] as i}
										{#if hop.rtts[i] != null && hop.rtts[i] > 0}
											<td class="rtt-{traceRttColor(hop.rtts[i])}">{hop.rtts[i].toFixed(3)} ms</td>
										{:else}
											<td class="timeout">*</td>
										{/if}
									{/each}
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<div class="empty-state">
				<div class="empty-icon">
					<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
					</svg>
				</div>
				<h3>No Traceroute Results</h3>
				<p class="text-muted">Enter a target and click Traceroute to trace the route.</p>
			</div>
		{/if}
	{/if}
</div>

<style>
	.ping-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Back nav */
	.back-nav {
		display: flex;
	}

	/* Page header */
	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.page-header h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
	}

	.page-desc {
		color: var(--text-secondary);
		font-size: var(--text-sm);
	}

	/* Input card */
	.input-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
	}

	.input-row {
		display: flex;
		gap: var(--space-md);
		align-items: flex-end;
	}

	.input-group {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.input-sm {
		max-width: 100px;
		flex: 0 0 auto;
	}

	.input-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.input-field {
		padding: 10px 14px;
		background: var(--bg-input);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		color: var(--text-primary);
		font-size: var(--text-sm);
		font-family: var(--font-mono);
		outline: none;
		transition: border-color var(--transition-fast);
		width: 100%;
	}

	.input-field::placeholder {
		color: var(--text-dim);
	}

	.input-field:focus {
		border-color: var(--accent);
	}

	/* Tabs */
	.tabs {
		display: flex;
		gap: 4px;
		border-bottom: 1px solid var(--border-dim);
		padding-bottom: 0;
	}

	.tab {
		padding: 10px 20px;
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-muted);
		cursor: pointer;
		border: none;
		background: none;
		border-bottom: 2px solid transparent;
		margin-bottom: -1px;
		transition: all var(--transition-fast);
		font-family: inherit;
	}

	.tab:hover {
		color: var(--text-secondary);
	}

	.tab.active {
		color: var(--accent);
		border-bottom-color: var(--accent);
	}

	/* Stats grid */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
	}

	.stat-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.stat-value {
		font-family: var(--font-mono);
		font-size: var(--text-2xl);
		font-weight: 700;
	}

	.stat-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.stat-value.green { color: var(--green); }
	.stat-value.cyan { color: var(--cyan); }
	.stat-value.blue { color: #448aff; }
	.stat-value.amber { color: var(--amber); }
	.stat-value.red { color: var(--red); }

	/* RTT chart */
	.rtt-chart {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
	}

	.rtt-chart-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-secondary);
		margin-bottom: var(--space-md);
	}

	.rtt-bars {
		display: flex;
		align-items: flex-end;
		gap: 8px;
		height: 100px;
		padding-bottom: 24px;
		position: relative;
	}

	.rtt-bar-wrapper {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		position: relative;
	}

	.rtt-bar {
		width: 100%;
		max-width: 48px;
		border-radius: 4px 4px 0 0;
		transition: height 0.6s cubic-bezier(0.22, 1, 0.36, 1);
	}

	.rtt-bar.good {
		background: linear-gradient(to top, var(--green), rgba(0, 230, 118, 0.4));
	}

	.rtt-bar.medium {
		background: linear-gradient(to top, var(--amber), rgba(255, 171, 0, 0.4));
	}

	.rtt-bar.bad {
		background: linear-gradient(to top, var(--red), rgba(255, 71, 87, 0.4));
	}

	.rtt-bar-value {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: center;
	}

	.rtt-bar-seq {
		font-family: var(--font-mono);
		font-size: 0.65rem;
		color: var(--text-dim);
		position: absolute;
		bottom: -20px;
		text-align: center;
		width: 100%;
	}

	/* Data table (shared for ping replies + traceroute) */
	.data-table {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		overflow: hidden;
	}

	.data-table table {
		width: 100%;
		border-collapse: collapse;
	}

	.data-table th {
		text-align: left;
		padding: 10px 20px;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		background: var(--bg-elevated);
		border-bottom: 1px solid var(--border-dim);
	}

	.data-table td {
		padding: 10px 20px;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--text-primary);
		border-bottom: 1px solid var(--border-dim);
	}

	.data-table tr:last-child td {
		border-bottom: none;
	}

	.data-table tr:hover td {
		background: rgba(255, 255, 255, 0.02);
	}

	.blue { color: #448aff; }
	.timeout { color: var(--text-dim); font-style: italic; }

	.rtt-good { color: var(--green); }
	.rtt-medium { color: var(--amber); }
	.rtt-bad { color: var(--red); }

	/* Visual hop path */
	.hop-path {
		display: flex;
		align-items: center;
		gap: 0;
		overflow-x: auto;
		padding: var(--space-md) 0;
	}

	.hop-node {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		min-width: 80px;
		position: relative;
	}

	.hop-dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		background: #448aff;
		border: 2px solid var(--bg-void);
		box-shadow: 0 0 8px rgba(68, 138, 255, 0.4);
		z-index: 1;
	}

	.hop-dot.start {
		background: var(--green);
		box-shadow: 0 0 8px rgba(0, 230, 118, 0.4);
	}

	.hop-dot.end {
		background: var(--cyan);
		box-shadow: 0 0 8px rgba(0, 212, 255, 0.4);
		width: 16px;
		height: 16px;
	}

	.hop-dot.timeout {
		background: var(--text-dim);
		box-shadow: none;
		opacity: 0.5;
	}

	.hop-line {
		flex: 1;
		height: 2px;
		background: var(--border-bright);
		min-width: 30px;
	}

	.hop-line.active {
		background: linear-gradient(90deg, #448aff, rgba(68, 138, 255, 0.3));
	}

	.hop-label {
		font-size: 0.65rem;
		font-family: var(--font-mono);
		color: var(--text-muted);
		text-align: center;
		max-width: 80px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.hop-label.timeout {
		color: var(--text-dim);
		font-style: italic;
	}

	.hop-rtt-label {
		font-size: 0.6rem;
		font-family: var(--font-mono);
		color: var(--text-dim);
	}

	/* Spinner */
	.spinner {
		width: 14px;
		height: 14px;
		border: 2px solid rgba(255, 255, 255, 0.3);
		border-top-color: #fff;
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
		display: inline-block;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Loading state */
	.loading-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.skeleton {
		background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--border-muted) 50%, var(--bg-tertiary) 75%);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
		border-radius: var(--radius-sm);
	}

	.skeleton-grid {
		display: grid;
		gap: var(--space-md);
	}

	.skeleton-grid.four-col {
		grid-template-columns: repeat(4, 1fr);
	}

	.skeleton-stat {
		height: 72px;
	}

	.skeleton-chart {
		height: 140px;
	}

	.skeleton-table {
		height: 200px;
	}

	@keyframes shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}

	/* Empty / error state */
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		text-align: center;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
	}

	.empty-icon {
		color: var(--text-muted);
		margin-bottom: var(--space-md);
	}

	.empty-state h3 {
		font-size: var(--text-xl);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	/* Responsive */
	@media (max-width: 768px) {
		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.input-row {
			flex-direction: column;
		}

		.input-sm {
			max-width: 100%;
		}

		.skeleton-grid.four-col {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
