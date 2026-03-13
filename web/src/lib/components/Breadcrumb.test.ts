import { describe, it, expect } from 'vitest';

// ---------------------------------------------------------------------------
// Reproduce the pure buildTrail logic for unit testing without Svelte runtime.
// The component itself uses $page.url.pathname; here we test the core logic
// that determines what breadcrumbs appear for a given path.
// ---------------------------------------------------------------------------

const ROUTE_MAP: Record<string, { label: string; parent?: string }> = {
	'/': { label: 'Home' },
	'/logs': { label: 'Log Explorer' },
	'/devices': { label: 'Devices' },
	'/alerts': { label: 'Alerts' },
	'/tools': { label: 'Tools' },
	'/tools/dns-recon': { label: 'DNS Recon', parent: '/tools' },
	'/tools/ping': { label: 'Ping', parent: '/tools' },
	'/settings': { label: 'Settings' },
	'/settings/notifications': { label: 'Notifications', parent: '/settings' },
	'/traffic': { label: 'Traffic Categories', parent: '/' },
};

const CATEGORY_LABELS: Record<string, string> = {
	streaming: 'Streaming',
	gaming: 'Gaming',
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
			const entry = ROUTE_MAP[current];
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
		crumbs.push({ label: 'Traffic Categories', href: '/traffic' });
		crumbs.push({ label: CATEGORY_LABELS[slug] || slug });
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Breadcrumb — buildTrail', () => {
	it('returns empty for home page', () => {
		expect(buildTrail('/')).toEqual([]);
	});

	it('returns empty for login', () => {
		expect(buildTrail('/login')).toEqual([]);
	});

	it('returns empty for setup', () => {
		expect(buildTrail('/setup')).toEqual([]);
	});

	it('builds trail for top-level page', () => {
		expect(buildTrail('/logs')).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Log Explorer' },
		]);
	});

	it('builds nested trail for tool subpage', () => {
		expect(buildTrail('/tools/dns-recon')).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Tools', href: '/tools' },
			{ label: 'DNS Recon' },
		]);
	});

	it('builds nested trail for settings subpage', () => {
		expect(buildTrail('/settings/notifications')).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Settings', href: '/settings' },
			{ label: 'Notifications' },
		]);
	});

	it('builds trail for device detail', () => {
		expect(buildTrail('/devices/192.168.1.5')).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Devices', href: '/devices' },
			{ label: '192.168.1.5', mono: true },
		]);
	});

	it('builds trail for traffic category', () => {
		expect(buildTrail('/traffic/streaming')).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Traffic Categories', href: '/traffic' },
			{ label: 'Streaming' },
		]);
	});

	it('uses slug as label for unknown category', () => {
		expect(buildTrail('/traffic/unknown-cat')).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Traffic Categories', href: '/traffic' },
			{ label: 'unknown-cat' },
		]);
	});

	it('last crumb never has href', () => {
		const trail = buildTrail('/tools/ping');
		expect(trail[trail.length - 1].href).toBeUndefined();
	});

	it('first crumb is always Home with href /', () => {
		const trail = buildTrail('/alerts');
		expect(trail[0]).toEqual({ label: 'Home', href: '/' });
	});

	it('builds trail for MAC address device', () => {
		expect(buildTrail('/devices/mac/AA:BB:CC:DD:EE:FF')).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Devices', href: '/devices' },
			{ label: 'AA:BB:CC:DD:EE:FF', mono: true },
		]);
	});

	it('falls back to segment-based trail for unknown paths', () => {
		const trail = buildTrail('/some/unknown/path');
		expect(trail).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'some', href: '/some' },
			{ label: 'unknown', href: '/some/unknown' },
			{ label: 'path' },
		]);
	});
});
