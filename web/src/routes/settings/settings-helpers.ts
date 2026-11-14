/**
 * The Settings page's sections (NET-273): four groups of tabs, each with a one-line intro.
 * The ids are the `?tab=` values, unchanged from before, so old deep links still open their tab.
 */

export type TabId =
	| 'notifications'
	| 'suricata-rules'
	| 'retention'
	| 'capture'
	| 'backup'
	| 'network'
	| 'integrations'
	| 'api-keys'
	| 'display'
	| 'about';

export interface SettingsTab {
	id: TabId;
	label: string;
	/** One plain-English line at the top of the panel. */
	intro: string;
}

export interface SettingsGroup {
	label: string;
	tabs: readonly SettingsTab[];
}

export const SETTINGS_GROUPS: readonly SettingsGroup[] = [
	{
		label: 'Alerts & detection',
		tabs: [
			{ id: 'notifications', label: 'Notifications', intro: 'Which alerts reach you, the channels that carry them and the rules that pick a channel.' },
			{ id: 'suricata-rules', label: 'Suricata rules', intro: 'The threat detection rules Suricata runs, where they come from and when they refresh.' },
		],
	},
	{
		label: 'Data',
		tabs: [
			{ id: 'retention', label: 'Storage & retention', intro: 'How long NetTap keeps what it records, and how full the disk may get before it prunes.' },
			{ id: 'capture', label: 'Capture', intro: 'Packet capture to disk, and live bandwidth on device pages.' },
			{ id: 'backup', label: 'Backup & restore', intro: 'Export your NetTap configuration to a file, or restore it from one.' },
		],
	},
	{
		label: 'Network',
		tabs: [
			{ id: 'network', label: 'Network', intro: 'Where this network is, and the addresses left out of device views.' },
			{ id: 'integrations', label: 'Integrations', intro: 'Device names, models and networks from your UniFi controller.' },
			{ id: 'api-keys', label: 'API keys', intro: 'Credentials for GeoIP lookups and the email server, kept on this NetTap.' },
		],
	},
	{
		label: 'General',
		tabs: [
			{ id: 'display', label: 'Display', intro: 'The theme, the time range pages open on and the Live map, saved in this browser.' },
			{ id: 'about', label: 'About', intro: 'The NetTap version and uptime of this appliance.' },
		],
	},
];

/** Every tab in menu order, with its group's label. */
export const SETTINGS_TABS: readonly (SettingsTab & { group: string })[] = SETTINGS_GROUPS.flatMap((g) =>
	g.tabs.map((t) => ({ ...t, group: g.label })),
);

const DEFAULT_TAB: TabId = 'notifications';

/** The tab a URL asks for (`?tab=`); a missing or unknown one opens Notifications. */
export function tabFrom(url: URL): TabId {
	const wanted = url.searchParams.get('tab');
	return SETTINGS_TABS.find((t) => t.id === wanted)?.id ?? DEFAULT_TAB;
}
