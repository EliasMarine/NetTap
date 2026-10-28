import { describe, it, expect, vi, afterEach } from 'vitest';
import { getChangelogEvents, getEventTypes } from './changelog';

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

function mockFetchReject(): void {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network error')));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('changelog API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getChangelogEvents ---------------------------------------------------

	describe('getChangelogEvents', () => {
		it('returns events on success', async () => {
			mockFetchSuccess({
				events: [
					{
						_id: 'evt-1',
						'@timestamp': '2026-03-08T10:00:00Z',
						event_type: 'device_joined',
						title: 'New device',
					},
				],
				count: 1,
			});

			const result = await getChangelogEvents();
			expect(result.count).toBe(1);
			expect(result.events[0].event_type).toBe('device_joined');
		});

		it('passes query parameters', async () => {
			const fetchMock = vi.fn().mockResolvedValue({
				ok: true,
				json: () => Promise.resolve({ events: [], count: 0 }),
			});
			vi.stubGlobal('fetch', fetchMock);

			await getChangelogEvents({
				from: '2026-03-01T00:00:00Z',
				to: '2026-03-08T00:00:00Z',
				type: 'alert_triggered',
				limit: 50,
			});

			const calledUrl = fetchMock.mock.calls[0][0] as string;
			expect(calledUrl).toContain('from=');
			expect(calledUrl).toContain('to=');
			expect(calledUrl).toContain('type=alert_triggered');
			expect(calledUrl).toContain('limit=50');
		});

		it('returns empty on HTTP error', async () => {
			mockFetchFailure();
			const result = await getChangelogEvents();
			expect(result.events).toEqual([]);
		});

		it('returns empty on network error', async () => {
			mockFetchReject();
			const result = await getChangelogEvents();
			expect(result.events).toEqual([]);
		});
	});

	// -- getEventTypes --------------------------------------------------------

	describe('getEventTypes', () => {
		it('returns types on success', async () => {
			mockFetchSuccess({ event_types: ['device_joined', 'alert_triggered'] });

			const types = await getEventTypes();
			expect(types).toEqual(['device_joined', 'alert_triggered']);
		});

		it('returns empty on error', async () => {
			mockFetchFailure();
			const types = await getEventTypes();
			expect(types).toEqual([]);
		});

		it('returns empty on network error', async () => {
			mockFetchReject();
			const types = await getEventTypes();
			expect(types).toEqual([]);
		});
	});
});
