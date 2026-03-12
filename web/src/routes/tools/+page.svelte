<script lang="ts">
	/** Tools Index — Card grid grouped by category. */

	// ---------------------------------------------------------------------------
	// Tool definitions
	// ---------------------------------------------------------------------------

	interface ToolDef {
		name: string;
		description: string;
		href: string;
		category: 'network' | 'analysis' | 'lookup';
		status: 'online' | 'client-side';
		tags: string[];
		icon: string;
	}

	const tools: ToolDef[] = [
		// Network
		{
			name: 'Ping & Traceroute',
			description: 'Test network reachability, measure RTT latency, and trace the route packets take to any destination.',
			href: '/tools/ping',
			category: 'network',
			status: 'online',
			tags: ['ICMP', 'diagnostics'],
			icon: 'activity',
		},
		{
			name: 'Subnet Calculator',
			description: 'Calculate CIDR ranges, netmasks, broadcast addresses, and usable host counts from any IP/prefix.',
			href: '/tools/subnet-calc',
			category: 'network',
			status: 'client-side',
			tags: ['CIDR', 'IPv4'],
			icon: 'grid',
		},
		{
			name: 'Port Reference',
			description: 'Searchable table of well-known ports, services, and protocols. Quickly identify what\'s running on any port.',
			href: '/tools/port-reference',
			category: 'network',
			status: 'client-side',
			tags: ['TCP', 'UDP', 'reference'],
			icon: 'inbox',
		},
		// Analysis
		{
			name: 'TShark Packet Analysis',
			description: 'Deep packet inspection with Wireshark display filters. Analyze PCAPs, extract fields, and explore protocol layers.',
			href: '/tools/tshark',
			category: 'analysis',
			status: 'online',
			tags: ['PCAP', 'Wireshark', 'deep inspect'],
			icon: 'zap',
		},
		{
			name: 'CyberChef',
			description: 'Data encoding, decoding, compression, and analysis. The cyber Swiss Army knife for security analysts.',
			href: '/tools/cyberchef',
			category: 'analysis',
			status: 'online',
			tags: ['encode', 'decode', 'recipes'],
			icon: 'code',
		},
		{
			name: 'Base64 / Hex Converter',
			description: 'Quick encode and decode operations: Base64, hexadecimal, and URL encoding. No data leaves your browser.',
			href: '/tools/base64',
			category: 'analysis',
			status: 'client-side',
			tags: ['base64', 'hex', 'URL'],
			icon: 'terminal',
		},
		// Lookup
		{
			name: 'DNS Reconnaissance',
			description: 'Enumerate all DNS records for any domain: A, AAAA, MX, NS, TXT, SOA, CNAME. Map domain infrastructure.',
			href: '/tools/dns-recon',
			category: 'lookup',
			status: 'online',
			tags: ['dig', 'records', 'enumeration'],
			icon: 'globe',
		},
		{
			name: 'WHOIS Lookup',
			description: 'Query registration data for any IP address: owner, ASN, CIDR range, registrar, and contact information.',
			href: '/lookup/whois',
			category: 'lookup',
			status: 'online',
			tags: ['registration', 'ASN'],
			icon: 'clipboard',
		},
		{
			name: 'Reverse DNS Lookup',
			description: 'Resolve IP addresses to hostnames and perform forward verification. Identify what\'s behind any IP.',
			href: '/lookup/dns',
			category: 'lookup',
			status: 'online',
			tags: ['PTR', 'hostname'],
			icon: 'globe-alt',
		},
		{
			name: 'MAC Vendor Lookup',
			description: 'Identify device manufacturers from MAC addresses using the IEEE OUI database. Works offline.',
			href: '/tools/mac-lookup',
			category: 'lookup',
			status: 'online',
			tags: ['OUI', 'vendor', 'offline'],
			icon: 'credit-card',
		},
		{
			name: 'SSL Certificate Viewer',
			description: 'Inspect TLS certificate chains: subject, issuer, validity, SANs, and fingerprints for any host.',
			href: '/tools/ssl-cert',
			category: 'lookup',
			status: 'online',
			tags: ['TLS', 'x509', 'chain'],
			icon: 'lock',
		},
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

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

	let networkTools = $derived(filteredTools.filter((t) => t.category === 'network'));
	let analysisTools = $derived(filteredTools.filter((t) => t.category === 'analysis'));
	let lookupTools = $derived(filteredTools.filter((t) => t.category === 'lookup'));

	let totalTools = tools.length;
	let onlineTools = tools.filter((t) => t.status === 'online').length;
	let clientTools = tools.filter((t) => t.status === 'client-side').length;
</script>

<svelte:head>
	<title>Tools | NetTap</title>
</svelte:head>

<div class="tools-page">
	<!-- Page header -->
	<div class="page-header">
		<h1>Network Tools</h1>
		<p class="text-muted">Analysis, diagnostics, and lookup utilities running directly on your NetTap appliance. No cloud dependencies.</p>
	</div>

	<!-- Stats bar -->
	<div class="stats-bar">
		<div class="stat-item">
			<span class="stat-value">{totalTools}</span>
			<span class="stat-label">Tools Available</span>
		</div>
		<div class="stat-item">
			<span class="stat-value stat-online">{onlineTools}</span>
			<span class="stat-label">Backend Online</span>
		</div>
		<div class="stat-item">
			<span class="stat-value stat-client">{clientTools}</span>
			<span class="stat-label">Frontend-Only</span>
		</div>
	</div>

	<!-- Search -->
	<div class="tools-search">
		<svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
			<circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
		</svg>
		<input
			type="text"
			placeholder="Search tools... (e.g. ping, certificate, decode)"
			bind:value={search}
		/>
	</div>

	<!-- Network Category -->
	{#if networkTools.length > 0}
		<div class="tool-category">
			<div class="category-header">
				<div class="category-icon network">
					<svg viewBox="0 0 24 24" stroke="currentColor"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>
				</div>
				<span class="category-label">Network</span>
				<span class="category-count">{networkTools.length} tools</span>
			</div>
			<div class="tool-grid">
				{#each networkTools as tool}
					<a class="tool-card network" href={tool.href}>
						<div class="card-top">
							<div class="card-icon network">
								{#if tool.icon === 'activity'}
									<svg viewBox="0 0 24 24" stroke="currentColor"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>
								{:else if tool.icon === 'grid'}
									<svg viewBox="0 0 24 24" stroke="currentColor"><rect x="2" y="2" width="20" height="20" rx="5" /><line x1="2" y1="12" x2="22" y2="12" /><line x1="12" y1="2" x2="12" y2="22" /></svg>
								{:else}
									<svg viewBox="0 0 24 24" stroke="currentColor"><rect x="2" y="7" width="20" height="15" rx="2" /><polyline points="17 2 12 7 7 2" /></svg>
								{/if}
							</div>
							{#if tool.status === 'online'}
								<span class="status-badge available"><span class="dot"></span> Online</span>
							{:else}
								<span class="status-badge frontend">Client-side</span>
							{/if}
						</div>
						<div class="card-name">{tool.name}</div>
						<div class="card-desc">{tool.description}</div>
						<div class="card-tags">
							{#each tool.tags as tag}
								<span class="tag">{tag}</span>
							{/each}
						</div>
					</a>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Analysis Category -->
	{#if analysisTools.length > 0}
		<div class="tool-category">
			<div class="category-header">
				<div class="category-icon analysis">
					<svg viewBox="0 0 24 24" stroke="currentColor"><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg>
				</div>
				<span class="category-label">Analysis</span>
				<span class="category-count">{analysisTools.length} tools</span>
			</div>
			<div class="tool-grid">
				{#each analysisTools as tool}
					<a class="tool-card analysis" href={tool.href}>
						<div class="card-top">
							<div class="card-icon analysis">
								{#if tool.icon === 'zap'}
									<svg viewBox="0 0 24 24" stroke="currentColor"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" /></svg>
								{:else if tool.icon === 'code'}
									<svg viewBox="0 0 24 24" stroke="currentColor"><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg>
								{:else}
									<svg viewBox="0 0 24 24" stroke="currentColor"><polyline points="4 17 10 11 4 5" /><line x1="12" y1="19" x2="20" y2="19" /></svg>
								{/if}
							</div>
							{#if tool.status === 'online'}
								<span class="status-badge available"><span class="dot"></span> Online</span>
							{:else}
								<span class="status-badge frontend">Client-side</span>
							{/if}
						</div>
						<div class="card-name">{tool.name}</div>
						<div class="card-desc">{tool.description}</div>
						<div class="card-tags">
							{#each tool.tags as tag}
								<span class="tag">{tag}</span>
							{/each}
						</div>
					</a>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Lookup Category -->
	{#if lookupTools.length > 0}
		<div class="tool-category">
			<div class="category-header">
				<div class="category-icon lookup">
					<svg viewBox="0 0 24 24" stroke="currentColor"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
				</div>
				<span class="category-label">Lookup</span>
				<span class="category-count">{lookupTools.length} tools</span>
			</div>
			<div class="tool-grid">
				{#each lookupTools as tool}
					<a class="tool-card lookup" href={tool.href}>
						<div class="card-top">
							<div class="card-icon lookup">
								{#if tool.icon === 'globe' || tool.icon === 'globe-alt'}
									<svg viewBox="0 0 24 24" stroke="currentColor"><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" /></svg>
								{:else if tool.icon === 'clipboard'}
									<svg viewBox="0 0 24 24" stroke="currentColor"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" /><path d="M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
								{:else if tool.icon === 'credit-card'}
									<svg viewBox="0 0 24 24" stroke="currentColor"><rect x="1" y="4" width="22" height="16" rx="2" /><line x1="1" y1="10" x2="23" y2="10" /></svg>
								{:else}
									<svg viewBox="0 0 24 24" stroke="currentColor"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" /></svg>
								{/if}
							</div>
							{#if tool.status === 'online'}
								<span class="status-badge available"><span class="dot"></span> Online</span>
							{:else}
								<span class="status-badge frontend">Client-side</span>
							{/if}
						</div>
						<div class="card-name">{tool.name}</div>
						<div class="card-desc">{tool.description}</div>
						<div class="card-tags">
							{#each tool.tags as tag}
								<span class="tag">{tag}</span>
							{/each}
						</div>
					</a>
				{/each}
			</div>
		</div>
	{/if}

	{#if filteredTools.length === 0}
		<div class="empty-state">
			<p class="text-muted">No tools match "{search}"</p>
		</div>
	{/if}
</div>

<style>
	.tools-page {
		max-width: 1200px;
	}

	/* Page header */
	.page-header {
		margin-bottom: var(--space-xl);
	}

	.page-header h1 {
		font-size: var(--text-3xl);
		font-weight: 700;
		letter-spacing: -0.02em;
		margin-bottom: var(--space-xs);
	}

	/* Stats bar */
	.stats-bar {
		display: flex;
		gap: var(--space-lg);
		margin-bottom: var(--space-xl);
		padding: var(--space-md) var(--space-lg);
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
	}

	.stat-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.stat-value {
		font-family: var(--font-mono);
		font-size: var(--text-2xl);
		font-weight: 600;
		color: var(--cyan);
	}

	.stat-online {
		color: var(--green);
	}

	.stat-client {
		color: var(--purple);
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 600;
	}

	/* Search */
	.tools-search {
		margin-bottom: var(--space-xl);
		position: relative;
	}

	.tools-search input {
		width: 100%;
		max-width: 420px;
		padding: 10px 14px 10px 38px;
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		color: var(--text-primary);
		font-size: var(--text-base);
		font-family: var(--font-sans);
		outline: none;
		transition: border-color var(--transition-fast);
	}

	.tools-search input::placeholder {
		color: var(--text-muted);
	}

	.tools-search input:focus {
		border-color: var(--cyan);
	}

	.search-icon {
		position: absolute;
		left: 12px;
		top: 50%;
		transform: translateY(-50%);
		width: 16px;
		height: 16px;
		color: var(--text-muted);
	}

	/* Category sections */
	.tool-category {
		margin-bottom: var(--space-xl);
	}

	.category-header {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: var(--space-md);
		padding-bottom: var(--space-sm);
		border-bottom: 1px solid var(--border-dim);
	}

	.category-icon {
		width: 28px;
		height: 28px;
		border-radius: 6px;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.category-icon :global(svg) {
		width: 16px;
		height: 16px;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
		fill: none;
	}

	.category-icon.network {
		background: var(--blue-dim);
		color: var(--blue);
	}

	.category-icon.analysis {
		background: var(--purple-dim);
		color: var(--purple);
	}

	.category-icon.lookup {
		background: var(--teal-dim);
		color: var(--teal);
	}

	.category-label {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-secondary);
	}

	.category-count {
		font-size: var(--text-xs);
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	/* Tool card grid */
	.tool-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 14px;
	}

	/* Tool cards */
	.tool-card {
		position: relative;
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
		cursor: pointer;
		transition: all 200ms ease;
		text-decoration: none;
		color: inherit;
		display: flex;
		flex-direction: column;
		gap: 10px;
		overflow: hidden;
	}

	.tool-card::before {
		content: '';
		position: absolute;
		left: 0;
		top: 12px;
		bottom: 12px;
		width: 3px;
		border-radius: 0 2px 2px 0;
	}

	.tool-card.network::before {
		background: var(--blue);
	}

	.tool-card.analysis::before {
		background: var(--purple);
	}

	.tool-card.lookup::before {
		background: var(--teal);
	}

	.tool-card:hover {
		border-color: var(--border-bright);
		background: var(--bg-tertiary);
		transform: translateY(-2px);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
		text-decoration: none;
		color: inherit;
	}

	.tool-card.network:hover {
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(68, 138, 255, 0.15);
	}

	.tool-card.analysis:hover {
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(179, 136, 255, 0.15);
	}

	.tool-card.lookup:hover {
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(29, 233, 182, 0.15);
	}

	/* Card header row */
	.card-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.card-icon {
		width: 36px;
		height: 36px;
		border-radius: 8px;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.card-icon :global(svg) {
		width: 20px;
		height: 20px;
		stroke-width: 1.8;
		stroke-linecap: round;
		stroke-linejoin: round;
		fill: none;
	}

	.card-icon.network {
		background: var(--blue-dim);
		color: var(--blue);
	}

	.card-icon.analysis {
		background: var(--purple-dim);
		color: var(--purple);
	}

	.card-icon.lookup {
		background: var(--teal-dim);
		color: var(--teal);
	}

	/* Status badge */
	.status-badge {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 8px;
		border-radius: 20px;
		font-size: var(--text-xs);
		font-weight: 600;
		font-family: var(--font-mono);
		letter-spacing: 0.02em;
	}

	.status-badge.available {
		background: var(--green-dim);
		color: var(--green);
	}

	.status-badge.available .dot {
		width: 5px;
		height: 5px;
		background: var(--green);
		border-radius: 50%;
		box-shadow: 0 0 6px var(--green);
		animation: pulse-dot 2s ease-in-out infinite;
	}

	.status-badge.frontend {
		background: var(--cyan-dim);
		color: var(--cyan);
	}

	@keyframes pulse-dot {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	/* Card content */
	.card-name {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
		letter-spacing: -0.01em;
	}

	.card-desc {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		line-height: 1.45;
	}

	/* Card tags */
	.card-tags {
		display: flex;
		gap: 6px;
		margin-top: auto;
		flex-wrap: wrap;
	}

	.tag {
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		font-weight: 500;
		background: var(--bg-elevated);
		color: var(--text-muted);
		border: 1px solid var(--border-dim);
	}

	/* Empty state */
	.empty-state {
		text-align: center;
		padding: var(--space-3xl);
	}

	/* Responsive */
	@media (max-width: 768px) {
		.tool-grid {
			grid-template-columns: 1fr;
		}

		.stats-bar {
			flex-wrap: wrap;
			gap: var(--space-md);
		}
	}
</style>
