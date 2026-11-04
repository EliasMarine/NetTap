/** Fixtures for /api/risk/scores (daemon/api/risk.py), reached through web routes. */
import type { DeviceRiskScore, RiskFactor } from '../../../src/lib/api/risk.ts';
import { HOUR, iso, type FixtureRoute } from './types.ts';

// The daemon sends `devices` (getRiskScores reshapes it into `scores`) with extra counters,
// and the single-device record carries the time range too.
interface DaemonDeviceRisk extends DeviceRiskScore {
	connection_count: number;
	alert_count: number;
}
interface DaemonRiskScores {
	from: string;
	to: string;
	device_count: number;
	network_avg_connections: number;
	network_stddev_connections: number;
	devices: DaemonDeviceRisk[];
}
interface DaemonRiskScore extends DaemonDeviceRisk {
	from: string;
	to: string;
}

const FROM = iso(24 * HOUR);
const TO = iso(0);

/** The five factors the scorer always reports, with the daemon's maxima (35/20/15/15/15). */
function factors(points: [number, number, number, number, number]): RiskFactor[] {
	const rows: [string, number, string][] = [
		['alert_count', 35, 'Suricata alerts raised by this device'],
		['connection_anomaly', 20, 'Connection volume compared with the network average'],
		['external_ratio', 15, 'Share of connections that leave the local network'],
		['suspicious_ports', 15, 'Connections to ports often used by malware'],
		['data_exfiltration', 15, 'Upload versus download volume'],
	];
	return rows.map(([name, max, description], i) => ({ name, score: points[i], max, description }));
}

const level = (score: number) => (score >= 75 ? 'critical' : score >= 50 ? 'high' : score >= 25 ? 'medium' : 'low');
function device(ip: string, points: [number, number, number, number, number], connections: number, alerts: number): DaemonDeviceRisk {
	const score = points.reduce((sum, p) => sum + p, 0);
	return { ip, score, level: level(score), factors: factors(points), connection_count: connections, alert_count: alerts };
}

const DEVICES = [
	device('192.168.1.42', [30, 14, 11, 8, 6], 5210, 61),
	device('192.168.1.57', [14, 6, 7, 0, 2], 2380, 33),
	device('192.168.1.23', [10, 4, 6, 0, 1], 1840, 19),
	device('192.168.1.80', [4, 2, 5, 0, 0], 960, 6),
];

const SCORES_EMPTY = { from: FROM, to: TO, device_count: 0, network_avg_connections: 0, network_stddev_connections: 0, devices: [] } satisfies DaemonRiskScores;
const SCORES = { ...SCORES_EMPTY, device_count: DEVICES.length, network_avg_connections: 2597.5, network_stddev_connections: 1650.2, devices: DEVICES } satisfies DaemonRiskScores;

// One record whatever the IP (the harness opens 192.168.1.20); the empty one is a device with no
// activity, where the real daemon would answer 404
const SINGLE_EMPTY = { from: FROM, to: TO, ...device('192.168.1.20', [0, 0, 0, 0, 0], 0, 0) } satisfies DaemonRiskScore;
const SINGLE = { from: FROM, to: TO, ...device('192.168.1.20', [10, 6, 8, 0, 2], 1520, 14) } satisfies DaemonRiskScore;

export const RISK_ROUTES: FixtureRoute[] = [
	{ path: '/api/risk/scores', empty: SCORES_EMPTY, populated: SCORES },
	{ path: /^\/api\/risk\/scores\/[^/]+$/, empty: SINGLE_EMPTY, populated: SINGLE },
];
