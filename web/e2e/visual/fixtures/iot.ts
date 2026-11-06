import type {
	ActivityTimeline,
	CommunicationMap,
	FleetDevice,
	FleetSummary,
	ManufacturerProfilesResponse,
	NetworkIsolation,
	PrivacyDevice,
	PrivacyReport,
	ProtocolAudit,
} from '../../../src/lib/api/iot.ts';
import { DAY, iso, type FixtureRoute } from './types.ts';
import { MB, hourBucket, hourly, lanDevice, sum, type LanDevice } from './net-world.ts';

const grade = (score: number): string =>
	score >= 90 ? 'A' : score >= 75 ? 'B' : score >= 60 ? 'C' : score >= 40 ? 'D' : 'F';
const avg = (xs: readonly number[]): number => Math.round(sum(xs) / xs.length);

interface IotProfile {
	device: LanDevice;
	privacy: number;
	security: number;
	behavior: number;
	anomalies: number;
	/** share of external connections that were encrypted, 0..1 */
	encryption: number;
	trackerDomains: string[];
	telemetryBytes: number;
	thirdPartyOrgs: number;
	phoneHomePerHour: number;
}

const PROFILES: readonly IotProfile[] = [
	{
		device: lanDevice('192.168.1.50'),
		privacy: 52,
		security: 55,
		behavior: 70,
		anomalies: 2,
		encryption: 0.62,
		trackerDomains: ['telemetry.example.org', 'metrics.example.net', 'beacon.example.org', 'pixel.example.net'],
		telemetryBytes: 410 * MB,
		thirdPartyOrgs: 3,
		phoneHomePerHour: 85,
	},
	{
		device: lanDevice('192.168.1.22'),
		privacy: 61,
		security: 78,
		behavior: 84,
		anomalies: 0,
		encryption: 0.91,
		trackerDomains: ['ads.example.net', 'tracker.example.org', 'metrics.example.net', 'beacon.example.org', 'analytics.example.com', 'pixel.example.net', 'insights.example.org'],
		telemetryBytes: 180 * MB,
		thirdPartyOrgs: 6,
		phoneHomePerHour: 24,
	},
	{
		device: lanDevice('192.168.1.31'),
		privacy: 92,
		security: 90,
		behavior: 96,
		anomalies: 0,
		encryption: 1,
		trackerDomains: [],
		telemetryBytes: 2 * MB,
		thirdPartyOrgs: 1,
		phoneHomePerHour: 6,
	},
];

const trustScore = (p: IotProfile): number => avg([p.privacy, p.security, p.behavior]);

const fleetDevice = (p: IotProfile): FleetDevice => ({
	mac: p.device.mac,
	name: p.device.hostname,
	manufacturer: p.device.vendor,
	ip: p.device.ip,
	score: trustScore(p),
	grade: grade(trustScore(p)),
	// NET-158: five measured checks (trackers, third parties, encryption, ports, alerts)
	coverage: 55,
	checks_available: 5,
	checks_total: 11,
	privacy_score: p.privacy,
	security_score: p.security,
	behavior_score: p.behavior,
	anomaly_count: p.anomalies,
	encryption_pct: Math.round(p.encryption * 100),
	tracker_count: p.trackerDomains.length,
	last_seen: iso(p.device.lastSeenAgo),
});

const fleetScore = avg(PROFILES.map(trustScore));
const anomalyCount = sum(PROFILES.map((p) => p.anomalies));
const privacyConcerns = PROFILES.filter((p) => p.privacy < 65).length;

const fleet = (): FleetSummary => ({
	health_score: fleetScore,
	health_grade: grade(fleetScore),
	privacy_score: avg(PROFILES.map((p) => p.privacy)),
	security_score: avg(PROFILES.map((p) => p.security)),
	behavior_score: avg(PROFILES.map((p) => p.behavior)),
	device_count: PROFILES.length,
	scored_device_count: PROFILES.length,
	anomaly_count: anomalyCount,
	anomalies_checked: PROFILES.length,
	privacy_concerns: privacyConcerns,
	unencrypted_count: PROFILES.filter((p) => p.encryption < 0.9).length,
	subtitle: `Your smart home is mostly healthy. ${anomalyCount} anomalies detected. ${privacyConcerns} devices have privacy concerns.`,
	devices: PROFILES.map(fleetDevice),
});

const privacyDevice = (p: IotProfile): PrivacyDevice => ({
	mac: p.device.mac,
	name: p.device.hostname,
	privacy_grade: grade(p.privacy),
	privacy_score: p.privacy,
	tracker_domains: p.trackerDomains.map((domain, i) => ({ domain, query_count: 140 - i * 17 })),
	tracker_count: p.trackerDomains.length,
	tracker_lookup_share: p.trackerDomains.length > 0 ? 0.2 : 0,
	third_party_orgs: p.thirdPartyOrgs,
	encryption_ratio: p.encryption,
	phone_home_per_hour: p.phoneHomePerHour,
});

const camera = PROFILES[0].device;

const protocolAudit = (): ProtocolAudit => ({
	devices: [
		{
			mac: camera.mac,
			name: camera.hostname,
			category: 'camera',
			findings: [
				{
					type: 'unexpected_port',
					severity: 'medium',
					port: 8883,
					connection_count: 3,
					description: 'Uses port 8883 which is not expected for a camera',
				},
				{
					type: 'hardcoded_dns',
					severity: 'medium',
					port: 53,
					connection_count: 120,
					description: 'Sends DNS queries directly to 198.51.100.53 instead of using network DNS',
				},
			],
			violation_count: 2,
			compliant: false,
		},
		...PROFILES.slice(1).map((p) => ({
			mac: p.device.mac,
			name: p.device.hostname,
			category: p.device.ip === '192.168.1.22' ? 'tv' : 'thermostat',
			findings: [],
			violation_count: 0,
			compliant: true,
		})),
	],
});

