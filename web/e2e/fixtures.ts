import { test as base, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

export const MOCK_NICS = [
	{
		name: 'eth0',
		mac: 'aa:bb:cc:dd:ee:01',
		state: 'up',
		speed: '2500Mb/s',
		driver: 'igc',
		ipv4: '192.168.1.100',
		type: 'ethernet',
	},
	{
		name: 'eth1',
		mac: 'aa:bb:cc:dd:ee:02',
		state: 'up',
		speed: '2500Mb/s',
		driver: 'igc',
		type: 'ethernet',
	},
	{
		name: 'lo',
		mac: '00:00:00:00:00:00',
		state: 'up',
		speed: '',
		driver: '',
		ipv4: '127.0.0.1',
		type: 'loopback',
	},
];

export const MOCK_TRAFFIC_SUMMARY = {
	total_bytes: 1_073_741_824,
	orig_bytes: 536_870_912,
	resp_bytes: 536_870_912,
	connection_count: 12_345,
	top_protocol: 'tcp',
	unique_sources: 42,
	unique_destinations: 128,
};

export const MOCK_BANDWIDTH_SERIES = {
	series: Array.from({ length: 24 }, (_, i) => ({
		timestamp: new Date(Date.now() - (23 - i) * 3_600_000).toISOString(),
		total_bytes: Math.floor(Math.random() * 50_000_000),
		orig_bytes: Math.floor(Math.random() * 25_000_000),
		resp_bytes: Math.floor(Math.random() * 25_000_000),
	})),
};

export const MOCK_PROTOCOLS = {
	protocols: [
		{ name: 'tcp', count: 8000 },
		{ name: 'udp', count: 3000 },
		{ name: 'dns', count: 1200 },
		{ name: 'tls', count: 900 },
	],
};

export const MOCK_TOP_TALKERS = {
	top_talkers: [
		{ ip: '192.168.1.10', total_bytes: 500_000_000, connection_count: 1234 },
		{ ip: '192.168.1.20', total_bytes: 300_000_000, connection_count: 567 },
		{ ip: '10.0.0.5', total_bytes: 100_000_000, connection_count: 89 },
	],
};

export const MOCK_ALERT_COUNT = {
	counts: { total: 7, high: 2, medium: 3, low: 2 },
};

export const MOCK_ALERTS = {
	alerts: [
		{
			_id: '1',
			timestamp: new Date().toISOString(),
			src_ip: '10.0.0.5',
			dest_ip: '192.168.1.1',
			alert: { signature: 'ET MALWARE Test Signature', severity: 1 },
		},
		{
			_id: '2',
			timestamp: new Date().toISOString(),
			src_ip: '192.168.1.20',
			dest_ip: '8.8.8.8',
			alert: { signature: 'ET INFO Observed DNS Query', severity: 3 },
		},
	],
};

export const MOCK_SYSTEM_HEALTH = {
	healthy: true,
	opensearch_reachable: true,
	disk_usage_percent: 35.2,
	uptime_seconds: 86400,
};

export const MOCK_DEVICES = {
	devices: [
		{ ip: '192.168.1.10', mac: 'aa:bb:cc:dd:ee:01', hostname: 'desktop-pc', last_seen: new Date().toISOString() },
		{ ip: '192.168.1.20', mac: 'aa:bb:cc:dd:ee:02', hostname: 'laptop', last_seen: new Date().toISOString() },
	],
};

export const MOCK_CATEGORIES = {
	categories: [
		{ name: 'streaming', label: 'Streaming', total_bytes: 400_000_000, connection_count: 500 },
		{ name: 'social_media', label: 'Social Media', total_bytes: 200_000_000, connection_count: 300 },
	],
};

export const MOCK_BRIDGE_CONFIG = {
	config_preview: 'bridge br0 { ... }',
	wan: 'eth0',
	lan: 'eth1',
	bridge_name: 'br0',
	ready: true,
	warnings: [],
	source: 'mock',
};

export const MOCK_STORAGE_STATUS = {
	disk_total_gb: 953.7,
	disk_used_gb: 120.5,
	disk_free_gb: 833.2,
	disk_usage_percent: 12.6,
	hot_days: 90,
	warm_days: 180,
	cold_days: 30,
	disk_threshold_percent: 80,
	emergency_threshold_percent: 90,
	estimated_daily_gb: 1.2,
	source: 'mock',
};

export const MOCK_REQUIREMENTS = {
	nics: true,
	docker: true,
	disk: true,
};

// ---------------------------------------------------------------------------
// Route interceptor: mocks all daemon API calls so no backend is needed
// ---------------------------------------------------------------------------

export async function mockAllApiRoutes(page: Page) {
	// Health check
	await page.route('**/api/health', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) }),
	);

	// Notifications
	await page.route('**/api/notifications**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ notifications: [], unreadCount: 0 }),
		}),
	);

	// Setup: NICs
	await page.route('**/api/setup/nics**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ interfaces: MOCK_NICS, source: 'mock' }),
		}),
	);

	// Setup: Bridge
	await page.route('**/api/setup/bridge**', (route) => {
		if (route.request().method() === 'GET') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_BRIDGE_CONFIG),
			});
		}
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_BRIDGE_CONFIG),
		});
	});

	// Setup: Storage
	await page.route('**/api/setup/storage**', (route) => {
		if (route.request().method() === 'GET') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_STORAGE_STATUS),
			});
		}
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ success: true }),
		});
	});

	// Traffic endpoints
	await page.route('**/api/traffic/summary**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_TRAFFIC_SUMMARY),
		}),
	);

	await page.route('**/api/traffic/bandwidth**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_BANDWIDTH_SERIES),
		}),
	);

	await page.route('**/api/traffic/protocols**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_PROTOCOLS),
		}),
	);

	await page.route('**/api/traffic/top-talkers**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_TOP_TALKERS),
		}),
	);

	await page.route('**/api/traffic/categories**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_CATEGORIES),
		}),
	);

	// Alerts
	await page.route('**/api/alerts/count**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_ALERT_COUNT),
		}),
	);

	await page.route('**/api/alerts**', (route) => {
		if (route.request().url().includes('/count')) return route.continue();
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_ALERTS),
		});
	});

	// System health
	await page.route('**/api/system/health**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_SYSTEM_HEALTH),
		}),
	);

	// Devices
	await page.route('**/api/devices**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_DEVICES),
		}),
	);
}

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------

