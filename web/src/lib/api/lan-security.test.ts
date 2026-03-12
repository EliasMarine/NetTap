import { describe, it, expect, vi, afterEach } from 'vitest';
import { getLanAnomalies, getArpSpoofing, getRogueDhcp } from './lan-security';

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

describe('LAN security API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	describe('getLanAnomalies', () => {
		it('returns anomalies on success', async () => {
			mockFetchSuccess({
				from: '', to: '',
				anomalies: [
					{ type: 'arp_spoofing', severity: 'high', description: 'ARP spoof', detected_at: '2026-01-01', ip: '192.168.1.1', mac_addresses: ['AA:BB', 'CC:DD'] },
				],
				count: 1,
			});

			const result = await getLanAnomalies();
			expect(result.anomalies).toHaveLength(1);
			expect(result.count).toBe(1);
		});

		it('returns empty on failure', async () => {
			mockFetchFailure();
			const result = await getLanAnomalies();
			expect(result.anomalies).toEqual([]);
		});

		it('passes time range params', async () => {
			mockFetchSuccess({ from: '', to: '', anomalies: [], count: 0 });
			await getLanAnomalies({ from: '2026-01-01T00:00:00Z', to: '2026-01-02T00:00:00Z' });
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('from=');
			expect(url).toContain('to=');
		});
	});

	describe('getArpSpoofing', () => {
		it('returns alerts on success', async () => {
			mockFetchSuccess({
				from: '', to: '',
				alerts: [
					{ type: 'arp_spoofing', severity: 'high', description: 'spoof', detected_at: '2026-01-01' },
				],
				count: 1,
			});

			const result = await getArpSpoofing();
			expect(result.alerts).toHaveLength(1);
		});

		it('returns empty on failure', async () => {
			mockFetchFailure();
			const result = await getArpSpoofing();
			expect(result.alerts).toEqual([]);
		});
	});

	describe('getRogueDhcp', () => {
		it('returns alerts on success', async () => {
			mockFetchSuccess({
				from: '', to: '',
				alerts: [
					{ type: 'rogue_dhcp', severity: 'critical', description: 'Rogue DHCP', detected_at: '2026-01-01', server_ip: '192.168.1.99' },
				],
				count: 1,
			});

			const result = await getRogueDhcp();
			expect(result.alerts).toHaveLength(1);
			expect(result.alerts[0].server_ip).toBe('192.168.1.99');
		});

		it('returns empty on failure', async () => {
			mockFetchFailure();
			const result = await getRogueDhcp();
			expect(result.alerts).toEqual([]);
		});
	});
});
