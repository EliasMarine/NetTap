<!--
  DashboardFilters.svelte — Global filter bar for dashboard pages.

  Horizontal bar at the top of pages controlling time range, device filter,
  and protocol filter. Emits a FilterState object via the onchange callback
  when the user clicks Apply.
-->
<script lang="ts" module>
	// ---------------------------------------------------------------------------
	// Exported types
	// ---------------------------------------------------------------------------

	export interface FilterState {
		timeRange: string;
		from: string;
		to: string;
		device: string;
		protocol: string;
	}
</script>

<script lang="ts">
	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		timeRange = '24h',
		device = '',
		protocol = '',
		onchange = (_filters: FilterState) => {},
	}: {
		timeRange?: string;
		device?: string;
		protocol?: string;
		onchange?: (filters: FilterState) => void;
	} = $props();

	// ---------------------------------------------------------------------------
	// Internal state
	// ---------------------------------------------------------------------------

	let selectedRange = $state('24h');
	let deviceFilter = $state('');
	let protocolFilter = $state('');

	// Sync from props on mount
	$effect(() => {
		selectedRange = timeRange;
		deviceFilter = device;
		protocolFilter = protocol;
	});
	let customFrom = $state('');
	let customTo = $state('');

	let isCustom = $derived(selectedRange === 'custom');

	// ---------------------------------------------------------------------------
	// Time range options
	// ---------------------------------------------------------------------------

	const TIME_RANGES = [
		{ value: '1h', label: 'Last 1h' },
		{ value: '6h', label: 'Last 6h' },
		{ value: '24h', label: 'Last 24h' },
		{ value: '7d', label: 'Last 7d' },
		{ value: '30d', label: 'Last 30d' },
		{ value: 'custom', label: 'Custom' },
	];

	const PROTOCOLS = [
		{ value: '', label: 'All Protocols' },
		{ value: 'tcp', label: 'TCP' },
		{ value: 'udp', label: 'UDP' },
		{ value: 'http', label: 'HTTP' },
		{ value: 'https', label: 'HTTPS' },
		{ value: 'dns', label: 'DNS' },
		{ value: 'ssh', label: 'SSH' },
		{ value: 'smtp', label: 'SMTP' },
	];

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	/**
	 * Convert a relative time range string (e.g. '24h', '7d') into ISO 8601
	 * from/to timestamps. Returns { from, to } with 'to' always set to now.
	 */
	export function computeTimeRange(range: string): { from: string; to: string } {
		const now = new Date();
		const to = now.toISOString();

		const match = range.match(/^(\d+)(h|d)$/);
		if (!match) {
			// Fallback: default to last 24h
			const fallback = new Date(now.getTime() - 24 * 60 * 60 * 1000);
			return { from: fallback.toISOString(), to };
		}

		const amount = parseInt(match[1], 10);
		const unit = match[2];
		let msOffset: number;

		if (unit === 'h') {
			msOffset = amount * 60 * 60 * 1000;
		} else {
			// 'd'
			msOffset = amount * 24 * 60 * 60 * 1000;
		}

		const from = new Date(now.getTime() - msOffset);
		return { from: from.toISOString(), to };
	}

	// ---------------------------------------------------------------------------
	// Actions
	// ---------------------------------------------------------------------------

	function handleApply() {
		let from: string;
		let to: string;

		if (isCustom && customFrom && customTo) {
			from = new Date(customFrom).toISOString();
			to = new Date(customTo).toISOString();
		} else {
			const computed = computeTimeRange(selectedRange);
			from = computed.from;
			to = computed.to;
		}

		onchange({
			timeRange: selectedRange,
			from,
			to,
			device: deviceFilter.trim(),
			protocol: protocolFilter,
		});
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleApply();
		}
	}
</script>

<div class="filter-bar" role="toolbar" aria-label="Dashboard filters">
	<!-- Time range -->
	<div class="filter-group">
		<label class="filter-label" for="filter-time-range">Time</label>
		<select
			id="filter-time-range"
			class="input filter-select"
			bind:value={selectedRange}
		>
			{#each TIME_RANGES as opt}
				<option value={opt.value}>{opt.label}</option>
			{/each}
		</select>
	</div>

	<!-- Custom date range (only visible when "Custom" selected) -->
	{#if isCustom}
		<div class="filter-group filter-group-custom">
			<label class="filter-label" for="filter-from">From</label>
			<input
				id="filter-from"
				type="datetime-local"
				class="input filter-datetime"
				bind:value={customFrom}
			/>
		</div>
		<div class="filter-group filter-group-custom">
			<label class="filter-label" for="filter-to">To</label>
			<input
				id="filter-to"
				type="datetime-local"
				class="input filter-datetime"
				bind:value={customTo}
			/>
		</div>
	{/if}

	<!-- Device filter -->
	<div class="filter-group filter-group-device">
		<label class="filter-label" for="filter-device">Device</label>
		<input
			id="filter-device"
			type="text"
			class="input filter-input"
			placeholder="Filter by device IP..."
			bind:value={deviceFilter}
			onkeydown={handleKeydown}
		/>
	</div>

	<!-- Protocol filter -->
	<div class="filter-group">
		<label class="filter-label" for="filter-protocol">Protocol</label>
		<select
			id="filter-protocol"
			class="input filter-select"
			bind:value={protocolFilter}
		>
			{#each PROTOCOLS as opt}
				<option value={opt.value}>{opt.label}</option>
			{/each}
		</select>
	</div>

	<!-- Apply button -->
	<div class="filter-group filter-group-action">
		<button class="btn btn-primary btn-sm" onclick={handleApply}>
			Apply
		</button>
	</div>
</div>

<style>
	.filter-bar {
		display: flex;
		align-items: flex-end;
		gap: var(--space-md);
		flex-wrap: wrap;
		padding: var(--space-sm) var(--space-md);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.filter-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.filter-group-device {
		flex: 1;
		min-width: 160px;
	}

	.filter-group-action {
		align-self: flex-end;
	}

	.filter-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.filter-select {
		min-width: 120px;
		padding: var(--space-xs) var(--space-sm);
		font-size: var(--text-sm);
	}

	.filter-input {
		padding: var(--space-xs) var(--space-sm);
		font-size: var(--text-sm);
	}

	.filter-datetime {
		padding: var(--space-xs) var(--space-sm);
		font-size: var(--text-sm);
		min-width: 180px;
	}

	.filter-group-custom {
		animation: fadeIn 150ms ease-out;
	}

	@keyframes fadeIn {
		from {
			opacity: 0;
			transform: translateY(-4px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	/* Responsive */
	@media (max-width: 768px) {
		.filter-bar {
			flex-direction: column;
			align-items: stretch;
		}

		.filter-group {
			width: 100%;
		}

		.filter-group-device {
			min-width: unset;
		}

		.filter-group-action {
			align-self: stretch;
		}

		.filter-group-action .btn {
			width: 100%;
		}
	}
</style>
