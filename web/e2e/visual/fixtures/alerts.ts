/** Fixtures for the alert endpoints (daemon/api/alerts.py), reached through the web passthrough routes. */
import type {
	Alert,
	AlertCategory,
	AlertCountResponse,
	AlertsListResponse,
	AlertTimelineResponse,
	AlertTopIpsResponse,
	AlertTopSignaturesResponse,
	CategoryDetailResponse,
	CategoryTimelinePoint,
	CategoryTimelineResponse,
	CategoryTrend,
	EnhancedCategoriesResponse,
	SmartAlert,
	SmartAlertSummary,
	SmartAlertsResponse,
} from '../../../src/lib/api/alerts.ts';
import { HOUR, iso, MIN, type FixtureRoute } from './types.ts';

const FROM = iso(24 * HOUR);
const TO = iso(0);
const MALWARE = { id: 'malware_c2', label: 'Malware & C2', icon: 'alert', color: '#ff4757' };

// --- /api/alerts -----------------------------------------------------------------------------

interface AlertSeed {
	minsAgo: number;
	severity: number;
	signature: string;
	sid: number;
	category: string;
	src: [string, number];
	dest: [string, number];
	proto: string;
	plain: string;
	risk: string;
	fix: string;
	acked?: boolean;
}

function toAlert(s: AlertSeed, i: number): Alert {
	return {
		_id: `fx-alert-${String(i + 1).padStart(3, '0')}`,
		_index: 'arkime_sessions3-fixture',
		timestamp: iso(s.minsAgo * MIN),
		alert: { signature: s.signature, signature_id: s.sid, severity: s.severity, category: s.category },
		src_ip: s.src[0],
		src_port: s.src[1],
		dest_ip: s.dest[0],
		dest_port: s.dest[1],
		proto: s.proto,
		acknowledged: s.acked ?? false,
		...(s.acked ? { acknowledged_at: iso((s.minsAgo - 30) * MIN) } : {}),
		plain_description: s.plain,
		risk_context: s.risk,
		recommendation: s.fix,
	};
}

