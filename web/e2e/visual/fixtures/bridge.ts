import type { BridgeHealth, BridgeReadiness, BridgeReadinessCheck } from '../../../src/lib/api/bridge.ts';
import { iso, type FixtureRoute } from './types.ts';

const LATENCY_NOTE = "Not measured: NetTap can't time packets through the bridge";

/** GET /api/bridge/bypass/status: the daemon sends `bypass_active`; the client maps it to `active`. */
interface DaemonBypassStatus {
	bypass_active: boolean;
}

/** A fresh install: the bridge is built on the Go Live page. */
const HEALTH_EMPTY = {
	bridge_state: 'not_configured',
	wan_link: false,
	lan_link: false,
	bypass_active: false,
	watchdog_active: false,
	latency_us: null,
	latency_note: LATENCY_NOTE,
	rx_bytes_delta: 0,
	tx_bytes_delta: 0,
	rx_packets_delta: 0,
	tx_packets_delta: 0,
	uptime_seconds: 0,
	health_status: 'not_configured',
	issues: ['Bridge interface has not been configured — run the setup wizard'],
	last_check: iso(8_000),
} satisfies BridgeHealth;

const HEALTH_POPULATED = {
	bridge_state: 'up',
	wan_link: true,
	lan_link: true,
	bypass_active: false,
	watchdog_active: true,
	latency_us: null,
	latency_note: LATENCY_NOTE,
	rx_bytes_delta: 118_400_000,
	tx_bytes_delta: 112_900_000,
	rx_packets_delta: 96_300,
	tx_packets_delta: 91_700,
	uptime_seconds: 1_047_600,
	health_status: 'normal',
	issues: [],
	last_check: iso(8_000),
} satisfies BridgeHealth;

const CHECKS_PASSED = [
	{ name: 'bridge_exists', passed: true, detail: 'Bridge br0 found in sysfs' },
	{ name: 'bridge_up', passed: true, detail: 'Bridge br0 is UP' },
	{ name: 'wan_carrier', passed: true, detail: 'WAN (enp1s0) carrier detected' },
	{ name: 'lan_carrier', passed: true, detail: 'LAN (enp2s0) carrier detected' },
	{ name: 'wan_promisc', passed: true, detail: 'WAN (enp1s0) promiscuous mode enabled' },
	{ name: 'lan_promisc', passed: true, detail: 'LAN (enp2s0) promiscuous mode enabled' },
	{ name: 'stp_disabled', passed: true, detail: 'STP disabled' },
	{
		name: 'netfilter_disabled',
		passed: true,
		detail: 'Bridge netfilter not loaded (br_netfilter module absent — no iptables interference)',
	},
] satisfies BridgeReadinessCheck[];

const READINESS_POPULATED = {
	ready: true,
	checks: CHECKS_PASSED,
	message: 'All checks passed. Your network is ready for monitoring.',
} satisfies BridgeReadiness;

/** No bridge yet, so Go Live opens on its first step. */
const READINESS_EMPTY = {
	ready: false,
	checks: [
		{ name: 'bridge_exists', passed: false, detail: 'Bridge br0 not found in sysfs' },
		...CHECKS_PASSED.slice(1).map((check) => ({
			name: check.name,
			passed: false,
			detail: 'Bridge does not exist',
		})),
	],
	message:
		'Bridge has not been configured yet. Run the setup wizard or create the bridge from the Go Live page.',
} satisfies BridgeReadiness;

const BYPASS_INACTIVE = { bypass_active: false } satisfies DaemonBypassStatus;

export const BRIDGE_ROUTES: FixtureRoute[] = [
	{ path: '/api/bridge/health', empty: HEALTH_EMPTY, populated: HEALTH_POPULATED },
	{ path: '/api/bridge/readiness', empty: READINESS_EMPTY, populated: READINESS_POPULATED },
	{ path: '/api/bridge/bypass/status', empty: BYPASS_INACTIVE, populated: BYPASS_INACTIVE },
];