/**
 * Mock the hooks.server.ts auth flow by setting the nettap_token cookie
 * to a value the server will accept. Since Playwright E2E runs against the
 * real SvelteKit server, we need to intercept the login form action and
 * have it return a Set-Cookie header with a mock JWT.
 */
export async function mockLoginSuccess(page: Page) {
	await page.route('**/login', (route) => {
		const req = route.request();
		// Only intercept the POST (form submission), not the GET (page load)
		if (req.method() === 'POST') {
			return route.fulfill({
				status: 302,
				headers: {
					'Location': '/',
					'Set-Cookie': 'nettap_token=mock-jwt-token; Path=/; HttpOnly; SameSite=Lax',
				},
			});
		}
		return route.continue();
	});
}

/**
 * Mock the server-side hasUsers() check. Since hooks.server.ts calls
 * hasUsers() directly (not via API), we cannot mock it with page.route().
 * Instead, for the first-run test, we rely on the real server state.
 *
 * For tests that need an authenticated session, we mock the auth check
 * by intercepting the redirect.
 */
export async function mockAuthenticatedSession(page: Page) {
	// Intercept any redirect to /login by instead serving the requested page
	// This effectively bypasses the server-side auth guard for testing
	await page.route('**/*', async (route) => {
		const response = await route.fetch();
		if (response.status() === 302) {
			const location = response.headers()['location'];
			if (location === '/login') {
				// The server wants to redirect to login — fulfill with a mock
				// authenticated response by retrying with a cookie
				return route.fulfill({
					status: 200,
					headers: { 'content-type': 'text/html' },
					body: '<html><body>Redirected</body></html>',
				});
			}
		}
		return route.fulfill({ response });
	});
}

// ---------------------------------------------------------------------------
// Extended test fixture
// ---------------------------------------------------------------------------

export const test = base.extend<{ mockApis: void }>({
	mockApis: [
		async ({ page }, use) => {
			await mockAllApiRoutes(page);
			await use();
		},
		{ auto: false },
	],
});

export { expect } from '@playwright/test';
