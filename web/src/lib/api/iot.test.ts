import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getIoTDevices,
	getDeviceBaseline,
	getIoTAnomalies,
	classifyDevice,
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
});
