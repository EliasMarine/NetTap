<script lang="ts">
	/** Tools index: a card grid grouped by category, filtered by the search field. */
	import Icon from '$lib/components/ui/Icon.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import type { IconName } from '$lib/components/ui/icons';

	interface ToolDef {
		name: string;
		description: string;
		href: string;
		category: 'network' | 'analysis' | 'lookup';
		/** Matched by the search, not shown. */
		tags: string[];
		icon: IconName;
	}

	// OLD CODE START — the "online" / "client-side" status was a fixed label, not a check, so the
	// Online badges and the "Backend Online" count read as live health. The design shows each
	// tool as icon, title and one line (PLAN.md §5.6).
	// status: 'online' | 'client-side';
	// let totalTools = tools.length;
	// let onlineTools = tools.filter((t) => t.status === 'online').length;
	// let clientTools = tools.filter((t) => t.status === 'client-side').length;
	// OLD CODE END

	const tools: ToolDef[] = [
		{
			name: 'Ping and traceroute',
			description: 'Check a host answers, measure round-trip time and trace the route to it.',
			href: '/tools/ping',
			category: 'network',
			tags: ['ICMP', 'diagnostics'],
			icon: 'live',
		},
		{
			name: 'Subnet calculator',
			description: 'Work out the range, netmask, broadcast address and host count of any CIDR block.',
			href: '/tools/subnet-calc',
			category: 'network',
			tags: ['CIDR', 'IPv4'],
			icon: 'infra',
		},
		{
			name: 'Port reference',
			description: 'Look up which service normally runs on a well-known port.',
			href: '/tools/port-reference',
			category: 'network',
			tags: ['TCP', 'UDP', 'reference'],
			icon: 'connections',
		},
		// OLD CODE START — NET-188: /tools/tshark redirects to Packet analysis
		// {
		// 	name: 'TShark packet analysis',
		// 	description: 'Inspect saved PCAP files with Wireshark display filters.',
		// 	href: '/tools/tshark',
		// 	category: 'analysis',
		// 	tags: ['PCAP', 'Wireshark', 'deep inspect'],
		// 	icon: 'pcap',
		// },
		// OLD CODE END
		{
			name: 'Packet analysis',
			description: 'See what crossed your network, packet by packet, from the saved captures.',
			href: '/packets',
			category: 'analysis',
			tags: ['PCAP', 'TShark', 'Wireshark', 'deep inspect'],
			icon: 'filter',
		},
		{
			name: 'CyberChef',
			description: 'Encode, decode, decompress and analyse data with ready-made recipes.',
			href: '/tools/cyberchef',
			category: 'analysis',
			tags: ['encode', 'decode', 'recipes'],
			icon: 'tools',
		},
		{
			name: 'Base64 and hex converter',
			description: 'Encode and decode Base64, hex and URL text. Nothing leaves your browser.',
			href: '/tools/base64',
			category: 'analysis',
			tags: ['base64', 'hex', 'URL'],
			icon: 'logs',
		},
		{
			name: 'DNS reconnaissance',
			description: 'List every DNS record a domain publishes: A, AAAA, MX, NS, TXT, SOA and CNAME.',
			href: '/tools/dns-recon',
			category: 'lookup',
			tags: ['dig', 'records', 'enumeration'],
			icon: 'dns',
		},
		{
			name: 'WHOIS lookup',
			description: 'See who an IP address is registered to: owner, ASN and CIDR range.',
			href: '/lookup/whois',
			category: 'lookup',
			tags: ['registration', 'ASN'],
			icon: 'search',
		},
		{
			name: 'Reverse DNS lookup',
			description: 'Turn an IP address into its host name and check the name points back.',
			href: '/lookup/dns',
			category: 'lookup',
			tags: ['PTR', 'hostname'],
			icon: 'dns',
		},
		{
			name: 'MAC vendor lookup',
			description: 'Name the maker of a device from its MAC address. Works offline.',
			href: '/tools/mac-lookup',
			category: 'lookup',
			tags: ['OUI', 'vendor', 'offline'],
			icon: 'devices',
		},
		{
			name: 'SSL certificate viewer',
			description: 'Read the TLS certificate a host presents: issuer, validity, names and fingerprint.',
			href: '/tools/ssl-cert',
			category: 'lookup',
			tags: ['TLS', 'x509', 'chain'],
			icon: 'certs',
		},
	];

	const categories = [
		{ key: 'network', label: 'Network' },
		{ key: 'analysis', label: 'Analysis' },
		{ key: 'lookup', label: 'Lookup' },
	] as const;

	let search = $state('');

	let filteredTools = $derived(
		search.trim()
			? tools.filter(
					(t) =>
						t.name.toLowerCase().includes(search.toLowerCase()) ||
						t.tags.some((tag) => tag.toLowerCase().includes(search.toLowerCase()))
				)
			: tools
	);
</script>

<svelte:head>
	<title>Tools | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Network tools</h1>
		<p class="page-sub">Diagnostics, analysis and lookups that run on your NetTap, with no cloud service.</p>
	</div>
	<div class="head-actions">
		<SearchField id="tools-search" label="Search tools" placeholder="Search tools: ping, certificate, decode…" size="toolbar" bind:value={search} />
	</div>
</div>

{#each categories as category (category.key)}
	{@const list = filteredTools.filter((t) => t.category === category.key)}
	{#if list.length > 0}
		<section class="stack" aria-labelledby="cat-{category.key}">
			<h2 class="eyebrow" id="cat-{category.key}">{category.label} · {list.length} {list.length === 1 ? 'tool' : 'tools'}</h2>
			<div class="grid">
				{#each list as tool (tool.href)}
					<a class="card tool c-4" href={tool.href}>
						<span class="tile"><Icon name={tool.icon} /></span>
						<span class="tool-text">
							<span class="card-title">{tool.name}</span>
							<span class="tool-desc">{tool.description}</span>
						</span>
					</a>
				{/each}
			</div>
		</section>
	{/if}
{/each}

{#if filteredTools.length === 0}
	<article class="card">
		<div class="state">
			<span class="state-ic"><Icon name="search" /></span>
			<h2 class="card-title">No tools match "{search}"</h2>
			<p>Try a shorter word, such as ping, DNS or decode.</p>
		</div>
	</article>
{/if}

<style>
	/* Layout glue: a whole card is one link, laid out as tile beside title and description */
	.tool { display: flex; gap: var(--sp-3); align-items: flex-start; color: var(--text-1); text-decoration: none; transition: border-color var(--dur-fast); }
	.tool:hover { border-color: var(--line-strong); }
	.tool .tile { color: var(--accent); }
	.tool-text { display: flex; flex-direction: column; gap: var(--sp-1); min-width: 0; }
	.tool-desc { font-size: var(--text-sm); color: var(--text-2); }
</style>
