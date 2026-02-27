<script lang="ts">
	/**
	 * FilterInput — display-filter input with validation and preset support.
	 *
	 * Props:
	 *   onsubmit  – callback fired when the user submits a filter string
	 *   disabled  – whether the input and buttons are disabled
	 */

	interface Props {
		onsubmit: (filter: string) => void;
		disabled?: boolean;
	}

	let { onsubmit, disabled = false }: Props = $props();

	// ---- State ----
	let filterText = $state('');
	let validationStatus = $state<'idle' | 'checking' | 'valid' | 'invalid'>('idle');
	let validationMessage = $state('');
	let showPresets = $state(false);

	// ---- Common display-filter presets ----
	const presets = [
		{ label: 'HTTP requests', filter: 'http.request' },
		{ label: 'DNS queries', filter: 'dns.qr == 0' },
		{ label: 'TLS handshakes', filter: 'tls.handshake' },
		{ label: 'TCP SYN packets', filter: 'tcp.flags.syn == 1 && tcp.flags.ack == 0' },
		{ label: 'ICMP traffic', filter: 'icmp' },
		{ label: 'ARP traffic', filter: 'arp' },
		{ label: 'TCP retransmissions', filter: 'tcp.analysis.retransmission' },
		{ label: 'SSH traffic', filter: 'ssh' },
		{ label: 'DHCP traffic', filter: 'dhcp' },
		{ label: 'Non-DNS/ARP traffic', filter: '!dns && !arp' },
	];

	// ---- Validation ----
	async function validateFilter() {
		if (!filterText.trim()) {
			validationStatus = 'idle';
			validationMessage = '';
			return;
		}

		validationStatus = 'checking';
		validationMessage = '';

		try {
			// Attempt a dry-run analyze with 0 packets to validate the filter syntax
			const res = await fetch('/api/tshark/analyze', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					pcap_path: '',
					display_filter: filterText.trim(),
					max_packets: 0,
				}),
			});

			const data = await res.json().catch(() => ({}));

			if (res.ok && !data.error) {
				validationStatus = 'valid';
				validationMessage = 'Filter syntax is valid';
			} else {
				validationStatus = 'invalid';
				validationMessage = data.error || 'Invalid filter syntax';
			}
		} catch {
			validationStatus = 'invalid';
			validationMessage = 'Could not validate filter — daemon unreachable';
		}
	}

	// ---- Submission ----
	function handleSubmit() {
		onsubmit(filterText.trim());
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			handleSubmit();
		}
	}

	// ---- Preset selection ----
	function selectPreset(filter: string) {
		filterText = filter;
		showPresets = false;
		validationStatus = 'idle';
		validationMessage = '';
	}

	function togglePresets() {
		showPresets = !showPresets;
	}

	// Close presets when clicking outside
	function handleWindowClick(e: MouseEvent) {
		const target = e.target as HTMLElement;
		if (!target.closest('.presets-wrapper')) {
			showPresets = false;
		}
	}
</script>

<svelte:window onclick={handleWindowClick} />

<div class="filter-input-wrapper">
	<div class="filter-row">
		<div class="input-group">
			<input
				type="text"
				class="input filter-field"
				placeholder="Enter display filter (e.g. http.request, dns, tcp.port == 443)"
				bind:value={filterText}
				onkeydown={handleKeydown}
				{disabled}
			/>

			{#if validationStatus === 'valid'}
				<span class="validation-indicator valid" title="Valid filter">
					<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor">
						<path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z" />
					</svg>
				</span>
			{:else if validationStatus === 'invalid'}
				<span class="validation-indicator invalid" title="Invalid filter">
					<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor">
						<path d="M3.72 3.72a.75.75 0 011.06 0L8 6.94l3.22-3.22a.75.75 0 111.06 1.06L9.06 8l3.22 3.22a.75.75 0 11-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 01-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 010-1.06z" />
					</svg>
				</span>
			{:else if validationStatus === 'checking'}
				<span class="validation-indicator checking" title="Checking...">
					<svg class="spin" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
						<circle cx="8" cy="8" r="6" opacity="0.25" />
						<path d="M14 8a6 6 0 00-6-6" />
					</svg>
				</span>
			{/if}
		</div>

		<button class="btn btn-secondary" onclick={validateFilter} disabled={disabled || !filterText.trim()}>
			Validate
		</button>

		<div class="presets-wrapper">
			<button class="btn btn-secondary" onclick={togglePresets} {disabled}>
				Presets
				<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
					<path d="M4.427 7.427l3.396 3.396a.25.25 0 00.354 0l3.396-3.396A.25.25 0 0011.396 7H4.604a.25.25 0 00-.177.427z" />
				</svg>
			</button>

			{#if showPresets}
				<div class="presets-dropdown">
					{#each presets as preset}
						<button
							class="preset-item"
							onclick={() => selectPreset(preset.filter)}
						>
							<span class="preset-label">{preset.label}</span>
							<code class="preset-filter">{preset.filter}</code>
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<button class="btn btn-primary" onclick={handleSubmit} disabled={disabled || !filterText.trim()}>
			Apply
		</button>
	</div>

	{#if validationMessage}
		<div class="validation-message" class:valid={validationStatus === 'valid'} class:invalid={validationStatus === 'invalid'}>
			{validationMessage}
		</div>
	{/if}
</div>

<style>
	.filter-input-wrapper {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.filter-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.input-group {
		flex: 1;
		position: relative;
		display: flex;
		align-items: center;
	}

	.filter-field {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		padding-right: 36px;
	}

	.validation-indicator {
		position: absolute;
		right: 10px;
		display: flex;
		align-items: center;
		pointer-events: none;
	}

	.validation-indicator.valid {
		color: var(--success);
	}

	.validation-indicator.invalid {
		color: var(--danger);
	}

	.validation-indicator.checking {
		color: var(--accent);
	}

	.spin {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}

	.presets-wrapper {
		position: relative;
	}

	.presets-dropdown {
		position: absolute;
		top: calc(100% + 4px);
		right: 0;
		z-index: 20;
		min-width: 320px;
		max-height: 300px;
		overflow-y: auto;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
		padding: var(--space-xs);
	}

	.preset-item {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 2px;
		width: 100%;
		padding: var(--space-sm) var(--space-md);
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		text-align: left;
		transition: background-color var(--transition-fast);
	}

	.preset-item:hover {
		background-color: var(--bg-tertiary);
	}

	.preset-label {
		font-size: var(--text-sm);
		color: var(--text-primary);
		font-weight: 500;
	}

	.preset-filter {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.validation-message {
		font-size: var(--text-xs);
		padding: var(--space-xs) var(--space-sm);
		border-radius: var(--radius-sm);
	}

	.validation-message.valid {
		color: var(--success);
		background-color: var(--success-muted);
	}

	.validation-message.invalid {
		color: var(--danger);
		background-color: var(--danger-muted);
	}
</style>
