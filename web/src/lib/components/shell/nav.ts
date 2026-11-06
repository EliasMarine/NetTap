// OLD CODE START — NET-160: the owner added Investigations and Security posture (2026-11-06)
// /**
//  * Sidebar navigation (PLAN.md §5.5): the same 17 pages as before, grouped as the
//  * design system's Sidebar shows them. Investigations and Security Posture stay out of
//  * the menu, as before.
//  */
// OLD CODE END
/**
 * Sidebar navigation (PLAN.md §5.5): 19 pages, grouped as the design system's Sidebar shows
 * them. Investigations and Security posture joined in NET-160.
 */
import type { IconName } from '$lib/components/ui/icons';

export interface NavItem {
	href: string;
	label: string;
	icon: IconName;
}

export interface NavGroup {
	label: string;
	items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
	{
		label: 'Overview',
		items: [
			{ href: '/', label: 'Home', icon: 'home' },
			{ href: '/live', label: 'Live Monitor', icon: 'live' },
			{ href: '/bandwidth', label: 'Bandwidth', icon: 'bandwidth' },
		],
	},
	{
		label: 'Investigate',
		items: [
			{ href: '/alerts', label: 'Alerts', icon: 'alerts' },
			{ href: '/threats', label: 'Threats', icon: 'threats' },
			{ href: '/connections', label: 'Connections', icon: 'connections' },
			{ href: '/logs', label: 'Log Explorer', icon: 'logs' },
			{ href: '/dns', label: 'DNS Analytics', icon: 'dns' },
			{ href: '/certificates', label: 'Certificates', icon: 'certs' },
			{ href: '/pcap', label: 'PCAP Search', icon: 'pcap' },
			{ href: '/investigations', label: 'Investigations', icon: 'search' },
		],
	},
	{
		label: 'Devices',
		items: [
			{ href: '/devices', label: 'Devices', icon: 'devices' },
			{ href: '/iot', label: 'IoT & LAN', icon: 'iot' },
			{ href: '/changelog', label: 'Changelog', icon: 'changelog' },
		],
	},
	{
		label: 'System',
		items: [
			{ href: '/infrastructure', label: 'Infrastructure', icon: 'infra' },
			{ href: '/system', label: 'System', icon: 'system' },
			{ href: '/compliance', label: 'Security posture', icon: 'check' },
			{ href: '/tools', label: 'Tools', icon: 'tools' },
			{ href: '/settings', label: 'Settings', icon: 'settings' },
		],
	},
];

/** The link is the current page, or a page under it (/alerts/malware highlights Alerts). */
export function isActive(href: string, path: string): boolean {
	if (href === '/') return path === '/';
	return path === href || path.startsWith(`${href}/`);
}

/** Drill-down pages with no nav item of their own (NET-160) */
const DRILL_TITLES: [string, string][] = [
	['/address', 'Address'],
	['/domain', 'Domain'],
];

/** The name of the current section, for the phone top bar. */
export function pageTitle(path: string): string {
	for (const group of NAV_GROUPS) {
		for (const item of group.items) if (isActive(item.href, path)) return item.label;
	}
	for (const [href, title] of DRILL_TITLES) if (isActive(href, path)) return title;
	return 'NetTap';
}

/** Pages that render without the shell (sign-in and first-run setup), as before. */
export function isBare(path: string): boolean {
	return path.startsWith('/login') || path.startsWith('/setup');
}