const ALERT_SEEDS: AlertSeed[] = [
	{ minsAgo: 6, severity: 1, signature: 'ET MALWARE Example Agent.Gen CnC Checkin', sid: 2900001, category: 'A Network Trojan was detected', src: ['192.168.1.42', 51842], dest: ['203.0.113.45', 8080], proto: 'TCP', plain: 'A device on your network contacted a server that is known to control infected computers.', risk: 'High: the device may be infected and taking orders from an attacker.', fix: 'Disconnect the device, run a malware scan, and change the passwords used on it.' },
	{ minsAgo: 18, severity: 1, signature: 'ET TROJAN Example Win32/Stealer Exfil Beacon', sid: 2900002, category: 'A Network Trojan was detected', src: ['192.168.1.42', 51990], dest: ['198.51.100.17', 443], proto: 'TCP', plain: 'A program on this device sent data to a server linked to credential-stealing malware.', risk: 'High: saved passwords or files may have left your network.', fix: 'Isolate the device and rotate the passwords stored on it.' },
	{ minsAgo: 41, severity: 2, signature: 'ET SCAN Example Port Sweep Detected', sid: 2900010, category: 'Detection of a Network Scan', src: ['192.168.1.57', 40122], dest: ['192.0.2.88', 22], proto: 'TCP', plain: 'This device probed many ports on another host, which is what a scanner does.', risk: 'Medium: normal for a security tool, unusual for a TV.', fix: 'Check whether anyone on the network runs a scanner; otherwise investigate the device.' },
	{ minsAgo: 70, severity: 2, signature: 'ET EXPLOIT Example Web App Command Injection Attempt', sid: 2900020, category: 'Web Application Attack', src: ['198.51.100.200', 44213], dest: ['192.168.1.23', 8080], proto: 'TCP', plain: 'An outside host tried to run commands on a web service in your network.', risk: 'Medium: the attempt was blocked by the router, but the service is exposed.', fix: 'Close the port forward to 192.168.1.23 or update the service.' },
	{ minsAgo: 120, severity: 3, signature: 'ET POLICY Example Cleartext Password Over HTTP', sid: 2900030, category: 'Potential Corporate Privacy Violation', src: ['192.168.1.23', 52210], dest: ['203.0.113.9', 80], proto: 'TCP', plain: 'A password was sent over an unencrypted connection.', risk: 'Low: anyone on the path could read it.', fix: 'Switch the service to HTTPS.' },
	{ minsAgo: 180, severity: 3, signature: 'ET POLICY Example Outbound Connection To Tor Relay', sid: 2900031, category: 'Potential Corporate Privacy Violation', src: ['192.168.1.57', 49310], dest: ['192.0.2.150', 9001], proto: 'TCP', plain: 'This device connected to the Tor anonymity network.', risk: 'Low: allowed on many networks, but it hides where traffic goes.', fix: 'Confirm that someone installed Tor on purpose.' },
	{ minsAgo: 300, severity: 3, signature: 'ET DNS Example Query To Suspicious TLD', sid: 2900040, category: 'Potentially Bad Traffic', src: ['192.168.1.80', 53422], dest: ['192.0.2.53', 53], proto: 'UDP', plain: 'This device looked up a domain on a top-level domain often used for abuse.', risk: 'Low: most of these lookups are harmless ads or trackers.', fix: 'Watch for repeats from the same device.' },
	{ minsAgo: 420, severity: 4, signature: 'ET INFO Example External IP Lookup Domain', sid: 2900050, category: 'Misc activity', src: ['192.168.1.23', 50211], dest: ['198.51.100.53', 443], proto: 'TCP', plain: 'This device asked a public website for its own internet address.', risk: 'Informational: common in apps and scripts.', fix: 'No action needed.' },
	{ minsAgo: 660, severity: 4, signature: 'ET INFO Example TLS Certificate Expired', sid: 2900051, category: 'Misc activity', src: ['192.168.1.80', 50999], dest: ['203.0.113.77', 443], proto: 'TCP', plain: 'A server presented a TLS certificate that has expired.', risk: 'Informational: the connection may not be trustworthy.', fix: 'Check the vendor service this device talks to.', acked: true },
	{ minsAgo: 1200, severity: 2, signature: 'ET SCAN Example SSH Brute Force Attempt', sid: 2900011, category: 'Attempted Administrator Privilege Gain', src: ['198.51.100.17', 55012], dest: ['192.168.1.23', 22], proto: 'TCP', plain: 'An outside host tried many passwords against the SSH service.', risk: 'Medium: a weak password here would give full access.', fix: 'Disable password logins for SSH and use keys.' },
];

const ALERTS: Alert[] = ALERT_SEEDS.map(toAlert);

const ALERT_LIST_EMPTY = { from: FROM, to: TO, page: 1, size: 10, total: 0, total_pages: 0, alerts: [] } satisfies AlertsListResponse;
const ALERT_LIST = { ...ALERT_LIST_EMPTY, total: 214, total_pages: 22, alerts: ALERTS } satisfies AlertsListResponse;

// --- /api/alerts/count and /timeline ---------------------------------------------------------

const COUNT_EMPTY = { from: FROM, to: TO, counts: { total: 0, high: 0, medium: 0, low: 0 } } satisfies AlertCountResponse;
// Real-sized counts (a home G11 logs ~150,000 a day), so a six-digit count has to fit its severity tile
const SCALE = 1000;
const COUNT = {
	from: FROM,
	to: TO,
	counts: { total: 214 * SCALE, high: 9 * SCALE, medium: 47 * SCALE, low: 158 * SCALE },
} satisfies AlertCountResponse;

// One entry per hour, oldest first; times SCALE, the columns sum to the counts above (9 / 47 / 158)
const HIGH_PER_HOUR = [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 2, 0, 0, 1, 0, 2, 0, 1, 1];
const MEDIUM_PER_HOUR = [1, 2, 1, 3, 2, 1, 2, 1, 2, 3, 2, 1, 2, 3, 2, 1, 2, 3, 2, 2, 3, 2, 2, 2];
const LOW_PER_HOUR = [5, 6, 7, 6, 5, 7, 6, 8, 7, 6, 7, 8, 7, 6, 7, 8, 7, 6, 7, 7, 6, 6, 7, 6];

