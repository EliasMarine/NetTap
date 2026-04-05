/**
 * Client-side API helpers for IoT monitoring endpoints.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface IoTDevice {
	mac: string;
	manufacturer: string;
	hostname: string | null;
	ip: string | null;
	classified_at: string;
	is_iot: boolean;
}

export interface DeviceBaseline {
	mac: string;
	built_at: string;
	period_days: number;
	known_destinations: string[];
	known_ports: number[];
	known_protocols: string[];
	known_countries: string[];
	active_hours: number[];
	total_bytes: number;
	daily_avg_bytes: number;
	connection_count: number;
}

export interface IoTAnomaly {
	type: string;
	mac: string;
	detail: string;
	count?: number;
	severity: string;
	description: string;
	detected_at: string;
}

// Fleet Summary
export interface FleetSummary {
	health_score: number;
	health_grade: string;
	privacy_score: number;
	security_score: number;
	behavior_score: number;
	device_count: number;
	anomaly_count: number;
	privacy_concerns: number;
	unencrypted_count: number;
	subtitle: string;
	devices: FleetDevice[];
}

export interface FleetDevice {
	mac: string;
	name: string;
	manufacturer: string;
	ip: string | null;
	score: number;
	grade: string;
	privacy_score: number;
	security_score: number;
	behavior_score: number;
	anomaly_count: number;
	encryption_pct: number;
	tracker_count: number;
	last_seen: string | null;
}

// Privacy Report
export interface PrivacyReport {
	devices: PrivacyDevice[];
}

export interface PrivacyDevice {
	mac: string;
	name: string;
	privacy_grade: string;
	privacy_score: number;
	tracker_domains: { domain: string; query_count: number }[];
	tracker_count: number;
	telemetry_bytes: number;
	third_party_orgs: number;
	encryption_ratio: number;
	phone_home_per_hour: number;
}

// Communication Map
export interface CommunicationMap {
	mac: string;
	destinations: Destination[];
}

export interface Destination {
	ip: string;
	hostname: string | null;
	country: string | null;
	ports: number[];
	bytes_sent: number;
	bytes_received: number;
	connection_count: number;
	first_seen: string;
	last_seen: string;
	in_baseline: boolean;
}

// Activity Timeline
export interface ActivityTimeline {
	mac: string;
	interval: string;
	buckets: TimelineBucket[];
	baseline_hours: number[];
	baseline_avg_hourly_bytes: number;
}

export interface TimelineBucket {
	time: string;
	connections: number;
	bytes: number;
	destinations: number;
}

// Protocol Audit
export interface ProtocolAudit {
	devices: ProtocolDevice[];
}

export interface ProtocolDevice {
	mac: string;
	name: string;
	category: string;
	findings: ProtocolFinding[];
	violation_count: number;
	compliant: boolean;
}

export interface ProtocolFinding {
	type: string;
	severity: string;
	port?: number;
	protocol?: string;
	connection_count?: number;
	description: string;
}

// Network Isolation
export interface NetworkIsolation {
	segmentation_score: number;
	segmentation_grade: string;
	pairs: IsolationPair[];
	recommendation: string;
}

export interface IsolationPair {
	iot_device: { mac: string; name: string; ip: string };
	internal_target: { ip: string; hostname: string | null };
	risk: string;
	connection_count: number;
	ports: number[];
	description: string;
}

// Manufacturer Profiles
export interface ManufacturerProfilesResponse {
	manufacturers: ManufacturerProfile[];
}

export interface ManufacturerProfile {
	name: string;
	device_count: number;
	avg_trust_score: number;
	avg_trust_grade: string;
	avg_privacy_grade: string;
	encryption_pct: number;
	total_tracker_domains: number;
	total_violations: number;
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | number | undefined>): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== '') {
			qs.set(key, String(value));
		}
	}
	const str = qs.toString();
	return str ? `?${str}` : '';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

export async function getIoTDevices(): Promise<{ devices: IoTDevice[]; count: number }> {
	const res = await fetch('/api/iot/devices');

	if (!res.ok) {
		return { devices: [], count: 0 };
	}

	return res.json();
}

export async function getDeviceBaseline(
	mac: string
): Promise<{ mac: string; baseline: DeviceBaseline | null }> {
	const res = await fetch(`/api/iot/devices/${encodeURIComponent(mac)}/baseline`);

	if (!res.ok) {
		return { mac, baseline: null };
	}

	return res.json();
}

export async function getIoTAnomalies(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; anomalies: IoTAnomaly[]; count: number }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/iot/anomalies${query}`);

	if (!res.ok) {
		return { from: '', to: '', anomalies: [], count: 0 };
	}

	return res.json();
}

export async function classifyDevice(
	mac: string,
	info: { manufacturer?: string; hostname?: string }
): Promise<{ mac: string; is_iot: boolean; message: string }> {
	const res = await fetch(`/api/iot/devices/${encodeURIComponent(mac)}/classify`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(info),
	});

	if (!res.ok) {
		throw new Error(`Failed to classify device: ${res.status}`);
	}

	return res.json();
}

export async function getFleetSummary(
	opts: { from?: string; to?: string } = {}
): Promise<FleetSummary> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/iot/fleet-summary${query}`);

	if (!res.ok) {
		return {
			health_score: 0,
			health_grade: 'F',
			privacy_score: 0,
			security_score: 0,
			behavior_score: 0,
			device_count: 0,
			anomaly_count: 0,
			privacy_concerns: 0,
			unencrypted_count: 0,
			subtitle: '',
			devices: [],
		};
	}

	return res.json();
}

export async function getPrivacyReport(
	opts: { from?: string; to?: string } = {}
): Promise<PrivacyReport> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/iot/privacy-report${query}`);

	if (!res.ok) {
		return { devices: [] };
	}

	return res.json();
}

export async function getCommunicationMap(
	mac: string,
	opts: { from?: string; to?: string } = {}
): Promise<CommunicationMap> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/iot/devices/${encodeURIComponent(mac)}/communication-map${query}`);

	if (!res.ok) {
		return { mac, destinations: [] };
	}

	return res.json();
}

export async function getActivityTimeline(
	mac: string,
	opts: { from?: string; to?: string } = {}
): Promise<ActivityTimeline> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/iot/devices/${encodeURIComponent(mac)}/activity-timeline${query}`);

	if (!res.ok) {
		return { mac, interval: '1h', buckets: [], baseline_hours: [], baseline_avg_hourly_bytes: 0 };
	}

	return res.json();
}

export async function getProtocolAudit(
	opts: { from?: string; to?: string } = {}
): Promise<ProtocolAudit> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/iot/protocol-audit${query}`);

	if (!res.ok) {
		return { devices: [] };
	}

	return res.json();
}

export async function getNetworkIsolation(
	opts: { from?: string; to?: string } = {}
): Promise<NetworkIsolation> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/iot/network-isolation${query}`);

	if (!res.ok) {
		return { segmentation_score: 0, segmentation_grade: 'F', pairs: [], recommendation: '' };
	}

	return res.json();
}

export async function getManufacturerProfiles(
	opts: { from?: string; to?: string } = {}
): Promise<ManufacturerProfilesResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/iot/manufacturer-profiles${query}`);

	if (!res.ok) {
		return { manufacturers: [] };
	}

	return res.json();
}
