<script lang="ts">
	/** Subnet Calculator — Pure frontend, no API calls. */

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function ipToInt(ip: string): number {
		const parts = ip.split('.').map(Number);
		if (parts.length !== 4 || parts.some((p) => isNaN(p) || p < 0 || p > 255)) return -1;
		return ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0;
	}

	function intToIp(int: number): string {
		return [
			(int >>> 24) & 255,
			(int >>> 16) & 255,
			(int >>> 8) & 255,
			int & 255,
		].join('.');
	}

	interface SubnetResult {
		networkAddress: string;
		broadcastAddress: string;
		firstUsable: string;
		lastUsable: string;
		totalHosts: number;
		usableHosts: number;
		netmask: string;
		wildcardMask: string;
		cidr: number;
	}

	function calculateSubnet(ip: string, prefix: number): SubnetResult | null {
		const ipInt = ipToInt(ip);
		if (ipInt === -1 || prefix < 0 || prefix > 32) return null;

		const mask = prefix === 0 ? 0 : (~0 << (32 - prefix)) >>> 0;
		const wildcard = (~mask) >>> 0;
		const network = (ipInt & mask) >>> 0;
		const broadcast = (network | wildcard) >>> 0;
		const totalHosts = Math.pow(2, 32 - prefix);
		const usableHosts = prefix >= 31 ? (prefix === 32 ? 1 : 2) : totalHosts - 2;
		const firstUsable = prefix >= 31 ? network : (network + 1) >>> 0;
		const lastUsable = prefix >= 31 ? broadcast : (broadcast - 1) >>> 0;

		return {
			networkAddress: intToIp(network),
			broadcastAddress: intToIp(broadcast),
			firstUsable: intToIp(firstUsable),
			lastUsable: intToIp(lastUsable),
			totalHosts,
			usableHosts,
			netmask: intToIp(mask),
			wildcardMask: intToIp(wildcard),
			cidr: prefix,
		};
	}

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let ipInput = $state('192.168.1.0');
	let prefixInput = $state(24);

	let result = $derived.by(() => {
		const ip = ipInput.trim();
		if (!ip) return null;

		// Support combined notation like "192.168.1.0/24"
		if (ip.includes('/')) {
			const [ipPart, prefixPart] = ip.split('/');
			const prefix = parseInt(prefixPart, 10);
			if (isNaN(prefix)) return null;
			return calculateSubnet(ipPart, prefix);
		}

		return calculateSubnet(ip, prefixInput);
	});

	const prefixOptions = Array.from({ length: 33 }, (_, i) => i);

	interface ResultField {
		label: string;
		value: string;
		mono?: boolean;
	}

	let fields = $derived<ResultField[]>(
		result
			? [
					{ label: 'Network Address', value: result.networkAddress, mono: true },
					{ label: 'Broadcast Address', value: result.broadcastAddress, mono: true },
					{ label: 'First Usable IP', value: result.firstUsable, mono: true },
					{ label: 'Last Usable IP', value: result.lastUsable, mono: true },
					{ label: 'Total Hosts', value: result.totalHosts.toLocaleString() },
					{ label: 'Usable Hosts', value: result.usableHosts.toLocaleString() },
					{ label: 'Netmask', value: result.netmask, mono: true },
					{ label: 'Wildcard Mask', value: result.wildcardMask, mono: true },
				]
			: []
	);
</script>

<svelte:head>
	<title>Subnet Calculator | NetTap</title>
</svelte:head>

<div class="subnet-page">
	<!-- Back nav -->
	<div class="back-nav">
		<a href="/tools" class="back-link">
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
			</svg>
			Back to Tools
		</a>
	</div>

	<!-- Page header -->
	<div class="page-header">
		<div class="header-left">
			<h1>Subnet Calculator</h1>
			<p class="text-muted">Calculate CIDR ranges, netmasks, broadcast addresses, and usable host counts</p>
		</div>
		<span class="header-badge">Client-side</span>
	</div>

	<!-- Input card -->
	<div class="input-card">
		<div class="input-row">
			<div class="input-group">
				<span class="input-label">IP Address</span>
				<input
					class="input-field"
					type="text"
					placeholder="192.168.1.0 or 192.168.1.0/24"
					bind:value={ipInput}
				/>
			</div>
			<div class="input-group prefix-group">
				<span class="input-label">CIDR Prefix</span>
				<select class="input-field" bind:value={prefixInput}>
					{#each prefixOptions as p}
						<option value={p}>/{p}</option>
					{/each}
				</select>
			</div>
		</div>
	</div>

	<!-- Results -->
	{#if result}
		<div class="result-card">
			<div class="result-header">
				<span class="mono result-cidr">{result.networkAddress}/{result.cidr}</span>
			</div>
			<div class="result-grid">
				{#each fields as field}
					<div class="result-field">
						<span class="field-label">{field.label}</span>
						<span class="field-value" class:mono={field.mono}>{field.value}</span>
					</div>
				{/each}
			</div>
		</div>
	{:else if ipInput.trim()}
		<div class="error-banner">
			Invalid IP address. Enter a valid IPv4 address (e.g. 192.168.1.0).
		</div>
	{/if}
</div>

<style>
	.subnet-page {
		max-width: 800px;
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Back nav */
	.back-nav {
		display: flex;
	}

	.back-link {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 6px 14px;
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		color: var(--text-secondary);
		font-size: var(--text-sm);
		font-weight: 500;
		text-decoration: none;
		transition: all var(--transition-fast);
	}

	.back-link:hover {
		background: var(--bg-tertiary);
		color: var(--text-primary);
		border-color: var(--border-default);
		text-decoration: none;
	}

	/* Page header */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.header-left h1 {
		font-size: var(--text-3xl);
		font-weight: 700;
		letter-spacing: -0.02em;
		margin-bottom: var(--space-xs);
	}

	.header-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 5px 12px;
		background: var(--cyan-dim);
		border: 1px solid rgba(0, 212, 255, 0.2);
		border-radius: 20px;
		color: var(--cyan);
		font-size: var(--text-xs);
		font-weight: 600;
		font-family: var(--font-mono);
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
		gap: 12px;
		align-items: flex-end;
	}

	.input-group {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.prefix-group {
		max-width: 120px;
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
		font-size: var(--text-base);
		font-family: var(--font-mono);
		outline: none;
		transition: border-color var(--transition-fast);
	}

	.input-field::placeholder {
		color: var(--text-dim);
	}

	.input-field:focus {
		border-color: var(--blue);
	}

	select.input-field {
		cursor: pointer;
		appearance: auto;
	}

	/* Result card */
	.result-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.result-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.result-cidr {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--blue);
	}

	.result-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: var(--space-lg);
	}

	.result-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.field-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.field-value {
		font-size: var(--text-lg);
		color: var(--text-primary);
	}

	.mono {
		font-family: var(--font-mono);
	}

	/* Error */
	.error-banner {
		padding: var(--space-md);
		background: var(--amber-dim);
		border: 1px solid rgba(255, 171, 0, 0.3);
		border-radius: var(--radius-md);
		color: var(--amber);
		font-size: var(--text-sm);
	}

	@media (max-width: 768px) {
		.input-row {
			flex-direction: column;
		}

		.prefix-group {
			max-width: 100%;
		}

		.result-grid {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
