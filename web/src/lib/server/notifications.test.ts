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

	// OLD CODE START — NET-224: loadConfig is gone; the daemon keeps the email/webhook settings
	// describe('loadConfig', () => {
	// 	it('returns default config when no env vars set', () => {
	// 		const config = notifications.loadConfig();
	//
	// 		expect(config.email.enabled).toBe(false);
	// 		expect(config.email.smtpHost).toBe('');
	// 		expect(config.email.smtpPort).toBe(587);
	// 		expect(config.email.recipients).toEqual([]);
	// 		expect(config.webhook.enabled).toBe(false);
	// 		expect(config.inApp.enabled).toBe(true);
	// 		expect(config.severityThreshold).toBe(3);
	// 	});
	//
	// 	it('enables email when SMTP_HOST and NOTIFY_EMAIL are set', () => {
	// 		process.env.SMTP_HOST = 'smtp.test.com';
	// 		process.env.NOTIFY_EMAIL = 'admin@test.com, ops@test.com';
	//
	// 		const config = notifications.loadConfig();
	//
	// 		expect(config.email.enabled).toBe(true);
	// 		expect(config.email.smtpHost).toBe('smtp.test.com');
	// 		expect(config.email.recipients).toEqual(['admin@test.com', 'ops@test.com']);
	// 	});
	//
	// 	it('enables webhook when NOTIFY_WEBHOOK_URL is set', () => {
	// 		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.slack.com/test';
	//
	// 		const config = notifications.loadConfig();
	//
	// 		expect(config.webhook.enabled).toBe(true);
	// 		expect(config.webhook.url).toBe('https://hooks.slack.com/test');
	// 	});
	//
	// 	it('parses severity threshold from env', () => {
	// 		process.env.NOTIFY_SEVERITY_THRESHOLD = '1';
	//
	// 		const config = notifications.loadConfig();
	//
	// 		expect(config.severityThreshold).toBe(1);
	// 	});
	// });
	// OLD CODE END

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

	describe('onNotification (SSE emitter)', () => {
		it('emits when sendNotification is called', async () => {
			const received: unknown[] = [];
			const unsubscribe = notifications.onNotification((n) => received.push(n));

			await notifications.sendNotification({
				type: 'alert',
				severity: 'high',
				title: 'Emitter Test',
				message: 'Should emit',
			});

			unsubscribe();

			expect(received).toHaveLength(1);
			expect((received[0] as { title: string }).title).toBe('Emitter Test');
		});

		it('unsubscribe stops receiving events', async () => {
			const received: unknown[] = [];
			const unsubscribe = notifications.onNotification((n) => received.push(n));

			await notifications.sendNotification({
				type: 'alert',
				severity: 'high',
				title: 'Before Unsub',
				message: 'Should receive',
			});

			unsubscribe();

			await notifications.sendNotification({
				type: 'alert',
				severity: 'high',
				title: 'After Unsub',
				message: 'Should NOT receive',
			});

			expect(received).toHaveLength(1);
			expect((received[0] as { title: string }).title).toBe('Before Unsub');
		});

		it('emits for below-threshold notifications too', async () => {
			// Default threshold is 3 (medium). Low = 4, so below threshold.
			const received: unknown[] = [];
			const unsubscribe = notifications.onNotification((n) => received.push(n));

			await notifications.sendNotification({
				type: 'system',
				severity: 'low',
				title: 'Low Severity',
				message: 'Below threshold but should still emit',
			});

			unsubscribe();

			expect(received).toHaveLength(1);
			expect((received[0] as { title: string }).title).toBe('Low Severity');
		});
	});

	// OLD CODE START — NET-224: sendTestNotification is gone; the daemon sends and tests (daemon/tests/test_notifications_api.py)
	// // F3: the test answered "sent" whatever happened; it now reports each channel's outcome
	// describe('sendTestNotification', () => {
	// 	afterEach(() => vi.unstubAllGlobals());
	//
	// 	it('returns no results when no email or webhook is set up', async () => {
	// 		expect(await notifications.sendTestNotification()).toEqual([]);
	// 	});
	//
	// 	it('reports an SMTP failure instead of throwing, beside a webhook that worked', async () => {
	// 		vi.spyOn(console, 'error').mockImplementation(() => {});
	// 		// nothing listens on port 1 (and nodemailer may not be installed): either way the send fails
	// 		process.env.SMTP_HOST = '127.0.0.1';
	// 		process.env.SMTP_PORT = '1';
	// 		process.env.NOTIFY_EMAIL = 'admin@example.com';
	// 		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
	// 		vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 200 })));
	//
	// 		const results = await notifications.sendTestNotification();
	//
	// 		expect(results.map((r) => [r.channel, r.ok])).toEqual([['email', false], ['webhook', true]]);
	// 		expect(results[0].error).toBeTruthy();
	// 		// a missing nodemailer reads in plain words, without Node's message and its file path
	// 		expect(results[0].error).not.toMatch(/Cannot find (package|module)/);
	// 	});
	//
	// 	it('does not add the test to the in-app list', async () => {
	// 		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
	// 		vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 200 })));
	//
	// 		await notifications.sendTestNotification();
	//
	// 		expect(notifications.getNotifications(10)).toEqual([]);
	// 	});
	// });
	// OLD CODE END

	// OLD CODE START — NET-224: the web side sends no webhook any more
	// describe('sendNotification when a channel fails', () => {
	// 	afterEach(() => vi.unstubAllGlobals());
	//
	// 	it('still resolves and stores in-app when the webhook answers non-2xx', async () => {
	// 		vi.spyOn(console, 'error').mockImplementation(() => {});
	// 		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
	// 		vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 500 })));
	//
	// 		const result = await notifications.sendNotification({
	// 			type: 'alert',
	// 			severity: 'critical',
	// 			title: 'Webhook down',
	// 			message: 'The alert still lands in-app.',
	// 		});
	//
	// 		expect(result.title).toBe('Webhook down');
	// 		expect(notifications.getNotifications(1)[0].title).toBe('Webhook down');
	// 	});
	// });
	// OLD CODE END

	// NET-224: the daemon is the only external sender, so an alert never goes out twice
	describe('sendNotification sends nothing outside NetTap', () => {
		afterEach(() => vi.unstubAllGlobals());

		it('makes no request even with the old webhook and mail settings in the environment', async () => {
			process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
			process.env.SMTP_HOST = 'smtp.example.com';
			process.env.NOTIFY_EMAIL = 'admin@example.com';
			const fetchMock = vi.fn(async () => new Response('', { status: 200 }));
			vi.stubGlobal('fetch', fetchMock);

			const result = await notifications.sendNotification({
				type: 'alert',
				severity: 'critical',
				title: 'In-app only',
				message: 'The daemon sends the email and webhook.',
			});

			expect(fetchMock).not.toHaveBeenCalled();
			expect(notifications.getNotifications(1)[0].title).toBe(result.title);
		});
	});
});
