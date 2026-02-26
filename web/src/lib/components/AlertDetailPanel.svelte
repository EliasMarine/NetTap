<!--
  AlertDetailPanel.svelte — Slide-out panel showing full alert details.

  Slides in from the right (480px wide) with a backdrop overlay.
  Shows alert severity, signature, plain-English description, risk context,
  recommendation, flow visualization, timestamps, category, device links,
  and an acknowledge button.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { acknowledgeAlert } from '$api/alerts';
	import type { Alert } from '$api/alerts';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		alert = null,
		onclose = () => {},
	}: {
		alert: Alert | null;
		onclose: () => void;
	} = $props();

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let acknowledging = $state(false);
	let acknowledgeError = $state('');

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let isOpen = $derived(alert !== null);

	let severityLabel = $derived.by(() => {
		if (!alert?.alert?.severity) return 'INFO';
		switch (alert.alert.severity) {
			case 1:
				return 'HIGH';
			case 2:
				return 'MEDIUM';
			case 3:
				return 'LOW';
			default:
				return 'INFO';
		}
	});

	let severityClass = $derived.by(() => {
		if (!alert?.alert?.severity) return 'badge';
		switch (alert.alert.severity) {
			case 1:
				return 'badge badge-danger';
			case 2:
				return 'badge badge-warning';
			case 3:
				return 'badge badge-accent';
			default:
				return 'badge';
		}
	});

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatTimestamp(ts: string | undefined): string {
		if (!ts) return '--';
		try {
			const d = new Date(ts);
			return d.toLocaleString(undefined, {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
			});
		} catch {
			return ts;
		}
	}

	function protoLabel(proto: string | undefined): string {
		if (!proto) return '?';
		return proto.toUpperCase();
	}

	// ---------------------------------------------------------------------------
	// Actions
	// ---------------------------------------------------------------------------

	async function handleAcknowledge() {
		if (!alert) return;
		acknowledging = true;
		acknowledgeError = '';

		try {
			const result = await acknowledgeAlert(alert._id);
			if (result) {
				// Update the local alert object to reflect acknowledged state
				alert.acknowledged = true;
				alert.acknowledged_at = result.acknowledged_at;
			} else {
				acknowledgeError = 'Failed to acknowledge alert. Please try again.';
			}
		} catch {
			acknowledgeError = 'Network error. Please check your connection.';
		} finally {
			acknowledging = false;
		}
	}

	function handleBackdropClick() {
		onclose();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			onclose();
		}
	}

	function navigateToDevice(ip: string) {
		goto(`/devices/${encodeURIComponent(ip)}`);
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Backdrop -->
{#if isOpen}
	<button
		class="panel-backdrop"
		onclick={handleBackdropClick}
		aria-label="Close alert detail panel"
		tabindex="-1"
	></button>
{/if}

<!-- Slide-out panel -->
<aside class="alert-detail-panel" class:open={isOpen} aria-label="Alert details">
	{#if alert}
		<!-- Header -->
		<div class="panel-header">
			<div class="panel-header-left">
				<span class={severityClass}>{severityLabel}</span>
				{#if alert.alert?.category}
					<span class="badge">{alert.alert.category}</span>
				{/if}
			</div>
			<button class="panel-close-btn" onclick={onclose} aria-label="Close panel">
				<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
				</svg>
			</button>
		</div>

		<!-- Body (scrollable) -->
		<div class="panel-body">
			<!-- Signature / title -->
			<section class="panel-section">
				<h3 class="alert-signature">{alert.alert?.signature || 'Unknown Alert'}</h3>
				<p class="alert-timestamp mono">{formatTimestamp(alert.timestamp)}</p>
			</section>

			<!-- Plain description -->
			{#if alert.plain_description}
				<section class="panel-section">
					<h4 class="section-label">What happened</h4>
					<p class="section-body">{alert.plain_description}</p>
				</section>
			{/if}

			<!-- Risk context -->
			{#if alert.risk_context}
				<section class="panel-section">
					<h4 class="section-label">Risk context</h4>
					<p class="section-body">{alert.risk_context}</p>
				</section>
			{/if}

			<!-- Recommendation -->
			{#if alert.recommendation}
				<section class="panel-section">
					<h4 class="section-label">Recommendation</h4>
					<p class="section-body">{alert.recommendation}</p>
				</section>
			{/if}

			<!-- Flow visualization -->
			<section class="panel-section">
				<h4 class="section-label">Network flow</h4>
				<div class="flow-visualization">
					<div class="flow-endpoint flow-source">
						<span class="flow-label">Source</span>
						<span class="flow-ip">
							{#if alert.src_ip}
								<IPAddress ip={alert.src_ip} />
							{:else}
								<span class="text-muted">--</span>
							{/if}
						</span>
						{#if alert.src_port}
							<span class="flow-port mono">:{alert.src_port}</span>
						{/if}
					</div>

					<div class="flow-arrow">
						<svg viewBox="0 0 48 24" width="48" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<line x1="4" y1="12" x2="40" y2="12" />
							<polyline points="34 6 40 12 34 18" />
						</svg>
						{#if alert.proto}
							<span class="badge flow-proto-badge">{protoLabel(alert.proto)}</span>
						{/if}
					</div>

					<div class="flow-endpoint flow-dest">
						<span class="flow-label">Destination</span>
						<span class="flow-ip">
							{#if alert.dest_ip}
								<IPAddress ip={alert.dest_ip} />
							{:else}
								<span class="text-muted">--</span>
							{/if}
						</span>
						{#if alert.dest_port}
							<span class="flow-port mono">:{alert.dest_port}</span>
						{/if}
					</div>
				</div>
			</section>

			<!-- Device links -->
			<section class="panel-section">
				<h4 class="section-label">Device links</h4>
				<div class="device-links">
					{#if alert.src_ip}
						<button
							class="btn btn-secondary btn-sm"
							onclick={() => navigateToDevice(alert!.src_ip!)}
						>
							<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
							</svg>
							View source device ({alert.src_ip})
						</button>
					{/if}
					{#if alert.dest_ip}
						<button
							class="btn btn-secondary btn-sm"
							onclick={() => navigateToDevice(alert!.dest_ip!)}
						>
							<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
							</svg>
							View dest device ({alert.dest_ip})
						</button>
					{/if}
				</div>
			</section>

			<!-- Metadata -->
			<section class="panel-section panel-section-meta">
				<div class="meta-row">
					<span class="meta-key">Alert ID</span>
					<span class="meta-val mono">{alert._id}</span>
				</div>
				{#if alert.alert?.signature_id}
					<div class="meta-row">
						<span class="meta-key">Signature ID</span>
						<span class="meta-val mono">{alert.alert.signature_id}</span>
					</div>
				{/if}
				<div class="meta-row">
					<span class="meta-key">Index</span>
					<span class="meta-val mono">{alert._index}</span>
				</div>
				<div class="meta-row">
					<span class="meta-key">Status</span>
					<span class="meta-val">
						{#if alert.acknowledged}
							<span class="badge badge-success">Acknowledged</span>
							{#if alert.acknowledged_at}
								<span class="text-muted ack-time">{formatTimestamp(alert.acknowledged_at)}</span>
							{/if}
						{:else}
							<span class="badge badge-warning">Unacknowledged</span>
						{/if}
					</span>
				</div>
			</section>
		</div>

		<!-- Footer -->
		<div class="panel-footer">
			{#if acknowledgeError}
				<p class="acknowledge-error">{acknowledgeError}</p>
			{/if}

			{#if !alert.acknowledged}
				<button
					class="btn btn-primary"
					onclick={handleAcknowledge}
					disabled={acknowledging}
				>
					{#if acknowledging}
						<span class="btn-spinner"></span>
						Acknowledging...
					{:else}
						<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<polyline points="20 6 9 17 4 12" />
						</svg>
						Acknowledge Alert
					{/if}
				</button>
			{:else}
				<div class="acknowledged-notice">
					<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M22 11.08V12a10 10 0 11-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
					</svg>
					<span>This alert has been acknowledged</span>
				</div>
			{/if}
		</div>
	{/if}
</aside>

<style>
	/* ----- Backdrop ----- */
	.panel-backdrop {
		position: fixed;
		inset: 0;
		z-index: 998;
		background-color: var(--bg-overlay);
		border: none;
		cursor: pointer;
		animation: backdropFadeIn 200ms ease-out;
	}

	@keyframes backdropFadeIn {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	/* ----- Panel ----- */
	.alert-detail-panel {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: 480px;
		max-width: 100vw;
		z-index: 999;
		background-color: var(--bg-primary);
		border-left: 1px solid var(--border-default);
		display: flex;
		flex-direction: column;
		transform: translateX(100%);
		transition: transform var(--transition-normal);
		box-shadow: var(--shadow-lg);
	}

	.alert-detail-panel.open {
		transform: translateX(0);
	}

	/* ----- Header ----- */
	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-default);
		background-color: var(--bg-secondary);
		flex-shrink: 0;
	}

	.panel-header-left {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.panel-close-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		color: var(--text-secondary);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.panel-close-btn:hover {
		background-color: var(--bg-tertiary);
		color: var(--text-primary);
	}

	/* ----- Body ----- */
	.panel-body {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Sections */
	.panel-section {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.section-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.section-body {
		font-size: var(--text-sm);
		color: var(--text-primary);
		line-height: var(--leading-relaxed);
	}

	.alert-signature {
		font-size: var(--text-lg);
		font-weight: 700;
		color: var(--text-primary);
		line-height: var(--leading-tight);
	}

	.alert-timestamp {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* Flow visualization */
	.flow-visualization {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-md);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		flex-wrap: wrap;
		justify-content: center;
	}

	.flow-endpoint {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		min-width: 0;
	}

	.flow-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 600;
	}

	.flow-ip {
		font-size: var(--text-sm);
		color: var(--accent);
		word-break: break-all;
		text-align: center;
	}

	.flow-port {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.flow-arrow {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		color: var(--text-muted);
		flex-shrink: 0;
	}

	.flow-proto-badge {
		font-size: 10px;
		padding: 1px 6px;
	}

	/* Device links */
	.device-links {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.device-links .btn {
		justify-content: flex-start;
		text-align: left;
	}

	/* Metadata */
	.panel-section-meta {
		gap: var(--space-xs);
	}

	.meta-row {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		font-size: var(--text-sm);
		padding: var(--space-xs) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.meta-row:last-child {
		border-bottom: none;
	}

	.meta-key {
		flex-shrink: 0;
		width: 100px;
		font-weight: 600;
		color: var(--text-muted);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.03em;
		padding-top: 2px;
	}

	.meta-val {
		flex: 1;
		color: var(--text-primary);
		word-break: break-all;
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.ack-time {
		font-size: var(--text-xs);
	}

	/* ----- Footer ----- */
	.panel-footer {
		padding: var(--space-md) var(--space-lg);
		border-top: 1px solid var(--border-default);
		background-color: var(--bg-secondary);
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.panel-footer .btn {
		width: 100%;
	}

	.acknowledge-error {
		font-size: var(--text-sm);
		color: var(--danger);
	}

	.acknowledged-notice {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		font-size: var(--text-sm);
		color: var(--success);
		justify-content: center;
		padding: var(--space-sm);
	}

	.btn-spinner {
		display: inline-block;
		width: 14px;
		height: 14px;
		border: 2px solid rgba(255, 255, 255, 0.3);
		border-top-color: #fff;
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* Responsive */
	@media (max-width: 640px) {
		.alert-detail-panel {
			width: 100vw;
		}

		.flow-visualization {
			flex-direction: column;
		}

		.flow-arrow {
			transform: rotate(90deg);
		}
	}
</style>
