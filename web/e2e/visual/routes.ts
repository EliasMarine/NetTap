/**
 * Every page under src/routes (find src/routes -name +page.svelte), with the heading
 * that proves the page itself rendered. The marker is looked up inside <main>, because
 * the layout's top bar has its own h1 on every page and would pass for any route.
 * Dynamic routes use synthetic ids (RFC 5737 / RFC 1918 addresses, locally administered MACs).
 */
export interface RouteCase {
	path: string;
	/** Heading (any level) inside <main>. */
	marker: string | RegExp;
	/** Visible text inside <main> in `error` mode, for pages whose error state has no heading. */
	errorText?: string | RegExp;
}

export const APP_ROUTES: readonly RouteCase[] = [
	{ path: '/', marker: /^(Network|Device) Overview$/ },
	{ path: '/alerts', marker: 'Alerts' },
	{ path: '/alerts/malware', marker: /malware/i },
	{ path: '/bandwidth', marker: 'Bandwidth' },
	{ path: '/certificates', marker: 'TLS Certificate Inventory' },
	{ path: '/changelog', marker: 'Network Changelog' },
	{ path: '/compliance', marker: 'Security Posture' },
	{ path: '/connections', marker: 'Connections' },
	{ path: '/devices', marker: 'Device Inventory' },
	{ path: '/devices/192.168.1.20', marker: '192.168.1.20', errorText: "Couldn't load device 192.168.1.20" },
	// the heading is the device's display name from fixtures/devices.ts
	{ path: '/devices/mac/02:00:5e:10:00:20', marker: 'laptop-01.example.com', errorText: "Couldn't load device 02:00:5e:10:00:20" },
	{ path: '/dns', marker: 'DNS Analytics' },
	{ path: '/geoip/198.51.100.23', marker: 'GeoIP Lookup' },
	{ path: '/infrastructure', marker: 'Pipeline Operations Center' },
	{ path: '/investigations', marker: 'Investigations' },
	{ path: '/iot', marker: 'IoT Trust Score' },
	{ path: '/live', marker: /Live/ },
	{ path: '/logs', marker: 'Network Activity' },
	{ path: '/lookup/dns', marker: 'Reverse DNS Lookup' },
	{ path: '/lookup/dns/203.0.113.5', marker: 'DNS Lookup' },
	{ path: '/lookup/whois', marker: 'WHOIS Lookup' },
	{ path: '/lookup/whois/203.0.113.5', marker: 'WHOIS Lookup' },
	{ path: '/pcap', marker: 'PCAP Search' },
	{ path: '/settings', marker: 'Settings' },
	{ path: '/settings/backup', marker: 'Backup & Restore' },
	{ path: '/settings/notifications', marker: 'Notification Settings' },
	{ path: '/settings/suricata-rules', marker: 'Suricata IDS Rules' },
	{ path: '/system', marker: 'System' },
	{ path: '/system/cyberchef', marker: 'CyberChef' },
	{ path: '/system/updates', marker: 'Software Updates' },
	{ path: '/threats', marker: 'Threat Intelligence' },
	{ path: '/tools', marker: 'Network Tools' },
	{ path: '/tools/base64', marker: 'Base64 / Hex Converter' },
	{ path: '/tools/cyberchef', marker: 'CyberChef' },
	{ path: '/tools/dns-recon', marker: 'DNS Reconnaissance' },
	{ path: '/tools/mac-lookup', marker: 'MAC Address Lookup' },
	{ path: '/tools/ping', marker: 'Ping & Traceroute' },
	{ path: '/tools/port-reference', marker: 'Port Reference' },
	{ path: '/tools/ssl-cert', marker: 'SSL Certificate Viewer' },
	{ path: '/tools/subnet-calc', marker: 'Subnet Calculator' },
	{ path: '/tools/tshark', marker: 'Packet Analysis' },
	{ path: '/traffic/streaming', marker: /streaming/i },
];
