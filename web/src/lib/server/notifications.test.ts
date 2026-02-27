import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock fs module before importing the module under test
vi.mock('fs', async (importOriginal) => {
	const actual = await importOriginal<typeof import('fs')>();
	return {
		...actual,
		existsSync: vi.fn().mockReturnValue(false),
		readFileSync: vi.fn().mockReturnValue('[]'),
		writeFileSync: vi.fn(),
		mkdirSync: vi.fn(),
	};
});

// We need to dynamically import after mocking
let notifications: typeof import('./notifications');

describe('notifications server module', () => {
	beforeEach(async () => {
		vi.resetModules();
		// Reset env vars
		delete process.env.SMTP_HOST;
		delete process.env.SMTP_PORT;
		delete process.env.SMTP_USER;
		delete process.env.SMTP_PASS;
		delete process.env.SMTP_FROM;
		delete process.env.NOTIFY_EMAIL;
		delete process.env.NOTIFY_WEBHOOK_URL;
		delete process.env.NOTIFY_INAPP_ENABLED;
		delete process.env.NOTIFY_SEVERITY_THRESHOLD;

		// Re-import module to reset internal state
		notifications = await import('./notifications');
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	describe('loadConfig', () => {
		it('returns default config when no env vars set', () => {
			const config = notifications.loadConfig();

			expect(config.email.enabled).toBe(false);
			expect(config.email.smtpHost).toBe('');
			expect(config.email.smtpPort).toBe(587);
			expect(config.email.recipients).toEqual([]);
			expect(config.webhook.enabled).toBe(false);
			expect(config.inApp.enabled).toBe(true);
			expect(config.severityThreshold).toBe(3);
		});

		it('enables email when SMTP_HOST and NOTIFY_EMAIL are set', () => {
			process.env.SMTP_HOST = 'smtp.test.com';
			process.env.NOTIFY_EMAIL = 'admin@test.com, ops@test.com';

			const config = notifications.loadConfig();

			expect(config.email.enabled).toBe(true);
			expect(config.email.smtpHost).toBe('smtp.test.com');
			expect(config.email.recipients).toEqual(['admin@test.com', 'ops@test.com']);
		});

		it('enables webhook when NOTIFY_WEBHOOK_URL is set', () => {
			process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.slack.com/test';

			const config = notifications.loadConfig();

			expect(config.webhook.enabled).toBe(true);
			expect(config.webhook.url).toBe('https://hooks.slack.com/test');
		});

		it('parses severity threshold from env', () => {
			process.env.NOTIFY_SEVERITY_THRESHOLD = '1';

			const config = notifications.loadConfig();

			expect(config.severityThreshold).toBe(1);
		});
	});

	describe('sendNotification', () => {
		it('creates a notification with id and timestamp', async () => {
			const result = await notifications.sendNotification({
				type: 'alert',
				severity: 'high',
				title: 'Test Alert',
				message: 'This is a test alert.',
			});

			expect(result.id).toMatch(/^ntf_/);
			expect(result.timestamp).toBeTruthy();
			expect(result.read).toBe(false);
			expect(result.title).toBe('Test Alert');
			expect(result.severity).toBe('high');
		});

		it('stores notification in the in-app store', async () => {
			await notifications.sendNotification({
				type: 'system',
				severity: 'medium',
				title: 'System check',
				message: 'All good.',
			});

			const stored = notifications.getNotifications(10);
			expect(stored.length).toBeGreaterThanOrEqual(1);
			expect(stored[0].title).toBe('System check');
		});
	});

	describe('getNotifications', () => {
		it('returns limited results', async () => {
			// Send multiple notifications
			for (let i = 0; i < 5; i++) {
				await notifications.sendNotification({
					type: 'alert',
					severity: 'low',
					title: `Alert ${i}`,
					message: `Message ${i}`,
				});
			}

			const limited = notifications.getNotifications(3);
			expect(limited).toHaveLength(3);
		});
	});

	describe('markRead', () => {
		it('marks a notification as read', async () => {
			const ntf = await notifications.sendNotification({
				type: 'alert',
				severity: 'medium',
				title: 'Unread Alert',
				message: 'This should be marked read.',
			});

			expect(ntf.read).toBe(false);

			const success = notifications.markRead(ntf.id);
			expect(success).toBe(true);

			const stored = notifications.getNotifications(1);
			expect(stored[0].read).toBe(true);
		});

		it('returns false for non-existent notification', () => {
			const success = notifications.markRead('ntf_nonexistent');
			expect(success).toBe(false);
		});
	});

	describe('markAllRead', () => {
		it('marks all notifications as read', async () => {
			for (let i = 0; i < 3; i++) {
				await notifications.sendNotification({
					type: 'alert',
					severity: 'low',
					title: `Alert ${i}`,
					message: `Msg ${i}`,
				});
			}

			const count = notifications.markAllRead();
			expect(count).toBeGreaterThanOrEqual(3);

			const unread = notifications.getUnreadCount();
			expect(unread).toBe(0);
		});
	});

	describe('getUnreadCount', () => {
		it('counts unread notifications', async () => {
			await notifications.sendNotification({
				type: 'alert',
				severity: 'medium',
				title: 'Unread 1',
				message: 'Test',
			});
			await notifications.sendNotification({
				type: 'alert',
				severity: 'low',
				title: 'Unread 2',
				message: 'Test',
			});

			const count = notifications.getUnreadCount();
			expect(count).toBeGreaterThanOrEqual(2);
		});
	});
});