const TIMELINE_EMPTY = { from: FROM, to: TO, interval: '1h', buckets: [] } satisfies AlertTimelineResponse;
const TIMELINE = {
	...TIMELINE_EMPTY,
	buckets: HIGH_PER_HOUR.map((high, i) => ({
		timestamp: iso((HIGH_PER_HOUR.length - i) * HOUR),
		high: high * SCALE,
		medium: MEDIUM_PER_HOUR[i] * SCALE,
		low: LOW_PER_HOUR[i] * SCALE,
	})),
} satisfies AlertTimelineResponse;

// --- /api/alerts/top-signatures and /top-ips -------------------------------------------------

const TOP_SIGNATURES_EMPTY = { from: FROM, to: TO, signatures: [] } satisfies AlertTopSignaturesResponse;
const TOP_SIGNATURES = {
	...TOP_SIGNATURES_EMPTY,
	signatures: [
		{ signature: 'ET INFO Example External IP Lookup Domain', count: 33, severity: 4 },
		{ signature: 'ET POLICY Example Outbound Connection To Tor Relay', count: 31, severity: 3 },
		{ signature: 'ET POLICY Example Cleartext Password Over HTTP', count: 27, severity: 3 },
		{ signature: 'ET INFO Example TLS Certificate Expired', count: 24, severity: 4 },
		{ signature: 'ET MALWARE Example Agent.Gen CnC Checkin', count: 21, severity: 1 },
		{ signature: 'ET SCAN Example Port Sweep Detected', count: 19, severity: 2 },
		{ signature: 'ET DNS Example Query To Suspicious TLD', count: 16, severity: 3 },
		{ signature: 'ET SCAN Example SSH Brute Force Attempt', count: 12, severity: 2 },
		{ signature: 'ET EXPLOIT Example Web App Command Injection Attempt', count: 9, severity: 2 },
		{ signature: 'ET TROJAN Example Win32/Stealer Exfil Beacon', count: 7, severity: 1 },
	],
} satisfies AlertTopSignaturesResponse;

// The same path answers direction=src and direction=dest (queries are ignored), so the list mixes both
const TOP_IPS_EMPTY = { from: FROM, to: TO, direction: 'dest', ips: [] } satisfies AlertTopIpsResponse;
const TOP_IPS = {
	...TOP_IPS_EMPTY,
	ips: [
		{ ip: '192.168.1.42', count: 61 },
		{ ip: '203.0.113.45', count: 38 },
		{ ip: '192.168.1.57', count: 33 },
		{ ip: '198.51.100.17', count: 24 },
		{ ip: '192.168.1.23', count: 19 },
		{ ip: '192.0.2.88', count: 11 },
	],
} satisfies AlertTopIpsResponse;

// --- /api/alerts/categories ------------------------------------------------------------------

// What the daemon sends: `trend` as a bare string and `sparkline` as [{timestamp, count}].
// The client (getEnhancedCategories) reshapes it into AlertCategory.
type DaemonCategory = Omit<AlertCategory, 'trend' | 'sparkline'> & {
	trend: CategoryTrend['direction'];
	sparkline: { timestamp: string; count: number }[];
};
type DaemonCategories = Omit<EnhancedCategoriesResponse, 'categories'> & { interval: string; categories: DaemonCategory[] };

const sparkline = (counts: number[]) => counts.map((count, i) => ({ timestamp: iso((counts.length - i) * 4 * HOUR), count }));

