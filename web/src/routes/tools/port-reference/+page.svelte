<script lang="ts">
	/**
	 * Port Reference — A searchable, filterable table of well-known network ports.
	 *
	 * Pure frontend — no API calls. Static data with ~150 common ports.
	 *
	 * A toolbar (search and protocol pills) over a DataTable card: Port, Protocol,
	 * Service, Description. Every column sorts; port ascending to start.
	 */
	import Card from '$lib/components/ui/Card.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';

	// ---------------------------------------------------------------------------
	// Static port data (~150 well-known ports)
	// ---------------------------------------------------------------------------

	interface PortEntry {
		port: number;
		protocol: string;
		service: string;
		description: string;
	}

	const PORTS: PortEntry[] = [
		{ port: 1, protocol: 'TCP', service: 'TCPMUX', description: 'TCP Port Service Multiplexer' },
		{ port: 5, protocol: 'TCP', service: 'RJE', description: 'Remote Job Entry' },
		{ port: 7, protocol: 'TCP/UDP', service: 'Echo', description: 'Echo Protocol' },
		{ port: 9, protocol: 'TCP/UDP', service: 'Discard', description: 'Discard Protocol' },
		{ port: 11, protocol: 'TCP', service: 'SYSTAT', description: 'Active Users' },
		{ port: 13, protocol: 'TCP/UDP', service: 'Daytime', description: 'Daytime Protocol' },
		{ port: 17, protocol: 'TCP', service: 'QOTD', description: 'Quote of the Day' },
		{ port: 19, protocol: 'TCP/UDP', service: 'CHARGEN', description: 'Character Generator Protocol' },
		{ port: 20, protocol: 'TCP', service: 'FTP Data', description: 'File Transfer Protocol data transfer' },
		{ port: 21, protocol: 'TCP', service: 'FTP', description: 'File Transfer Protocol control' },
		{ port: 22, protocol: 'TCP', service: 'SSH', description: 'Secure Shell' },
		{ port: 23, protocol: 'TCP', service: 'Telnet', description: 'Unencrypted text communications' },
		{ port: 25, protocol: 'TCP', service: 'SMTP', description: 'Simple Mail Transfer Protocol' },
		{ port: 37, protocol: 'TCP/UDP', service: 'Time', description: 'Time Protocol' },
		{ port: 42, protocol: 'TCP', service: 'WINS', description: 'Windows Internet Name Service' },
		{ port: 43, protocol: 'TCP', service: 'WHOIS', description: 'WHOIS directory service' },
		{ port: 49, protocol: 'TCP/UDP', service: 'TACACS', description: 'Terminal Access Controller Access-Control System' },
		{ port: 53, protocol: 'TCP/UDP', service: 'DNS', description: 'Domain Name System' },
		{ port: 67, protocol: 'UDP', service: 'DHCP', description: 'Dynamic Host Configuration (server)' },
		{ port: 68, protocol: 'UDP', service: 'DHCP', description: 'Dynamic Host Configuration (client)' },
		{ port: 69, protocol: 'UDP', service: 'TFTP', description: 'Trivial File Transfer Protocol' },
		{ port: 70, protocol: 'TCP', service: 'Gopher', description: 'Gopher Protocol' },
		{ port: 79, protocol: 'TCP', service: 'Finger', description: 'Finger Protocol' },
		{ port: 80, protocol: 'TCP', service: 'HTTP', description: 'Hypertext Transfer Protocol' },
		{ port: 88, protocol: 'TCP/UDP', service: 'Kerberos', description: 'Kerberos authentication system' },
		{ port: 102, protocol: 'TCP', service: 'ISO-TSAP', description: 'ISO Transport Service Access Point' },
		{ port: 110, protocol: 'TCP', service: 'POP3', description: 'Post Office Protocol v3' },
		{ port: 111, protocol: 'TCP/UDP', service: 'RPC', description: 'Remote Procedure Call' },
		{ port: 113, protocol: 'TCP', service: 'Ident', description: 'Identification Protocol' },
		{ port: 119, protocol: 'TCP', service: 'NNTP', description: 'Network News Transfer Protocol' },
		{ port: 123, protocol: 'UDP', service: 'NTP', description: 'Network Time Protocol' },
		{ port: 135, protocol: 'TCP/UDP', service: 'MS-RPC', description: 'Microsoft RPC Endpoint Mapper' },
		{ port: 137, protocol: 'UDP', service: 'NetBIOS-NS', description: 'NetBIOS Name Service' },
		{ port: 138, protocol: 'UDP', service: 'NetBIOS-DGM', description: 'NetBIOS Datagram Service' },
		{ port: 139, protocol: 'TCP', service: 'NetBIOS-SSN', description: 'NetBIOS Session Service' },
		{ port: 143, protocol: 'TCP', service: 'IMAP', description: 'Internet Message Access Protocol' },
		{ port: 161, protocol: 'UDP', service: 'SNMP', description: 'Simple Network Management Protocol' },
		{ port: 162, protocol: 'UDP', service: 'SNMP Trap', description: 'SNMP Trap notifications' },
		{ port: 179, protocol: 'TCP', service: 'BGP', description: 'Border Gateway Protocol' },
		{ port: 194, protocol: 'TCP', service: 'IRC', description: 'Internet Relay Chat' },
		{ port: 201, protocol: 'TCP', service: 'AppleTalk', description: 'AppleTalk Routing Maintenance' },
		{ port: 264, protocol: 'TCP', service: 'BGMP', description: 'Border Gateway Multicast Protocol' },
		{ port: 318, protocol: 'TCP', service: 'TSP', description: 'Time Stamp Protocol' },
		{ port: 381, protocol: 'TCP', service: 'HP Perf', description: 'HP Performance Data Collector' },
		{ port: 383, protocol: 'TCP', service: 'HP Alarm', description: 'HP Performance Data Alarm Manager' },
		{ port: 389, protocol: 'TCP/UDP', service: 'LDAP', description: 'Lightweight Directory Access Protocol' },
		{ port: 411, protocol: 'TCP', service: 'Direct Connect', description: 'Direct Connect Hub' },
		{ port: 412, protocol: 'TCP', service: 'Direct Connect', description: 'Direct Connect Client-to-Client' },
		{ port: 427, protocol: 'TCP/UDP', service: 'SLP', description: 'Service Location Protocol' },
		{ port: 443, protocol: 'TCP', service: 'HTTPS', description: 'HTTP over TLS/SSL' },
		{ port: 445, protocol: 'TCP', service: 'SMB', description: 'Server Message Block / Microsoft-DS' },
		{ port: 464, protocol: 'TCP/UDP', service: 'Kpasswd', description: 'Kerberos Change/Set Password' },
		{ port: 465, protocol: 'TCP', service: 'SMTPS', description: 'SMTP over TLS/SSL (deprecated)' },
		{ port: 497, protocol: 'TCP', service: 'Retrospect', description: 'Retrospect backup' },
		{ port: 500, protocol: 'UDP', service: 'IKE', description: 'Internet Key Exchange (IPSec)' },
		{ port: 502, protocol: 'TCP', service: 'Modbus', description: 'Modbus industrial protocol' },
		{ port: 512, protocol: 'TCP', service: 'rexec', description: 'Remote Process Execution' },
		{ port: 513, protocol: 'TCP', service: 'rlogin', description: 'Remote Login' },
		{ port: 514, protocol: 'TCP/UDP', service: 'Syslog', description: 'System Logging Protocol / Remote Shell' },
		{ port: 515, protocol: 'TCP', service: 'LPD', description: 'Line Printer Daemon' },
		{ port: 520, protocol: 'UDP', service: 'RIP', description: 'Routing Information Protocol' },
		{ port: 521, protocol: 'UDP', service: 'RIPng', description: 'Routing Information Protocol next generation' },
		{ port: 530, protocol: 'TCP', service: 'RPC', description: 'Remote Procedure Call' },
		{ port: 543, protocol: 'TCP', service: 'Klogin', description: 'Kerberos Login' },
		{ port: 544, protocol: 'TCP', service: 'Kshell', description: 'Kerberos Remote Shell' },
		{ port: 546, protocol: 'TCP/UDP', service: 'DHCPv6', description: 'DHCPv6 Client' },
		{ port: 547, protocol: 'TCP/UDP', service: 'DHCPv6', description: 'DHCPv6 Server' },
		{ port: 548, protocol: 'TCP', service: 'AFP', description: 'Apple Filing Protocol' },
		{ port: 554, protocol: 'TCP/UDP', service: 'RTSP', description: 'Real Time Streaming Protocol' },
		{ port: 587, protocol: 'TCP', service: 'Submission', description: 'Email Message Submission (SMTP)' },
		{ port: 593, protocol: 'TCP', service: 'HTTP-RPC', description: 'HTTP RPC Endpoint Mapper' },
		{ port: 631, protocol: 'TCP/UDP', service: 'IPP', description: 'Internet Printing Protocol (CUPS)' },
		{ port: 636, protocol: 'TCP', service: 'LDAPS', description: 'LDAP over TLS/SSL' },
		{ port: 639, protocol: 'TCP', service: 'MSDP', description: 'Multicast Source Discovery Protocol' },
		{ port: 646, protocol: 'TCP', service: 'LDP', description: 'Label Distribution Protocol' },
		{ port: 691, protocol: 'TCP', service: 'MS Exchange', description: 'MS Exchange Routing' },
		{ port: 860, protocol: 'TCP', service: 'iSCSI', description: 'iSCSI storage protocol' },
		{ port: 873, protocol: 'TCP', service: 'rsync', description: 'rsync file synchronization' },
		{ port: 902, protocol: 'TCP', service: 'VMware', description: 'VMware ESXi' },
		{ port: 989, protocol: 'TCP', service: 'FTPS Data', description: 'FTP over TLS data' },
		{ port: 990, protocol: 'TCP', service: 'FTPS', description: 'FTP over TLS control' },
		{ port: 993, protocol: 'TCP', service: 'IMAPS', description: 'IMAP over TLS/SSL' },
		{ port: 995, protocol: 'TCP', service: 'POP3S', description: 'POP3 over TLS/SSL' },
		{ port: 1080, protocol: 'TCP', service: 'SOCKS', description: 'SOCKS proxy protocol' },
		{ port: 1194, protocol: 'TCP/UDP', service: 'OpenVPN', description: 'OpenVPN tunnel' },
		{ port: 1433, protocol: 'TCP', service: 'MSSQL', description: 'Microsoft SQL Server' },
		{ port: 1434, protocol: 'UDP', service: 'MSSQL Browser', description: 'Microsoft SQL Server Browser' },
		{ port: 1521, protocol: 'TCP', service: 'Oracle', description: 'Oracle Database' },
		{ port: 1701, protocol: 'UDP', service: 'L2TP', description: 'Layer 2 Tunneling Protocol' },
		{ port: 1723, protocol: 'TCP', service: 'PPTP', description: 'Point-to-Point Tunneling Protocol' },
		{ port: 1812, protocol: 'UDP', service: 'RADIUS Auth', description: 'RADIUS Authentication' },
		{ port: 1813, protocol: 'UDP', service: 'RADIUS Acct', description: 'RADIUS Accounting' },
		{ port: 1883, protocol: 'TCP', service: 'MQTT', description: 'Message Queuing Telemetry Transport' },
		{ port: 1900, protocol: 'UDP', service: 'SSDP', description: 'Simple Service Discovery Protocol (UPnP)' },
		{ port: 2049, protocol: 'TCP/UDP', service: 'NFS', description: 'Network File System' },
		{ port: 2082, protocol: 'TCP', service: 'cPanel', description: 'cPanel default' },
		{ port: 2083, protocol: 'TCP', service: 'cPanel SSL', description: 'cPanel default SSL' },
		{ port: 2181, protocol: 'TCP', service: 'ZooKeeper', description: 'Apache ZooKeeper' },
		{ port: 2222, protocol: 'TCP', service: 'SSH Alt', description: 'SSH alternative' },
		{ port: 2375, protocol: 'TCP', service: 'Docker', description: 'Docker REST API (unencrypted)' },
		{ port: 2376, protocol: 'TCP', service: 'Docker TLS', description: 'Docker REST API (encrypted)' },
		{ port: 3000, protocol: 'TCP', service: 'Grafana', description: 'Grafana / Node.js dev server' },
		{ port: 3268, protocol: 'TCP', service: 'LDAP GC', description: 'Active Directory Global Catalog' },
		{ port: 3269, protocol: 'TCP', service: 'LDAPS GC', description: 'AD Global Catalog over SSL' },
		{ port: 3306, protocol: 'TCP', service: 'MySQL', description: 'MySQL / MariaDB Database' },
		{ port: 3389, protocol: 'TCP', service: 'RDP', description: 'Remote Desktop Protocol' },
		{ port: 3478, protocol: 'TCP/UDP', service: 'STUN', description: 'Session Traversal Utilities for NAT' },
		{ port: 4243, protocol: 'TCP', service: 'Docker', description: 'Docker default (older)' },
		{ port: 4500, protocol: 'UDP', service: 'IPSec NAT-T', description: 'IPSec NAT Traversal' },
		{ port: 4789, protocol: 'UDP', service: 'VXLAN', description: 'Virtual Extensible LAN' },
		{ port: 5000, protocol: 'TCP', service: 'UPnP', description: 'Universal Plug and Play / Flask' },
		{ port: 5044, protocol: 'TCP', service: 'Beats', description: 'Elastic Beats / Logstash Beats input' },
		{ port: 5060, protocol: 'TCP/UDP', service: 'SIP', description: 'Session Initiation Protocol' },
		{ port: 5061, protocol: 'TCP', service: 'SIP TLS', description: 'SIP over TLS' },
		{ port: 5222, protocol: 'TCP', service: 'XMPP', description: 'Extensible Messaging (Jabber) client' },
		{ port: 5269, protocol: 'TCP', service: 'XMPP S2S', description: 'XMPP Server-to-Server' },
		{ port: 5353, protocol: 'UDP', service: 'mDNS', description: 'Multicast DNS (Bonjour)' },
		{ port: 5432, protocol: 'TCP', service: 'PostgreSQL', description: 'PostgreSQL Database' },
		{ port: 5601, protocol: 'TCP', service: 'Kibana', description: 'Kibana / OpenSearch Dashboards' },
		{ port: 5672, protocol: 'TCP', service: 'AMQP', description: 'Advanced Message Queuing Protocol (RabbitMQ)' },
		{ port: 5900, protocol: 'TCP', service: 'VNC', description: 'Virtual Network Computing' },
		{ port: 5938, protocol: 'TCP', service: 'TeamViewer', description: 'TeamViewer remote access' },
		{ port: 5984, protocol: 'TCP', service: 'CouchDB', description: 'Apache CouchDB' },
		{ port: 6379, protocol: 'TCP', service: 'Redis', description: 'Redis key-value store' },
		{ port: 6443, protocol: 'TCP', service: 'Kubernetes', description: 'Kubernetes API Server' },
		{ port: 6514, protocol: 'TCP', service: 'Syslog TLS', description: 'Syslog over TLS' },
		{ port: 6660, protocol: 'TCP', service: 'IRC Alt', description: 'IRC alternative range start' },
		{ port: 6667, protocol: 'TCP', service: 'IRC', description: 'Internet Relay Chat (common)' },
		{ port: 6697, protocol: 'TCP', service: 'IRC TLS', description: 'IRC over TLS/SSL' },
		{ port: 6881, protocol: 'TCP/UDP', service: 'BitTorrent', description: 'BitTorrent default range start' },
		{ port: 7001, protocol: 'TCP', service: 'WebLogic', description: 'Oracle WebLogic Server' },
		{ port: 7474, protocol: 'TCP', service: 'Neo4j', description: 'Neo4j graph database HTTP' },
		{ port: 8000, protocol: 'TCP', service: 'HTTP Alt', description: 'HTTP alternative / Python dev server' },
		{ port: 8080, protocol: 'TCP', service: 'HTTP Proxy', description: 'HTTP alternative / proxy' },
		{ port: 8081, protocol: 'TCP', service: 'HTTP Alt', description: 'HTTP alternative' },
		{ port: 8443, protocol: 'TCP', service: 'HTTPS Alt', description: 'HTTPS alternative' },
		{ port: 8834, protocol: 'TCP', service: 'Nessus', description: 'Nessus vulnerability scanner' },
		{ port: 8880, protocol: 'TCP', service: 'NetTap API', description: 'NetTap Storage Daemon API' },
		{ port: 8883, protocol: 'TCP', service: 'MQTT TLS', description: 'MQTT over TLS/SSL' },
		{ port: 8888, protocol: 'TCP', service: 'HTTP Alt', description: 'HTTP alternative / Jupyter Notebook' },
		{ port: 9000, protocol: 'TCP', service: 'PHP-FPM', description: 'PHP FastCGI Process Manager' },
		{ port: 9090, protocol: 'TCP', service: 'Prometheus', description: 'Prometheus monitoring' },
		{ port: 9092, protocol: 'TCP', service: 'Kafka', description: 'Apache Kafka' },
		{ port: 9200, protocol: 'TCP', service: 'Elasticsearch', description: 'Elasticsearch / OpenSearch REST API' },
		{ port: 9300, protocol: 'TCP', service: 'ES Transport', description: 'Elasticsearch / OpenSearch node transport' },
		{ port: 9418, protocol: 'TCP', service: 'Git', description: 'Git daemon' },
		{ port: 9443, protocol: 'TCP', service: 'HTTPS Alt', description: 'HTTPS alternative (VMware)' },
		{ port: 10000, protocol: 'TCP', service: 'Webmin', description: 'Webmin admin panel' },
		{ port: 10050, protocol: 'TCP', service: 'Zabbix Agent', description: 'Zabbix monitoring agent' },
		{ port: 10051, protocol: 'TCP', service: 'Zabbix Server', description: 'Zabbix monitoring server' },
		{ port: 11211, protocol: 'TCP/UDP', service: 'Memcached', description: 'Memcached caching system' },
		{ port: 15672, protocol: 'TCP', service: 'RabbitMQ', description: 'RabbitMQ management UI' },
		{ port: 25565, protocol: 'TCP', service: 'Minecraft', description: 'Minecraft game server' },
		{ port: 27017, protocol: 'TCP', service: 'MongoDB', description: 'MongoDB Database' },
		{ port: 27018, protocol: 'TCP', service: 'MongoDB Shard', description: 'MongoDB Shard Server' },
		{ port: 27019, protocol: 'TCP', service: 'MongoDB Config', description: 'MongoDB Config Server' },
		{ port: 28017, protocol: 'TCP', service: 'MongoDB Web', description: 'MongoDB HTTP interface' },
		{ port: 33848, protocol: 'UDP', service: 'Jenkins', description: 'Jenkins auto-discovery' },
		{ port: 43594, protocol: 'TCP', service: 'RuneScape', description: 'RuneScape game server' },
		{ port: 47984, protocol: 'TCP', service: 'Sunshine', description: 'Sunshine / GameStream HTTPS' },
		{ port: 51413, protocol: 'TCP/UDP', service: 'Transmission', description: 'Transmission BitTorrent' },
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let search = $state('');
	let protocolFilter = $state<'All' | 'TCP' | 'UDP'>('All');

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let filtered = $derived.by(() => {
		let list = PORTS;

		if (protocolFilter !== 'All') {
			list = list.filter((p) => p.protocol.includes(protocolFilter));
		}

		const q = search.trim().toLowerCase();
		if (q) {
			list = list.filter(
				(p) =>
					String(p.port).includes(q) ||
					p.service.toLowerCase().includes(q) ||
					p.description.toLowerCase().includes(q) ||
					p.protocol.toLowerCase().includes(q)
			);
		}

		// OLD CODE START — DataTable sorts every column (utils/table-sort, the same compareValues), so the page only filters
		// const sorted = [...list].sort((a, b) => {
		// 	const av = a[sortKey];
		// 	const bv = b[sortKey];
		// 	if (typeof av === 'number' && typeof bv === 'number') {
		// 		return sortAsc ? av - bv : bv - av;
		// 	}
		// 	// OLD CODE START — text columns: compareValues orders the numbers inside names ("HTTP-8" before "HTTP-80"), like every table
		// 	// const cmp = String(av).localeCompare(String(bv));
		// 	// OLD CODE END
		// 	const cmp = compareValues(av, bv);
		// 	return sortAsc ? cmp : -cmp;
		// });
		//
		// return sorted;
		// OLD CODE END
		return list;
	});

	// OLD CODE START — the header buttons and arrows moved into DataTable
	// let sortKey = $state<'port' | 'protocol' | 'service' | 'description'>('port');
	// let sortAsc = $state(true);

	// function toggleSort(key: 'port' | 'protocol' | 'service' | 'description') {
	// 	if (sortKey === key) {
	// 		sortAsc = !sortAsc;
	// 	} else {
	// 		sortKey = key;
	// 		sortAsc = true;
	// 	}
	// }

	// function sortIndicator(key: string): string {
	// 	if (sortKey !== key) return '';
	// 	return sortAsc ? ' ↑' : ' ↓';
	// }
	// OLD CODE END

	const protocolOptions = [
		{ value: 'All' as const, label: 'All protocols' },
		{ value: 'TCP' as const, label: 'TCP' },
		{ value: 'UDP' as const, label: 'UDP' },
	];

	const columns: Column<PortEntry>[] = [
		{ key: 'port', label: 'Port', numeric: true, cell: portCell },
		{ key: 'protocol', label: 'Protocol', cell: protocolCell },
		{ key: 'service', label: 'Service', cell: serviceCell },
		{ key: 'description', label: 'Description' },
	];
</script>

{#snippet portCell(entry: PortEntry)}<span class="mono">{entry.port}</span>{/snippet}
{#snippet protocolCell(entry: PortEntry)}<span class="tag">{entry.protocol}</span>{/snippet}
{#snippet serviceCell(entry: PortEntry)}<b>{entry.service}</b>{/snippet}
{#snippet noPorts()}<span class="dim">No ports match your search.</span>{/snippet}

<svelte:head>
	<title>Port reference | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">Port reference</h1>
		<p class="page-sub">Well-known network ports, their protocols and the services that normally use them.</p>
	</div>
</div>

<Card title="Ports" sub="Showing {filtered.length} of {PORTS.length} ports">
	<div class="toolbar">
		<SearchField id="port-search" label="Search ports" placeholder="Search by port, service or description…" size="toolbar" bind:value={search} />
		<Pills options={protocolOptions} bind:value={protocolFilter} ariaLabel="Protocol" />
	</div>
	<DataTable
		{columns}
		rows={filtered}
		ariaLabel="Well-known ports"
		rowKey={(entry) => entry.port + entry.description}
		initialSort={{ key: 'port', dir: 'asc' }}
		empty={noPorts}
	/>
</Card>
