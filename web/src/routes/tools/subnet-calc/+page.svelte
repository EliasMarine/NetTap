<script lang="ts">
	/** Subnet calculator: runs in the browser, no API calls. A form card, then a result card with .facts. */
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { fmt } from '$lib/utils/drilldown';

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
					{ label: 'Network address', value: result.networkAddress, mono: true },
					{ label: 'Broadcast address', value: result.broadcastAddress, mono: true },
					{ label: 'First usable IP', value: result.firstUsable, mono: true },
					{ label: 'Last usable IP', value: result.lastUsable, mono: true },
					{ label: 'Total hosts', value: fmt(result.totalHosts) },
					{ label: 'Usable hosts', value: fmt(result.usableHosts) },
					{ label: 'Netmask', value: result.netmask, mono: true },
					{ label: 'Wildcard mask', value: result.wildcardMask, mono: true },
				]
			: []
	);
</script>

<svelte:head>
	<title>Subnet calculator | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">Subnet calculator</h1>
		<p class="page-sub">CIDR ranges, netmasks, broadcast addresses and usable host counts. Runs in your browser.</p>
	</div>
</div>

<div class="grid">
	<Card title="Network" sub="An IPv4 address and prefix, or both as 192.168.1.0/24" class="c-4">
		<div class="field form-group">
			<label class="label" for="subnet-ip">IP address</label>
			<input id="subnet-ip" class="input mono" type="text" placeholder="192.168.1.0 or 192.168.1.0/24" bind:value={ipInput} />
		</div>
		<div class="field">
			<label class="label" for="subnet-prefix">CIDR prefix</label>
			<select id="subnet-prefix" class="select mono" bind:value={prefixInput}>
				{#each prefixOptions as p}
					<option value={p}>/{p}</option>
				{/each}
			</select>
		</div>
	</Card>

	<Card title="Result" sub="The block the address belongs to" class="c-8">
		{#if result}
			<dl class="facts">
				<dt>CIDR block</dt>
				<dd class="mono">{result.networkAddress}/{result.cidr}</dd>
				{#each fields as field (field.label)}
					<dt>{field.label}</dt>
					<dd class={[field.mono ? 'mono' : 'num']}>{field.value}</dd>
				{/each}
			</dl>
		{:else if ipInput.trim()}
			<p class="notice is-error" role="alert"><Icon name="warn" />Invalid IP address. Enter a valid IPv4 address (e.g. 192.168.1.0).</p>
		{:else}
			<CardState state="empty" icon="infra" title="Enter an IP address" message="Type an IPv4 address to see its network, broadcast address and host range." />
		{/if}
	</Card>
</div>
