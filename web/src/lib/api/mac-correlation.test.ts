import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getRandomizedMacs,
	getFingerprint,
	getMergeSuggestions,
	mergeDevices,
	getMergeHistory,
	undoMerge,
} from './mac-correlation';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('mac-correlation API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getRandomizedMacs ------------------------------------------------

	describe('getRandomizedMacs', () => {
		it('returns parsed data on success', async () => {
			const expected = {
				from: '2026-03-01T00:00:00Z',
				to: '2026-03-08T00:00:00Z',
				count: 1,
				randomized_macs: [
					{
						mac: '02:aa:bb:cc:dd:ee',
						connection_count: 100,
						first_seen: '2026-03-01T00:00:00Z',
						last_seen: '2026-03-08T00:00:00Z',
						total_bytes: 50000,
						top_destinations: ['8.8.8.8'],
					},
				],
			};
			mockFetchSuccess(expected);

			const result = await getRandomizedMacs();
			expect(result.count).toBe(1);
			expect(result.randomized_macs[0].mac).toBe('02:aa:bb:cc:dd:ee');
		});

		it('returns empty on failure', async () => {
			mockFetchFailure();
			const result = await getRandomizedMacs();
			expect(result.count).toBe(0);
			expect(result.randomized_macs).toEqual([]);
		});

		it('passes time range params', async () => {
			mockFetchSuccess({ from: '', to: '', count: 0, randomized_macs: [] });

			await getRandomizedMacs({ from: '2026-03-01', to: '2026-03-08' });
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('from=2026-03-01');
			expect(url).toContain('to=2026-03-08');
		});
	});

	// -- getFingerprint ---------------------------------------------------

	describe('getFingerprint', () => {
		it('returns fingerprint on success', async () => {
			const expected = {
				from: '',
				to: '',
				fingerprint: {
					mac: '02:aa:bb:cc:dd:ee',
					is_randomized: true,
					dns_patterns: [{ domain: 'google.com', count: 50 }],
					tls_fingerprints: [],
					destination_ips: [],
					timing_pattern: [],
					traffic_profile: {
						orig_bytes: 0,
						resp_bytes: 0,
						total_bytes: 0,
						orig_packets: 0,
						resp_packets: 0,
						avg_packet_size: 0,
					},
				},
			};
			mockFetchSuccess(expected);

			const result = await getFingerprint('02:aa:bb:cc:dd:ee');
			expect(result.fingerprint.mac).toBe('02:aa:bb:cc:dd:ee');
		});

		it('throws on failure', async () => {
			mockFetchFailure();
			await expect(getFingerprint('02:aa:bb:cc:dd:ee')).rejects.toThrow();
		});

		it('encodes MAC in URL', async () => {
			mockFetchSuccess({ from: '', to: '', fingerprint: {} });
			await getFingerprint('02:aa:bb:cc:dd:ee');
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('/api/mac/fingerprint/');
		});
	});

	// -- getMergeSuggestions -----------------------------------------------

	describe('getMergeSuggestions', () => {
		it('returns suggestions on success', async () => {
			mockFetchSuccess({
				from: '',
				to: '',
				count: 1,
				suggestions: [
					{
						mac_randomized: '02:aa:bb:cc:dd:ee',
						mac_real: '00:11:22:33:44:55',
						confidence: 0.85,
						confidence_level: 'high',
						shared_dns: ['google.com'],
						shared_ja3: [],
						shared_destinations: ['8.8.8.8'],
					},
				],
			});

			const result = await getMergeSuggestions();
			expect(result.count).toBe(1);
			expect(result.suggestions[0].confidence).toBe(0.85);
		});

		it('returns empty on failure', async () => {
			mockFetchFailure();
			const result = await getMergeSuggestions();
			expect(result.suggestions).toEqual([]);
		});
	});

	// -- mergeDevices -----------------------------------------------------

	describe('mergeDevices', () => {
		it('sends correct body', async () => {
			mockFetchSuccess({
				result: 'merged',
				merge: { id: 'abc', mac_randomized: '02:aa', mac_real: '00:11', status: 'active' },
			});

			await mergeDevices('02:aa', '00:11');
			const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
			const body = JSON.parse(call[1].body);
			expect(body.mac_randomized).toBe('02:aa');
			expect(body.mac_real).toBe('00:11');
		});

		it('throws on failure', async () => {
			mockFetchFailure();
			await expect(mergeDevices('02:aa', '00:11')).rejects.toThrow();
		});
	});

	// -- getMergeHistory --------------------------------------------------

	describe('getMergeHistory', () => {
		it('returns history on success', async () => {
			mockFetchSuccess({ count: 2, merges: [{}, {}] });
			const result = await getMergeHistory();
			expect(result.count).toBe(2);
		});

		it('returns empty on failure', async () => {
			mockFetchFailure();
			const result = await getMergeHistory();
			expect(result.merges).toEqual([]);
		});
	});

	// -- undoMerge --------------------------------------------------------

	describe('undoMerge', () => {
		it('sends merge_id in body', async () => {
			mockFetchSuccess({ result: 'undone', merge_id: 'abc' });

			await undoMerge('abc');
			const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
			const body = JSON.parse(call[1].body);
			expect(body.merge_id).toBe('abc');
		});

		it('throws on failure', async () => {
			mockFetchFailure();
			await expect(undoMerge('abc')).rejects.toThrow();
		});
	});
});