const CATEGORIES_EMPTY = { from: FROM, to: TO, interval: '4h', categories: [] } satisfies DaemonCategories;
const CATEGORIES = {
	...CATEGORIES_EMPTY,
	// the counts add up to the 214 alerts in /api/alerts/count
	categories: [
		{ ...MALWARE, description: 'Known malware signatures, command-and-control callbacks, and threat intel matches.', count: 31, severity_breakdown: { critical: 9, high: 12, medium: 10, low: 0, info: 0 }, trend: 'increasing', sparkline: sparkline([2, 3, 4, 5, 7, 10]), sub_categories: [{ id: 'trojan', label: 'Trojan Activity', count: 14 }, { id: 'botnet', label: 'Botnet C2', count: 11 }, { id: 'threat_intel', label: 'Threat Intel Match', count: 6 }] },
		{ id: 'reconnaissance', label: 'Reconnaissance', icon: 'search', color: '#ffa502', description: 'Port scanning, service enumeration, and network probing.', count: 22, severity_breakdown: { critical: 0, high: 7, medium: 15, low: 0, info: 0 }, trend: 'stable', sparkline: sparkline([4, 3, 4, 3, 4, 4]), sub_categories: [{ id: 'port_scan', label: 'Port Scan', count: 22 }] },
		{ id: 'exploit', label: 'Exploit Attempt', icon: 'bug', color: '#ff4757', description: 'Active exploitation of known vulnerabilities (CVEs, RCE, injection).', count: 9, severity_breakdown: { critical: 0, high: 9, medium: 0, low: 0, info: 0 }, trend: 'decreasing', sparkline: sparkline([3, 2, 2, 1, 1, 0]), sub_categories: [] },
		{ id: 'credential_abuse', label: 'Credential Abuse', icon: 'key', color: '#e74c3c', description: 'Brute force, password spraying, and credential theft attempts.', count: 12, severity_breakdown: { critical: 0, high: 12, medium: 0, low: 0, info: 0 }, trend: 'stable', sparkline: sparkline([2, 2, 1, 3, 2, 2]), sub_categories: [{ id: 'ssh_brute', label: 'SSH Brute Force', count: 12 }] },
		{ id: 'policy', label: 'Policy Violation', icon: 'shield', color: '#2ed573', description: 'P2P usage, gaming traffic, Tor access, and other policy-violating activity.', count: 74, severity_breakdown: { critical: 0, high: 0, medium: 0, low: 74, info: 0 }, trend: 'stable', sparkline: sparkline([12, 13, 12, 14, 11, 12]), sub_categories: [] },
		{ id: 'informational', label: 'Informational', icon: 'info', color: '#a4b0be', description: 'Low-priority observations and protocol metadata events.', count: 66, severity_breakdown: { critical: 0, high: 0, medium: 0, low: 0, info: 66 }, trend: 'stable', sparkline: sparkline([10, 11, 11, 12, 11, 11]), sub_categories: [] },
	],
} satisfies DaemonCategories;

// --- /api/alerts/categories/<category> and /timeline (one record whatever the id) ------------

const CATEGORY_DETAIL_EMPTY = {
	from: FROM,
	to: TO,
	category: { ...MALWARE, description: 'Known malware signatures, command-and-control callbacks, and threat intel matches.' },
	stats: { total: 0, unique_sources: 0, unique_targets: 0, affected_devices: 0 },
	severity_breakdown: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
	sub_categories: [],
	affected_devices: [],
	top_signatures: [],
	mitre_techniques: [],
} satisfies CategoryDetailResponse;

const CATEGORY_DETAIL = {
	...CATEGORY_DETAIL_EMPTY,
	stats: { total: 31, unique_sources: 2, unique_targets: 3, affected_devices: 5 },
	severity_breakdown: { critical: 9, high: 12, medium: 10, low: 0, info: 0 },
	sub_categories: [{ id: 'trojan', label: 'Trojan Activity', count: 14 }, { id: 'botnet', label: 'Botnet C2', count: 11 }, { id: 'threat_intel', label: 'Threat Intel Match', count: 6 }],
	affected_devices: [
		{ ip: '192.168.1.42', count: 24, severity: 'critical' },
		{ ip: '203.0.113.45', count: 17, severity: 'critical' },
		{ ip: '198.51.100.17', count: 7, severity: 'critical' },
		{ ip: '192.168.1.80', count: 4, severity: 'high' },
		{ ip: '192.0.2.150', count: 3, severity: 'medium' },
	],
	top_signatures: [
		{ signature: 'ET MALWARE Example Agent.Gen CnC Checkin', count: 21, last_seen: iso(6 * MIN) },
		{ signature: 'ET TROJAN Example Win32/Stealer Exfil Beacon', count: 7, last_seen: iso(18 * MIN) },
		{ signature: 'ET CNC Example Known Botnet Controller Traffic', count: 3, last_seen: iso(5 * HOUR) },
	],
	mitre_techniques: [
		{ id: 'T1071', name: 'Application Layer Protocol', description: 'C2 over HTTP, DNS, or other app-layer protocols.' },
		{ id: 'T1573', name: 'Encrypted Channel', description: 'C2 encrypted to avoid detection.' },
	],
} satisfies CategoryDetailResponse;

