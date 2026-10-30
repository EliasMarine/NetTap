import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getIoTDevices,
	getDeviceBaseline,
	getIoTAnomalies,
	classifyDevice,
	getFleetSummary,
	getPrivacyReport,
	getCommunicationMap,
	getActivityTimeline,
	getProtocolAudit,
	getNetworkIsolation,
	getManufacturerProfiles,
} from './iot';

function mockFetchSuccess(body: unknown): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: () => Promise.resolve(body),
		}),
	);
}

function mockFetchFailure(status = 500): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.reject(new Error('no body')),
		}),
	);
}

describe('IoT API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	describe('getIoTDevices', () => {
		it('returns device list on success', async () => {
			mockFetchSuccess({
				devices: [
					{ mac: 'AA:BB:CC:DD:EE:FF', manufacturer: 'Ring', hostname: null, ip: '192.168.1.50', classified_at: '2026-01-01', is_iot: true },
				],
				count: 1,
			});

			const result = await getIoTDevices();
			expect(result.devices).toHaveLength(1);
			expect(result.count).toBe(1);
		});

		it('returns empty on failure', async () => {
			mockFetchFailure();
			const result = await getIoTDevices();
			expect(result.devices).toEqual([]);
		});
	});

	describe('getDeviceBaseline', () => {
		it('returns baseline on success', async () => {
			mockFetchSuccess({
				mac: 'AA:BB:CC:DD:EE:FF',
				baseline: {
					mac: 'AA:BB:CC:DD:EE:FF',
					built_at: '2026-01-01',
					period_days: 14,
					known_destinations: ['8.8.8.8'],
					known_ports: [443],
					known_protocols: ['tcp'],
					known_countries: ['United States'],
					active_hours: [8, 9, 10],
					total_bytes: 5000000,
					daily_avg_bytes: 357142,
					connection_count: 1000,
				},
			});

			const result = await getDeviceBaseline('AA:BB:CC:DD:EE:FF');
			expect(result.baseline).not.toBeNull();
			expect(result.baseline?.known_destinations).toContain('8.8.8.8');
		});

		it('returns null baseline on failure', async () => {
			mockFetchFailure();
			const result = await getDeviceBaseline('FF:FF:FF:FF:FF:FF');
			expect(result.baseline).toBeNull();
		});
	});

	describe('getIoTAnomalies', () => {
		it('returns anomalies on success', async () => {
			mockFetchSuccess({
				from: '', to: '',
				anomalies: [
					{ type: 'NEW_DESTINATION', mac: 'AA:BB:CC:DD:EE:FF', detail: '185.100.87.202', severity: 'medium', description: 'New dest', detected_at: '2026-01-01' },
				],
				count: 1,
			});

			const result = await getIoTAnomalies();
			expect(result.anomalies).toHaveLength(1);
			expect(result.anomalies[0].type).toBe('NEW_DESTINATION');
		});

		it('returns empty on failure', async () => {
			mockFetchFailure();
			const result = await getIoTAnomalies();
			expect(result.anomalies).toEqual([]);
		});
	});

	describe('classifyDevice', () => {
		it('sends POST and returns classification', async () => {
			mockFetchSuccess({ mac: 'AA:BB:CC', is_iot: true, message: 'classified' });

			const result = await classifyDevice('AA:BB:CC', { manufacturer: 'Ring' });
			expect(result.is_iot).toBe(true);
			expect(fetch).toHaveBeenCalledWith(
				expect.stringContaining('/api/iot/devices/'),
				expect.objectContaining({ method: 'POST' }),
			);
		});

		it('throws on failure', async () => {
			mockFetchFailure(400);
			await expect(classifyDevice('AA:BB:CC', {})).rejects.toThrow();
		});
	});

	describe('getFleetSummary', () => {
		it('returns fleet summary on success', async () => {
			mockFetchSuccess({
				health_score: 85,
				health_grade: 'B',
				privacy_score: 78,
				security_score: 90,
				behavior_score: 88,
				device_count: 5,
				anomaly_count: 2,
				privacy_concerns: 1,
				unencrypted_count: 0,
				subtitle: '5 devices monitored',
				devices: [
					{ mac: 'AA:BB:CC:DD:EE:FF', name: 'Ring Doorbell', manufacturer: 'Ring', ip: '192.168.1.50', score: 85, grade: 'B', privacy_score: 78, security_score: 90, behavior_score: 88, anomaly_count: 0, encryption_pct: 100, tracker_count: 2, last_seen: '2026-01-01T00:00:00Z' },
				],
			});

			const result = await getFleetSummary();
			expect(result.health_score).toBe(85);
			expect(result.health_grade).toBe('B');
			expect(result.device_count).toBe(5);
			expect(result.devices).toHaveLength(1);
			expect(result.devices[0].mac).toBe('AA:BB:CC:DD:EE:FF');
		});

		it('passes time range params', async () => {
			mockFetchSuccess({ health_score: 85, health_grade: 'B', privacy_score: 0, security_score: 0, behavior_score: 0, device_count: 0, anomaly_count: 0, privacy_concerns: 0, unencrypted_count: 0, subtitle: '', devices: [] });

			await getFleetSummary({ from: 'now-7d', to: 'now' });
			expect(fetch).toHaveBeenCalledWith(expect.stringContaining('from=now-7d'));
		});

		it('returns defaults on failure', async () => {
			mockFetchFailure();
			const result = await getFleetSummary();
			expect(result.health_score).toBe(0);
			expect(result.health_grade).toBe('F');
			expect(result.devices).toEqual([]);
		});
	});

	describe('getPrivacyReport', () => {
		it('returns privacy report on success', async () => {
			mockFetchSuccess({
				devices: [
					{ mac: 'AA:BB:CC:DD:EE:FF', name: 'Ring Doorbell', privacy_grade: 'C', privacy_score: 55, tracker_domains: [{ domain: 'tracker.example.com', query_count: 42 }], tracker_count: 1, telemetry_bytes: 50000, third_party_orgs: 3, encryption_ratio: 0.95, phone_home_per_hour: 12 },
				],
			});

			const result = await getPrivacyReport();
			expect(result.devices).toHaveLength(1);
			expect(result.devices[0].privacy_grade).toBe('C');
			expect(result.devices[0].tracker_domains).toHaveLength(1);
		});

		it('returns empty devices on failure', async () => {
			mockFetchFailure();
			const result = await getPrivacyReport();
			expect(result.devices).toEqual([]);
		});
	});

	describe('getCommunicationMap', () => {
		it('returns communication map on success', async () => {
			mockFetchSuccess({
				mac: 'AA:BB:CC:DD:EE:FF',
				destinations: [
					{ ip: '8.8.8.8', hostname: 'dns.google', country: 'US', ports: [443], bytes_sent: 1000, bytes_received: 5000, connection_count: 10, first_seen: '2026-01-01', last_seen: '2026-01-02', in_baseline: true },
				],
			});

			const result = await getCommunicationMap('AA:BB:CC:DD:EE:FF');
			expect(result.mac).toBe('AA:BB:CC:DD:EE:FF');
			expect(result.destinations).toHaveLength(1);
			expect(result.destinations[0].hostname).toBe('dns.google');
		});

		it('encodes mac in URL', async () => {
			mockFetchSuccess({ mac: 'AA:BB:CC:DD:EE:FF', destinations: [] });
			await getCommunicationMap('AA:BB:CC:DD:EE:FF');
			expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/iot/devices/AA%3ABB%3ACC%3ADD%3AEE%3AFF/communication-map'));
		});

		it('returns empty destinations on failure', async () => {
			mockFetchFailure();
			const result = await getCommunicationMap('AA:BB:CC:DD:EE:FF');
			expect(result.mac).toBe('AA:BB:CC:DD:EE:FF');
			expect(result.destinations).toEqual([]);
		});
	});

	describe('getActivityTimeline', () => {
		it('returns activity timeline on success', async () => {
			mockFetchSuccess({
				mac: 'AA:BB:CC:DD:EE:FF',
				interval: '1h',
				buckets: [
					{ time: '2026-01-01T00:00:00Z', connections: 5, bytes: 10000, destinations: 3 },
				],
				baseline_hours: [8, 9, 10, 11],
				baseline_avg_hourly_bytes: 5000,
			});

			const result = await getActivityTimeline('AA:BB:CC:DD:EE:FF');
			expect(result.mac).toBe('AA:BB:CC:DD:EE:FF');
			expect(result.interval).toBe('1h');
			expect(result.buckets).toHaveLength(1);
			expect(result.baseline_hours).toContain(8);
		});

		it('returns defaults on failure', async () => {
			mockFetchFailure();
			const result = await getActivityTimeline('AA:BB:CC:DD:EE:FF');
			expect(result.mac).toBe('AA:BB:CC:DD:EE:FF');
			expect(result.buckets).toEqual([]);
			expect(result.baseline_avg_hourly_bytes).toBe(0);
		});
	});

	describe('getProtocolAudit', () => {
		it('returns protocol audit on success', async () => {
			mockFetchSuccess({
				devices: [
					{ mac: 'AA:BB:CC:DD:EE:FF', name: 'Ring Doorbell', category: 'camera', findings: [{ type: 'UNENCRYPTED', severity: 'high', port: 80, protocol: 'HTTP', connection_count: 5, description: 'Unencrypted HTTP traffic' }], violation_count: 1, compliant: false },
				],
			});

			const result = await getProtocolAudit();
			expect(result.devices).toHaveLength(1);
			expect(result.devices[0].compliant).toBe(false);
			expect(result.devices[0].findings).toHaveLength(1);
			expect(result.devices[0].findings[0].type).toBe('UNENCRYPTED');
		});

		it('returns empty devices on failure', async () => {
			mockFetchFailure();
			const result = await getProtocolAudit();
			expect(result.devices).toEqual([]);
		});
	});

	describe('getNetworkIsolation', () => {
		it('returns network isolation on success', async () => {
			mockFetchSuccess({
				segmentation_score: 72,
				segmentation_grade: 'C',
				pairs: [
					{ iot_device: { mac: 'AA:BB:CC:DD:EE:FF', name: 'Ring Doorbell', ip: '192.168.1.50' }, internal_target: { ip: '192.168.1.1', hostname: 'router.local' }, risk: 'medium', connection_count: 15, ports: [80, 443], description: 'IoT device accessing router admin' },
				],
				recommendation: 'Consider VLAN segmentation',
			});

			const result = await getNetworkIsolation();
			expect(result.segmentation_score).toBe(72);
			expect(result.segmentation_grade).toBe('C');
			expect(result.pairs).toHaveLength(1);
			expect(result.pairs[0].risk).toBe('medium');
			expect(result.recommendation).toBe('Consider VLAN segmentation');
		});

		it('returns defaults on failure', async () => {
			mockFetchFailure();
			const result = await getNetworkIsolation();
			expect(result.segmentation_score).toBe(0);
			expect(result.segmentation_grade).toBe('F');
			expect(result.pairs).toEqual([]);
			expect(result.recommendation).toBe('');
		});
	});

	describe('getManufacturerProfiles', () => {
		it('returns manufacturer profiles on success', async () => {
			mockFetchSuccess({
				manufacturers: [
					{ name: 'Ring', device_count: 3, avg_trust_score: 72, avg_trust_grade: 'C', avg_privacy_grade: 'D', encryption_pct: 95, total_tracker_domains: 5, total_violations: 2 },
				],
			});

			const result = await getManufacturerProfiles();
			expect(result.manufacturers).toHaveLength(1);
			expect(result.manufacturers[0].name).toBe('Ring');
			expect(result.manufacturers[0].avg_trust_score).toBe(72);
		});

		it('returns empty manufacturers on failure', async () => {
			mockFetchFailure();
			const result = await getManufacturerProfiles();
			expect(result.manufacturers).toEqual([]);
		});
	});
});
