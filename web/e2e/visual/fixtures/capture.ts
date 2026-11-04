import type {
	CaptureHealthResponse,
	CaptureMode,
	CaptureStatsResponse,
	CaptureStatus,
} from '../../../src/lib/api/capture.ts';
import { iso, type FixtureRoute } from './types.ts';

const LATENCY_NOTE = "Not measured: NetTap can't time packets through the bridge";

/** Same in every mode: the mode is a setting, not data. */
const MODE = { mode: 'bridge', interface: 'br0' } satisfies CaptureMode;

const HEALTH_POPULATED = {
	mode: 'bridge',
	status: 'normal',
	capture_interface: 'br0',
	link_up: true,
	promisc_enabled: true,
	issues: [],
	bridge_state: 'up',
	wan_link: true,
	lan_link: true,
	wan_iface: 'enp1s0',
	lan_iface: 'enp2s0',
	bypass_active: false,
	watchdog_active: true,
	latency_us: null,
	latency_note: LATENCY_NOTE,
	uptime_seconds: 1_047_600,
	last_check: iso(8_000),
} satisfies CaptureHealthResponse;

/** A fresh install: the bridge is built on the Go Live page, so nothing is up yet. */
const HEALTH_EMPTY = {
	mode: 'bridge',
	status: 'not_configured',
	capture_interface: 'br0',
	link_up: false,
	promisc_enabled: false,
	issues: ['Bridge interface has not been configured — run the setup wizard'],
	bridge_state: 'not_configured',
	wan_link: false,
	lan_link: false,
	wan_iface: 'enp1s0',
	lan_iface: 'enp2s0',
	bypass_active: false,
	watchdog_active: false,
	latency_us: null,
	latency_note: LATENCY_NOTE,
	uptime_seconds: 0,
	last_check: iso(8_000),
} satisfies CaptureHealthResponse;

const RX_PACKETS = 2_950_000_000;
const RX_DROPPED = 1_204;

const STATS_POPULATED = {
	capture_interface: 'br0',
	rx_bytes: 3_480_000_000_000,
	tx_bytes: 3_390_000_000_000,
	rx_packets: RX_PACKETS,
	tx_packets: 2_870_000_000,
	rx_dropped: RX_DROPPED,
	rx_missed_errors: 0,
	link_speed_mbps: 2500,
	drop_rate_pct: Math.round((RX_DROPPED / RX_PACKETS) * 100 * 1e6) / 1e6,
} satisfies CaptureStatsResponse;

const STATS_EMPTY = {
	capture_interface: 'br0',
	rx_bytes: 0,
	tx_bytes: 0,
	rx_packets: 0,
	tx_packets: 0,
	rx_dropped: 0,
	rx_missed_errors: 0,
	link_speed_mbps: 0,
	drop_rate_pct: 0,
} satisfies CaptureStatsResponse;

/** The PCAP container runs in both: only the bridge is missing on a fresh install. */
const STATUS_EMPTY = {
	enabled: true,
	maxFileSizeMB: 100,
	rotateMinutes: 10,
	containerRunning: true,
	containerStatus: 'running',
} satisfies CaptureStatus;

const STATUS_POPULATED = { ...STATUS_EMPTY, maxFileSizeMB: 256 } satisfies CaptureStatus;

export const CAPTURE_ROUTES: FixtureRoute[] = [
	{ path: '/api/capture/mode', empty: MODE, populated: MODE },
	{ path: '/api/capture/health', empty: HEALTH_EMPTY, populated: HEALTH_POPULATED },
	{ path: '/api/capture/stats', empty: STATS_EMPTY, populated: STATS_POPULATED },
	{ path: '/api/capture/status', empty: STATUS_EMPTY, populated: STATUS_POPULATED },
];