const CATEGORY_TIMELINE_EMPTY = { category: MALWARE.id, from: FROM, to: TO, interval: '1h', series: [] } satisfies CategoryTimelineResponse;
const MALWARE_PER_HOUR = [0, 0, 1, 1, 0, 2, 1, 0, 0, 1, 2, 1, 1, 0, 2, 1, 2, 1, 2, 3, 2, 3, 3, 2];
const CATEGORY_TIMELINE = {
	...CATEGORY_TIMELINE_EMPTY,
	series: MALWARE_PER_HOUR.map((total, i): CategoryTimelinePoint => ({
		timestamp: iso((MALWARE_PER_HOUR.length - i) * HOUR),
		total,
		sub_categories: total ? { trojan: Math.ceil(total / 2), botnet: Math.floor(total / 2) } : {},
	})),
} satisfies CategoryTimelineResponse;

// --- /api/alerts/smart and /smart/summary ----------------------------------------------------

const SMART_ALERTS: SmartAlert[] = [
	{ signature_id: 2900001, signature: 'ET MALWARE Example Agent.Gen CnC Checkin', suricata_category: 'A Network Trojan was detected', severity: 1, severity_label: 'CRITICAL', category: 'malware_c2', category_label: 'Malware & C2', source_ip: '192.168.1.42', destination_ip: '203.0.113.45', destination_port: 8080, count: 142, first_seen: iso(22 * HOUR), last_seen: iso(6 * MIN), trend: 'increasing', assessment: 'This alert indicates potential malicious activity. Only this device triggers this alert, so it may be targeted. Frequency is increasing rapidly: investigate promptly.' },
	{ signature_id: 2900002, signature: 'ET TROJAN Example Win32/Stealer Exfil Beacon', suricata_category: 'A Network Trojan was detected', severity: 1, severity_label: 'CRITICAL', category: 'malware_c2', category_label: 'Malware & C2', source_ip: '192.168.1.42', destination_ip: '198.51.100.17', destination_port: 443, count: 37, first_seen: iso(9 * HOUR), last_seen: iso(18 * MIN), trend: 'stable', assessment: 'This alert indicates potential malicious activity. Only this device triggers this alert, so it may be targeted.' },
	{ signature_id: 2900020, signature: 'ET EXPLOIT Example Web App Command Injection Attempt', suricata_category: 'Web Application Attack', severity: 2, severity_label: 'HIGH', category: 'exploit', category_label: 'Exploit Attempt', source_ip: '198.51.100.200', destination_ip: '192.168.1.23', destination_port: 8080, count: 9, first_seen: iso(6 * HOUR), last_seen: iso(70 * MIN), trend: 'decreasing', assessment: 'Possible exploitation attempt. Only this device triggers this alert, so it may be targeted. Alert frequency is declining.' },
	{ signature_id: 2900010, signature: 'ET SCAN Example Port Sweep Detected', suricata_category: 'Detection of a Network Scan', severity: 3, severity_label: 'MEDIUM', category: 'reconnaissance', category_label: 'Reconnaissance', source_ip: '192.168.1.57', destination_ip: '192.0.2.88', destination_port: 22, count: 64, first_seen: iso(20 * HOUR), last_seen: iso(41 * MIN), trend: 'stable', assessment: 'Network scanning or enumeration activity. Only this device triggers this alert, so it may be targeted.' },
	{ signature_id: 2900030, signature: 'ET POLICY Example Cleartext Password Over HTTP', suricata_category: 'Potential Corporate Privacy Violation', severity: 3, severity_label: 'MEDIUM', category: 'sensitive_data', category_label: 'Sensitive Data Exposure', source_ip: '192.168.1.23', destination_ip: '203.0.113.9', destination_port: 80, count: 12, first_seen: iso(12 * HOUR), last_seen: iso(2 * HOUR), trend: 'stable', assessment: 'Sensitive data exposure detected. Only this device triggers this alert, so it may be targeted.' },
	{ signature_id: 2900031, signature: 'ET POLICY Example Outbound Connection To Tor Relay', suricata_category: 'Potential Corporate Privacy Violation', severity: 4, severity_label: 'LOW', category: 'policy', category_label: 'Policy Violation', source_ip: '192.168.1.57', destination_ip: '192.0.2.150', destination_port: 9001, count: 27, first_seen: iso(15 * HOUR), last_seen: iso(3 * HOUR), trend: 'stable', assessment: 'Network policy violation detected. Only this device triggers this alert, so it may be targeted.' },
];