const isolation = (): NetworkIsolation => ({
	segmentation_score: 72,
	segmentation_grade: 'C',
	pairs: [
		{
			iot_device: { mac: camera.mac, name: camera.hostname, ip: camera.ip },
			internal_target: { ip: '192.168.1.30', hostname: 'desktop-02.example.com' },
			risk: 'high',
			connection_count: 46,
			ports: [8080],
			description: `${camera.hostname} can reach 192.168.1.30 via port 8080`,
		},
		{
			iot_device: { mac: PROFILES[1].device.mac, name: PROFILES[1].device.hostname, ip: PROFILES[1].device.ip },
			internal_target: { ip: '192.168.1.20', hostname: 'laptop-01.example.com' },
			risk: 'medium',
			connection_count: 12,
			ports: [7000],
			description: `${PROFILES[1].device.hostname} can reach 192.168.1.20 via port 7000`,
		},
	],
	recommendation: 'Move IoT devices to a separate VLAN or guest network to limit their reach into your main network.',
});

const manufacturers = (): ManufacturerProfilesResponse => ({
	manufacturers: PROFILES.map((p) => ({
		name: p.device.vendor,
		device_count: 1,
		scored_device_count: 1,
		avg_trust_score: trustScore(p),
		avg_trust_grade: grade(trustScore(p)),
		avg_privacy_grade: grade(p.privacy),
		encryption_pct: Math.round(p.encryption * 100),
		total_tracker_domains: p.trackerDomains.length,
		total_violations: p.device.ip === camera.ip ? 2 : 0,
	})),
});

// ---- the drawer's two per-device calls (open on a device card) -------------------------------

const communicationMap = (): CommunicationMap => ({
	mac: camera.mac,
	destinations: [
		{
			ip: '192.0.2.80',
			hostname: 'telemetry.example.org',
			country: 'SG',
			ports: [443],
			bytes_sent: 2150 * MB,
			bytes_received: 60 * MB,
			connection_count: 640,
			first_seen: iso(DAY),
			last_seen: iso(camera.lastSeenAgo),
			in_baseline: true,
		},
		{
			ip: '203.0.113.15',
			hostname: 'api.example.org',
			country: 'DE',
			ports: [8883],
			bytes_sent: 1 * MB,
			bytes_received: 0,
			connection_count: 3,
			first_seen: iso(3 * 60 * 60 * 1000),
			last_seen: iso(40 * 60 * 1000),
			in_baseline: false,
		},
	],
});

const activityTimeline = (): ActivityTimeline => ({
	mac: camera.mac,
	interval: '1h',
	buckets: hourly((i, share) => ({
		time: hourBucket(i),
		connections: Math.round(camera.connections * share),
		bytes: Math.round((camera.origBytes + camera.respBytes) * share),
		destinations: i % 6 === 5 ? 2 : 1,
	})),
	baseline_hours: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21],
	baseline_avg_hourly_bytes: Math.round((camera.origBytes + camera.respBytes) / 24),
});

export const IOT_ROUTES: FixtureRoute[] = [
	{
		// the daemon's own empty fleet: nothing measured, so no score (NET-158; it read 100 / A)
		path: '/api/iot/fleet-summary',
		empty: {
			health_score: null,
			health_grade: null,
			privacy_score: null,
			security_score: null,
			behavior_score: null,
			device_count: 0,
			scored_device_count: 0,
			anomaly_count: 0,
			anomalies_checked: 0,
			privacy_concerns: 0,
			unencrypted_count: 0,
			subtitle: 'No IoT devices detected yet.',
			devices: [],
		} satisfies FleetSummary,
		populated: fleet(),
	},
	{
		path: '/api/iot/privacy-report',
		empty: { devices: [] } satisfies PrivacyReport,
		populated: { devices: PROFILES.map(privacyDevice) } satisfies PrivacyReport,
	},
	{
		path: '/api/iot/protocol-audit',
		empty: { devices: [] } satisfies ProtocolAudit,
		populated: protocolAudit(),
	},
	{
		path: '/api/iot/network-isolation',
		empty: {
			segmentation_score: 100,
			segmentation_grade: 'A',
			pairs: [],
			recommendation: 'No IoT devices detected yet.',
		} satisfies NetworkIsolation,
		populated: isolation(),
	},
	{
		path: '/api/iot/manufacturer-profiles',
		empty: { manufacturers: [] } satisfies ManufacturerProfilesResponse,
		populated: manufacturers(),
	},
	{
		path: /^\/api\/iot\/devices\/[^/]+\/communication-map$/,
		empty: { mac: camera.mac, destinations: [] } satisfies CommunicationMap,
		populated: communicationMap(),
	},
	{
		path: /^\/api\/iot\/devices\/[^/]+\/activity-timeline$/,
		empty: {
			mac: camera.mac,
			interval: '1h',
			buckets: [],
			baseline_hours: [],
			baseline_avg_hourly_bytes: 0,
		} satisfies ActivityTimeline,
		populated: activityTimeline(),
	},
];
