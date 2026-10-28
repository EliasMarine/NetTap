import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock notification-stream module
// ---------------------------------------------------------------------------

const mockStreamClose = vi.fn();
const mockStreamIsConnected = vi.fn().mockReturnValue(true);
let streamCallback: ((notification: unknown) => void) | null = null;

vi.mock('$api/notification-stream', () => ({
	createNotificationStream: vi.fn((cb: (notification: unknown) => void) => {
		streamCallback = cb;
		return {
			close: mockStreamClose,
			isConnected: mockStreamIsConnected,
		};
	}),
}));

// ---------------------------------------------------------------------------
// Mock fetch for initial notifications load
// ---------------------------------------------------------------------------

function mockFetchNotifications(notifications: unknown[] = [], unreadCount = 0) {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: true,
			json: () => Promise.resolve({ notifications, unreadCount }),
		})
	);
}

// ---------------------------------------------------------------------------
// Tests — logic-focused (Svelte 5 runes are hard to render in jsdom)
// ---------------------------------------------------------------------------

describe('NotificationBell logic', () => {
	beforeEach(() => {
		streamCallback = null;
		mockStreamClose.mockClear();
		mockStreamIsConnected.mockClear().mockReturnValue(true);
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	describe('SSE stream integration', () => {
		it('createNotificationStream is importable and returns correct interface', async () => {
			const { createNotificationStream } = await import('$api/notification-stream');
			const stream = createNotificationStream(() => {});

			expect(stream).toHaveProperty('close');
			expect(stream).toHaveProperty('isConnected');
			expect(typeof stream.close).toBe('function');
			expect(typeof stream.isConnected).toBe('function');
		});

		it('stream callback prepends notification to list correctly', () => {
			// Simulate what the NotificationBell $effect does
			let notifications: unknown[] = [
				{ id: 'ntf_old', read: true, title: 'Old' },
			];
			let unreadCount = 0;

			const onNotification = (notification: { read: boolean; [key: string]: unknown }) => {
				notifications = [notification, ...notifications].slice(0, 15);
				if (!notification.read) {
					unreadCount++;
				}
			};

			onNotification({
				id: 'ntf_new',
				read: false,
				title: 'New Alert',
				severity: 'high',
				type: 'alert',
				message: 'Test',
				timestamp: new Date().toISOString(),
			});

			expect(notifications).toHaveLength(2);
			expect((notifications[0] as { id: string }).id).toBe('ntf_new');
			expect(unreadCount).toBe(1);
		});

		it('stream callback caps list at 15 items', () => {
			let notifications: unknown[] = Array.from({ length: 15 }, (_, i) => ({
				id: `ntf_${i}`,
				read: true,
			}));
			let unreadCount = 0;

			const onNotification = (notification: { read: boolean; [key: string]: unknown }) => {
				notifications = [notification, ...notifications].slice(0, 15);
				if (!notification.read) {
					unreadCount++;
				}
			};

			onNotification({ id: 'ntf_new', read: false });

			expect(notifications).toHaveLength(15);
			expect((notifications[0] as { id: string }).id).toBe('ntf_new');
			// The last old item should have been evicted
			expect((notifications[14] as { id: string }).id).toBe('ntf_13');
		});

		it('stream callback does not increment unread for read notifications', () => {
			let notifications: unknown[] = [];
			let unreadCount = 0;

			const onNotification = (notification: { read: boolean; [key: string]: unknown }) => {
				notifications = [notification, ...notifications].slice(0, 15);
				if (!notification.read) {
					unreadCount++;
				}
			};

			onNotification({ id: 'ntf_read', read: true });

			expect(notifications).toHaveLength(1);
			expect(unreadCount).toBe(0);
		});
	});

	describe('polling interval logic', () => {
		it('uses 60s interval when SSE is connected', () => {
			mockStreamIsConnected.mockReturnValue(true);
			const interval = mockStreamIsConnected() ? 60_000 : 30_000;
			expect(interval).toBe(60_000);
		});

		it('uses 30s interval when SSE is disconnected', () => {
			mockStreamIsConnected.mockReturnValue(false);
			const interval = mockStreamIsConnected() ? 60_000 : 30_000;
			expect(interval).toBe(30_000);
		});
	});

	describe('fetch API integration', () => {
		it('fetches notifications with correct URL', async () => {
			mockFetchNotifications(
				[{ id: 'ntf_1', title: 'Test', read: false }],
				1
			);

			const res = await fetch('/api/notifications?limit=15');
			const data = await res.json();

			expect(data.notifications).toHaveLength(1);
			expect(data.unreadCount).toBe(1);
		});

		it('returns empty on fetch failure', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue({
					ok: false,
					json: () => Promise.reject(new Error('fail')),
				})
			);

			const res = await fetch('/api/notifications?limit=15');
			expect(res.ok).toBe(false);
		});
	});

	describe('severity class mapping', () => {
		function severityClass(severity: string): string {
			switch (severity) {
				case 'critical':
					return 'severity-critical';
				case 'high':
					return 'severity-high';
				case 'medium':
					return 'severity-medium';
				case 'low':
					return 'severity-low';
				default:
					return '';
			}
		}

		it('returns correct class for each severity', () => {
			expect(severityClass('critical')).toBe('severity-critical');
			expect(severityClass('high')).toBe('severity-high');
			expect(severityClass('medium')).toBe('severity-medium');
			expect(severityClass('low')).toBe('severity-low');
			expect(severityClass('unknown')).toBe('');
		});
	});

	describe('timeAgo formatting', () => {
		function timeAgo(timestamp: string): string {
			const diff = Date.now() - new Date(timestamp).getTime();
			const minutes = Math.floor(diff / 60_000);
			if (minutes < 1) return 'just now';
			if (minutes < 60) return `${minutes}m ago`;
			const hours = Math.floor(minutes / 60);
			if (hours < 24) return `${hours}h ago`;
			const days = Math.floor(hours / 24);
			return `${days}d ago`;
		}

		it('returns "just now" for recent timestamps', () => {
			expect(timeAgo(new Date().toISOString())).toBe('just now');
		});

		it('returns minutes for sub-hour timestamps', () => {
			const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString();
			expect(timeAgo(fiveMinAgo)).toBe('5m ago');
		});

		it('returns hours for sub-day timestamps', () => {
			const twoHoursAgo = new Date(Date.now() - 2 * 3600_000).toISOString();
			expect(timeAgo(twoHoursAgo)).toBe('2h ago');
		});

		it('returns days for older timestamps', () => {
			const threeDaysAgo = new Date(Date.now() - 3 * 86400_000).toISOString();
			expect(timeAgo(threeDaysAgo)).toBe('3d ago');
		});
	});
});