const SMART_EMPTY = { from: FROM, to: TO, device_ip: null, alerts: [], total: 0 } satisfies SmartAlertsResponse;
const SMART = { ...SMART_EMPTY, alerts: SMART_ALERTS, total: SMART_ALERTS.length } satisfies SmartAlertsResponse;

const SMART_SUMMARY_EMPTY = { from: FROM, to: TO, threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, informational_events: 0, categories: {}, top_threats: [] } satisfies SmartAlertSummary;
const SMART_SUMMARY = {
	...SMART_SUMMARY_EMPTY,
	threat_score: 29, // two critical (10 each) + one high (5) + two medium (2 each) + one low (0.5)
	threat_level: 'medium',
	total_groups: SMART_ALERTS.length,
	total_events: SMART_ALERTS.reduce((sum, a) => sum + a.count, 0),
	informational_events: 66,
	categories: {
		malware_c2: { label: 'Malware & C2', groups: 2, events: 179 },
		exploit: { label: 'Exploit Attempt', groups: 1, events: 9 },
		reconnaissance: { label: 'Reconnaissance', groups: 1, events: 64 },
		sensitive_data: { label: 'Sensitive Data Exposure', groups: 1, events: 12 },
		policy: { label: 'Policy Violation', groups: 1, events: 27 },
	},
	top_threats: SMART_ALERTS.slice(0, 3),
} satisfies SmartAlertSummary;

export const ALERT_ROUTES: FixtureRoute[] = [
	{ path: '/api/alerts', empty: ALERT_LIST_EMPTY, populated: ALERT_LIST },
	{ path: '/api/alerts/count', empty: COUNT_EMPTY, populated: COUNT },
	{ path: '/api/alerts/timeline', empty: TIMELINE_EMPTY, populated: TIMELINE },
	{ path: '/api/alerts/top-signatures', empty: TOP_SIGNATURES_EMPTY, populated: TOP_SIGNATURES },
	{ path: '/api/alerts/top-ips', empty: TOP_IPS_EMPTY, populated: TOP_IPS },
	{ path: '/api/alerts/categories', empty: CATEGORIES_EMPTY, populated: CATEGORIES },
	{ path: /^\/api\/alerts\/categories\/[^/]+$/, empty: CATEGORY_DETAIL_EMPTY, populated: CATEGORY_DETAIL },
	{ path: /^\/api\/alerts\/categories\/[^/]+\/timeline$/, empty: CATEGORY_TIMELINE_EMPTY, populated: CATEGORY_TIMELINE },
	{ path: '/api/alerts/smart', empty: SMART_EMPTY, populated: SMART },
	{ path: '/api/alerts/smart/summary', empty: SMART_SUMMARY_EMPTY, populated: SMART_SUMMARY },
];
