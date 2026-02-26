import { describe, it, expect, vi, afterEach } from 'vitest';
import { getRiskScores, getDeviceRiskScore } from './risk';

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
// Sample data
// ---------------------------------------------------------------------------

const sampleScore = {
	ip: '192.168.1.100',
	score: 72,
	level: 'high',
	factors: [
		{ name: 'alert_count', score: 30, max: 40, description: 'High number of IDS alerts' },
		{ name: 'external_connections', score: 22, max: 30, description: 'Many external connections' },
		{ name: 'unusual_ports', score: 20, max: 30, description: 'Connections on unusual ports' },
	],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('risk API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getRiskScores --------------------------------------------------------

	describe('getRiskScores', () => {
		it('returns parsed risk scores on success', async () => {
			const expected = { scores: [sampleScore] };
			mockFetchSuccess(expected);

			const result = await getRiskScores();

			expect(fetch).toHaveBeenCalledWith('/api/risk/scores');
			expect(result.scores).toHaveLength(1);
			expect(result.scores[0].ip).toBe('192.168.1.100');
			expect(result.scores[0].score).toBe(72);
		});

		it('returns scores array with multiple devices', async () => {
			const secondScore = { ...sampleScore, ip: '192.168.1.200', score: 35, level: 'medium' };
			mockFetchSuccess({ scores: [sampleScore, secondScore] });

			const result = await getRiskScores();

			expect(result.scores).toHaveLength(2);
			expect(result.scores[1].ip).toBe('192.168.1.200');
		});

		it('returns empty scores array on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getRiskScores();

			expect(result.scores).toEqual([]);
		});

		it('returns empty scores array on server error', async () => {
			mockFetchFailure(500);

			const result = await getRiskScores();

			expect(result.scores).toEqual([]);
		});

		it('includes risk factors in each score', async () => {
			mockFetchSuccess({ scores: [sampleScore] });

			const result = await getRiskScores();

			expect(result.scores[0].factors).toHaveLength(3);
			expect(result.scores[0].factors[0].name).toBe('alert_count');
			expect(result.scores[0].factors[0].score).toBe(30);
			expect(result.scores[0].factors[0].max).toBe(40);
		});

		it('includes the risk level for each device', async () => {
			mockFetchSuccess({ scores: [sampleScore] });

			const result = await getRiskScores();

			expect(result.scores[0].level).toBe('high');
		});
	});

	// -- getDeviceRiskScore ---------------------------------------------------

	describe('getDeviceRiskScore', () => {
		it('returns parsed risk score for a single device', async () => {
			mockFetchSuccess(sampleScore);

			const result = await getDeviceRiskScore('192.168.1.100');

			expect(fetch).toHaveBeenCalledWith('/api/risk/scores/192.168.1.100');
			expect(result).not.toBeNull();
			expect(result!.ip).toBe('192.168.1.100');
			expect(result!.score).toBe(72);
		});

		it('returns null on HTTP error', async () => {
			mockFetchFailure(404);

			const result = await getDeviceRiskScore('10.0.0.99');

			expect(result).toBeNull();
		});

		it('encodes the IP address in the URL', async () => {
			mockFetchSuccess(sampleScore);

			await getDeviceRiskScore('192.168.1.100');

			expect(fetch).toHaveBeenCalledWith('/api/risk/scores/192.168.1.100');
		});

		it('returns the factors breakdown for a device', async () => {
			mockFetchSuccess(sampleScore);

			const result = await getDeviceRiskScore('192.168.1.100');

			expect(result!.factors).toHaveLength(3);
			expect(result!.factors[2].name).toBe('unusual_ports');
			expect(result!.factors[2].description).toBe('Connections on unusual ports');
		});

		it('returns null on 502 gateway error', async () => {
			mockFetchFailure(502);

			const result = await getDeviceRiskScore('192.168.1.100');

			expect(result).toBeNull();
		});
	});
});
