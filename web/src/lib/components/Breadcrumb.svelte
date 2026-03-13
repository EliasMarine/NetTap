<script lang="ts">
	import { page } from '$app/stores';

	const ROUTE_MAP: Record<string, { label: string; parent?: string }> = {
		'/': { label: 'Home' },
		'/logs': { label: 'Log Explorer' },
		'/devices': { label: 'Devices' },
		'/alerts': { label: 'Alerts' },
		'/connections': { label: 'Connections' },
		'/live': { label: 'Live Monitor' },
		'/bandwidth': { label: 'Bandwidth' },
		'/dns': { label: 'DNS Analytics' },
		'/iot': { label: 'IoT & LAN' },
		'/changelog': { label: 'Changelog' },
		'/certificates': { label: 'Certificates' },
		'/pcap': { label: 'PCAP Search' },
		'/tools': { label: 'Tools' },
		'/tools/dns-recon': { label: 'DNS Recon', parent: '/tools' },
		'/tools/ping': { label: 'Ping', parent: '/tools' },
		'/tools/traceroute': { label: 'Traceroute', parent: '/tools' },
		'/tools/ssl-cert': { label: 'SSL Cert', parent: '/tools' },
		'/tools/mac-lookup': { label: 'MAC Lookup', parent: '/tools' },
		'/tools/subnet-calc': { label: 'Subnet Calc', parent: '/tools' },
		'/tools/port-reference': { label: 'Port Reference', parent: '/tools' },
		'/tools/base64': { label: 'Base64', parent: '/tools' },
		'/tools/cyberchef': { label: 'CyberChef', parent: '/tools' },
		'/tools/tshark': { label: 'Tshark', parent: '/tools' },
		'/infrastructure': { label: 'Infrastructure' },
		'/settings': { label: 'Settings' },
		'/settings/notifications': { label: 'Notifications', parent: '/settings' },
		'/settings/backup': { label: 'Backup', parent: '/settings' },
		'/settings/suricata-rules': { label: 'Suricata Rules', parent: '/settings' },
		'/traffic': { label: 'Traffic Categories', parent: '/' },
		'/go-live': { label: 'Go Live' },
		'/geoip': { label: 'GeoIP' },
	};

	const CATEGORY_LABELS: Record<string, string> = {
		streaming: 'Streaming', gaming: 'Gaming', social: 'Social Media',
		communication: 'Communication', work: 'Work & Productivity',
		iot: 'IoT & Smart Home', cloud: 'Cloud Services',
		file_transfer: 'File Transfer', dns: 'DNS', email: 'Email',
		web: 'Web Browsing', security: 'Security & VPN',
		shopping: 'Shopping', news: 'News & Media',
		ads: 'Ads & Tracking', updates: 'Updates & Downloads',
		suspicious: 'Suspicious', other: 'Other',
	};

	const HIDDEN_PATHS = ['/', '/login', '/setup'];

	interface Crumb {
		label: string;
		href?: string;
		mono?: boolean;
	}

	function buildTrail(pathname: string): Crumb[] {
		if (HIDDEN_PATHS.includes(pathname)) return [];

		const crumbs: Crumb[] = [{ label: 'Home', href: '/' }];

		// Exact match in route map
		const exact = ROUTE_MAP[pathname];
		if (exact) {
			const chain: { label: string; href: string }[] = [];
			let current: string | undefined = pathname;
			while (current && ROUTE_MAP[current]) {
				const entry: { label: string; parent?: string } = ROUTE_MAP[current];
				chain.unshift({ label: entry.label, href: current });
				current = entry.parent;
			}
			for (const c of chain) {
				if (c.href === '/') continue;
				crumbs.push(c);
			}
			if (crumbs.length > 1) {
				delete crumbs[crumbs.length - 1].href;
			}
			return crumbs;
		}

		// Dynamic: /devices/mac/{mac}
		const macMatch = pathname.match(/^\/devices\/mac\/(.+)$/);
		if (macMatch) {
			crumbs.push({ label: 'Devices', href: '/devices' });
			crumbs.push({ label: decodeURIComponent(macMatch[1]), mono: true });
			return crumbs;
		}

		// Dynamic: /devices/{ip}
		const devMatch = pathname.match(/^\/devices\/(.+)$/);
		if (devMatch) {
			crumbs.push({ label: 'Devices', href: '/devices' });
			crumbs.push({ label: decodeURIComponent(devMatch[1]), mono: true });
			return crumbs;
		}

		// Dynamic: /traffic/{category}
		const catMatch = pathname.match(/^\/traffic\/(.+)$/);
		if (catMatch) {
			const slug = decodeURIComponent(catMatch[1]);
			crumbs.push({ label: 'Traffic Categories', href: '/' });
			crumbs.push({ label: CATEGORY_LABELS[slug] || slug });
			return crumbs;
		}

		// Dynamic: /geoip/{ip}
		const geoMatch = pathname.match(/^\/geoip\/(.+)$/);
		if (geoMatch) {
			crumbs.push({ label: 'GeoIP', href: '/geoip' });
			crumbs.push({ label: decodeURIComponent(geoMatch[1]), mono: true });
			return crumbs;
		}

		// Dynamic: /lookup/dns/{ip} or /lookup/whois/{ip}
		const lookupMatch = pathname.match(/^\/lookup\/(dns|whois)\/(.+)$/);
		if (lookupMatch) {
			crumbs.push({ label: lookupMatch[1].toUpperCase() + ' Lookup' });
			crumbs.push({ label: decodeURIComponent(lookupMatch[2]), mono: true });
			return crumbs;
		}

		// Fallback: path segments
		const segments = pathname.split('/').filter(Boolean);
		for (let i = 0; i < segments.length; i++) {
			const href = '/' + segments.slice(0, i + 1).join('/');
			const isLast = i === segments.length - 1;
			crumbs.push({
				label: decodeURIComponent(segments[i]).replace(/-/g, ' '),
				href: isLast ? undefined : href,
			});
		}
		return crumbs;
	}

	let trail = $derived(buildTrail($page.url.pathname));
</script>

{#if trail.length > 1}
	<nav class="breadcrumb-bar" aria-label="Breadcrumb">
		<ol class="breadcrumb-trail">
			{#each trail as crumb, i}
				{#if i > 0}
					<li class="separator" aria-hidden="true">/</li>
				{/if}
				<li class="crumb" class:current={!crumb.href}>
					{#if crumb.href}
						<a href={crumb.href}>{crumb.label}</a>
					{:else}
						<span class:mono={crumb.mono}>{crumb.label}</span>
					{/if}
				</li>
			{/each}
		</ol>
	</nav>
{/if}

<style>
	.breadcrumb-bar {
		padding: var(--space-xs) var(--space-lg);
	}

	.breadcrumb-trail {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: var(--text-sm);
		font-family: var(--font-sans);
	}

	.separator {
		color: var(--text-dim);
		user-select: none;
	}

	.crumb a {
		color: var(--text-muted);
		text-decoration: none;
		transition: color var(--transition-fast);
	}

	.crumb a:hover {
		color: var(--text-link);
	}

	.crumb.current span {
		color: var(--text-secondary);
	}

	.mono {
		font-family: var(--font-mono);
	}
</style>
