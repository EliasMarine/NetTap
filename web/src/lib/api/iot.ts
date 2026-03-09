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
