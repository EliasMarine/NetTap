<script lang="ts">
	/**
	 * FilterInput — display-filter input with validation and preset support.
	 *
	 * Props:
	 *   onsubmit  – callback fired when the user submits a filter string
	 *   disabled  – whether the input and buttons are disabled
	 *   onchange  – callback fired on every edit, so a parent's Analyze uses the typed filter
	 */

	import Icon from '$lib/components/ui/Icon.svelte';

	interface Props {
		onsubmit: (filter: string) => void;
		disabled?: boolean;
		value?: string;
		onchange?: (filter: string) => void;
	}

	let { onsubmit, disabled = false, value = '', onchange }: Props = $props();

	// ---- State ----
	let filterText = $state('');

	// Sync filterText when parent value changes (e.g. URL-derived filter)
	$effect(() => {
		if (value && !filterText) {
			filterText = value;
		}
	});
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
			validationMessage = "Couldn't validate the filter: the daemon can't be reached.";
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
		onchange?.(filter);
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
				class="input mono filter-field"
				placeholder="Enter display filter (e.g. http.request, dns, tcp.port == 443)"
				bind:value={filterText}
				oninput={() => onchange?.(filterText.trim())}
				onkeydown={handleKeydown}
				{disabled}
			/>

			{#if validationStatus === 'valid'}
				<span class="validation-indicator valid" title="Valid filter">
					<Icon name="check" />
				</span>
			{:else if validationStatus === 'invalid'}
				<span class="validation-indicator invalid" title="Invalid filter">
					<Icon name="close" />
				</span>
			{:else if validationStatus === 'checking'}
				<span class="validation-indicator checking" title="Checking…">
					<svg class="spin" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
						<circle cx="8" cy="8" r="6" opacity="0.25" />
						<path d="M14 8a6 6 0 00-6-6" />
					</svg>
				</span>
			{/if}
		</div>

		<button class="btn" onclick={validateFilter} disabled={disabled || !filterText.trim()}>
			Validate
		</button>

		<div class="presets-wrapper">
			<button class="btn" onclick={togglePresets} {disabled}>
				Presets
				<Icon name="chevdown" />
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

		<button class="btn primary" onclick={handleSubmit} disabled={disabled || !filterText.trim()}>
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
		gap: var(--sp-1);
	}

	.filter-row {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}

	.input-group {
		flex: 1;
		position: relative;
		display: flex;
		align-items: center;
	}

	.filter-field {
		padding-right: var(--sp-8);
	}

	.validation-indicator {
		position: absolute;
		right: var(--sp-3);
		display: flex;
		align-items: center;
		pointer-events: none;
	}

	.validation-indicator :global(.ic) {
		width: 16px;
		height: 16px;
	}

	.validation-indicator.valid {
		color: var(--ok);
	}

	.validation-indicator.invalid {
		color: var(--sev-critical);
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
		top: calc(100% + var(--sp-1));
		right: 0;
		z-index: 20;
		min-width: 320px;
		max-height: 300px;
		overflow-y: auto;
		background-color: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		box-shadow: var(--shadow-pop);
		padding: var(--sp-1);
	}

	.preset-item {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 2px;
		width: 100%;
		padding: var(--sp-2) var(--sp-3);
		background: none;
		border: none;
		border-radius: var(--r-sm);
		color: var(--text-1);
		cursor: pointer;
		text-align: left;
		transition: background-color var(--dur-fast);
	}

	.preset-item:hover {
		background-color: var(--surface-2);
	}

	.preset-label {
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.preset-filter {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.validation-message {
		font-size: var(--text-xs);
		padding: var(--sp-1) var(--sp-2);
		border-radius: var(--r-sm);
	}

	.validation-message.valid {
		color: var(--ok);
		background-color: color-mix(in srgb, var(--ok) 12%, transparent);
	}

	.validation-message.invalid {
		color: var(--sev-critical);
		background-color: color-mix(in srgb, var(--sev-critical) 12%, transparent);
	}
</style>
