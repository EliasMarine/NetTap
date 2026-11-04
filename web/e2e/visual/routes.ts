/**
 * Every page under src/routes (find src/routes -name +page.svelte), with the heading
 * that proves the page itself rendered, looked up inside <main> so the shell can't pass for it.
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
	{ path: '/', marker: 'Network overview' },
	{ path: '/alerts', marker: 'Alerts' },
	{ path: '/alerts/malware', marker: /malware/i },
	{ path: '/bandwidth', marker: 'Bandwidth' },
	{ path: '/certificates', marker: 'Certificates' },
	{ path: '/changelog', marker: 'Changelog' },
	{ path: '/compliance', marker: 'Security Posture' },
	{ path: '/connections', marker: 'Connections' },
	{ path: '/devices', marker: 'Device Inventory' },
	{ path: '/devices/192.168.1.20', marker: '192.168.1.20', errorText: "Couldn't load device 192.168.1.20" },
	// the heading is the device's display name from fixtures/devices.ts
	{ path: '/devices/mac/02:00:5e:10:00:20', marker: 'laptop-01.example.com', errorText: "Couldn't load device 02:00:5e:10:00:20" },
	{ path: '/dns', marker: 'DNS analytics' },
	{ path: '/geoip/198.51.100.23', marker: 'GeoIP lookup' },
	{ path: '/infrastructure', marker: 'Infrastructure' },
	{ path: '/investigations', marker: 'Investigations' },
	{ path: '/iot', marker: 'IoT Trust Score' },
	{ path: '/live', marker: /Live/ },
	{ path: '/logs', marker: 'Log explorer' },
	{ path: '/lookup/dns', marker: 'Reverse DNS lookup' },
	{ path: '/lookup/dns/203.0.113.5', marker: 'DNS lookup' },
	{ path: '/lookup/whois', marker: 'WHOIS lookup' },
	{ path: '/lookup/whois/203.0.113.5', marker: 'WHOIS lookup' },
	{ path: '/pcap', marker: 'PCAP search' },
	{ path: '/settings', marker: 'Settings' },
	{ path: '/settings/backup', marker: 'Backup and restore' },
	{ path: '/settings/notifications', marker: 'Notifications' },
	{ path: '/settings/suricata-rules', marker: 'Suricata rules' },
	{ path: '/system', marker: 'System' },
	{ path: '/system/cyberchef', marker: 'CyberChef' },
	{ path: '/system/updates', marker: 'Software updates' },
	{ path: '/threats', marker: 'Threats' },
	{ path: '/tools', marker: 'Network tools' },
	{ path: '/tools/base64', marker: 'Base64 and hex converter' },
	{ path: '/tools/cyberchef', marker: 'CyberChef' },
	{ path: '/tools/dns-recon', marker: 'DNS reconnaissance' },
	{ path: '/tools/mac-lookup', marker: 'MAC address lookup' },
	{ path: '/tools/ping', marker: 'Ping and traceroute' },
	{ path: '/tools/port-reference', marker: 'Port reference' },
	{ path: '/tools/ssl-cert', marker: 'SSL certificate viewer' },
	{ path: '/tools/subnet-calc', marker: 'Subnet calculator' },
	{ path: '/tools/tshark', marker: 'TShark packet analysis' },
	{ path: '/traffic/streaming', marker: /streaming/i },
];
