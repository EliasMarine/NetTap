import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import CompliancePage from './+page.svelte';

// #81: the page read riskScores.scores, but /api/risk/scores sends `devices`, so it crashed on
// `.length` and stayed on "Calculating security posture..." for good. It also compared counts
// per IP: a second address of one device (G11: an AP's VLAN 40 IP) gave coverage above 100%.

const DAEMON_REPLIES: Record<string, unknown> = {
	'/api/traffic/protocols': {
		protocols: [],
		// #86: names alone gave 80 / 380 = 21% and DNS 0%; the daemon's figures give 60% and 10%
		services: [
			{ name: 'ssl', count: 80 },
			{ name: 'unknown', count: 200 },
			{ name: 'dns', count: 100 },
		],
		encryption: { eligible: 200, encrypted: 120 },
		dns: { plain: 90, over_tls: 10 },
	},
	'/api/alerts/count': { from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } },
	'/api/devices': { from: '', to: '', limit: 100, devices: [{ ip: '192.168.1.10' }, { ip: '192.168.1.198' }] },
	'/api/devices/count': { from: '', to: '', count: 2 },
	'/api/risk/scores': {
		device_count: 3,
		devices: ['192.168.1.10', '192.168.1.198', '192.168.40.198'].map((ip) => ({
			ip,
			score: 10,
			level: 'low',
			factors: [],
		})),
	},
	'/api/investigations/stats': { total: 0, by_status: {} },
};

function categoryCard(name: string): HTMLElement {
	return screen.getByRole('heading', { name }).closest('.category-card') as HTMLElement;
}

/** The category cards render once the first load has finished. */
const heading = (name: string) => screen.getByRole('heading', { name });

describe('Security Posture page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('loads with the daemon risk response and counts each device once', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const path = url.split('?')[0];
				const body = DAEMON_REPLIES[path];
				return body
					? { ok: true, status: 200, json: async () => body }
					: { ok: false, status: 503, json: async () => ({}) };
			}),
		);

		render(CompliancePage);

		await vi.waitFor(() => expect(heading('Monitoring coverage')).toBeInTheDocument());
		expect(screen.queryByText('Calculating security posture…')).not.toBeInTheDocument();
		expect(within(categoryCard('Monitoring coverage')).getByText('100%')).toBeInTheDocument();
		expect(within(categoryCard('Network segmentation')).getByText('100%')).toBeInTheDocument();
	});

	it('compares every device, not the two endpoints\' top 100s (#96)', async () => {
		// 150 devices: /api/devices lists its top 100 by bytes; the count and the risk list have all 150
		const ips = Array.from({ length: 150 }, (_, i) => `192.168.1.${i + 1}`);
		const replies: Record<string, unknown> = {
			...DAEMON_REPLIES,
			'/api/devices': { from: '', to: '', limit: 100, devices: ips.slice(0, 100).map((ip) => ({ ip })) },
			'/api/devices/count': { from: '', to: '', count: 150 },
			'/api/risk/scores': {
				device_count: 150,
				devices: ips.map((ip) => ({ ip, score: 10, level: 'low', factors: [] })),
			},
		};
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const body = replies[url.split('?')[0]];
				return body
					? { ok: true, status: 200, json: async () => body }
					: { ok: false, status: 503, json: async () => ({}) };
			}),
		);

		render(CompliancePage);

		await vi.waitFor(() => expect(heading('Network segmentation')).toBeInTheDocument());
		const network = categoryCard('Network segmentation');
		expect(within(network).getByText('150 device(s) discovered on your network')).toBeInTheDocument();
		expect(within(network).getByText('100%')).toBeInTheDocument();
		const monitoring = categoryCard('Monitoring coverage');
		expect(within(monitoring).getByText('150 of 150 device(s) have risk scores computed')).toBeInTheDocument();
		expect(within(monitoring).getByText('100%')).toBeInTheDocument();
	});

	it('scores Encryption and DNS from the daemon figures, not Zeek service names (#86)', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const body = DAEMON_REPLIES[url.split('?')[0]];
				return body
					? { ok: true, status: 200, json: async () => body }
					: { ok: false, status: 503, json: async () => ({}) };
			}),
		);

		render(CompliancePage);

		await vi.waitFor(() => expect(heading('Encryption')).toBeInTheDocument());
		const encryption = categoryCard('Encryption');
		expect(within(encryption).getByText('60%')).toBeInTheDocument();
		expect(within(encryption).getByText('120 of 200 connections encrypted (60%)')).toBeInTheDocument();
		const dns = categoryCard('DNS security');
		expect(within(dns).getByText('10%')).toBeInTheDocument();
		expect(within(dns).getByText('10 DNS-over-TLS connections')).toBeInTheDocument();
	});
});

// #96: a failed input became zeros or an empty list, so its categories scored as if measured
// ("0 of 2 device(s) have risk scores computed") and the overall grade looked complete.
describe('Security Posture page when an input fails', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function stubDaemon(failing: Record<string, 'http' | 'network'>): void {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const path = url.split('?')[0];
				if (failing[path] === 'network') throw new TypeError('Failed to fetch');
				if (failing[path] === 'http') return { ok: false, status: 502, json: async () => ({}) };
				return { ok: true, status: 200, json: async () => DAEMON_REPLIES[path] };
			}),
		);
	}

	it('says which categories it could not compute when risk scores fail', async () => {
		stubDaemon({ '/api/risk/scores': 'http' });
		render(CompliancePage);

		await vi.waitFor(() => expect(heading('Monitoring coverage')).toBeInTheDocument());
		for (const name of ['Monitoring coverage', 'Network segmentation']) {
			const card = categoryCard(name);
			expect(within(card).getAllByText("Couldn't load risk scores: the request failed.").length).toBeGreaterThan(0);
			expect(within(card).queryByText(/%$/)).not.toBeInTheDocument();
		}
		expect(screen.queryByText(/0 of 2 device\(s\) have risk scores/)).not.toBeInTheDocument();
		expect(screen.getByText(/Couldn't compute the overall score/)).toBeInTheDocument();
		// the categories that loaded still score
		expect(within(categoryCard('Encryption')).getByText('60%')).toBeInTheDocument();
	});

	it('handles a rejected request the same way (traffic protocols)', async () => {
		stubDaemon({ '/api/traffic/protocols': 'network' });
		render(CompliancePage);

		await vi.waitFor(() => expect(heading('Encryption')).toBeInTheDocument());
		for (const name of ['Encryption', 'DNS security', 'Patch currency']) {
			expect(within(categoryCard(name)).getAllByText("Couldn't load traffic protocols: the request failed.").length).toBeGreaterThan(0);
		}
		expect(screen.queryByText('No legacy unencrypted protocols detected')).not.toBeInTheDocument();
		expect(screen.queryByText(/looks excellent/)).not.toBeInTheDocument();
		expect(within(categoryCard('Monitoring coverage')).getByText('100%')).toBeInTheDocument();
	});

	it('shows the overall score when every input loads', async () => {
		stubDaemon({});
		render(CompliancePage);

		// the overall figure is the ring's (its centre reads the number without a % sign)
		await vi.waitFor(() =>
			expect(screen.getByRole('img', { name: /^Overall score \d+ out of 100, grade [A-F]$/ })).toBeInTheDocument(),
		);
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
		// all six categories
		expect(screen.getAllByText(/^\d+%$/)).toHaveLength(6);
	});

	it('needs investigation stats for Alert Response only when there are alerts', async () => {
		stubDaemon({ '/api/investigations/stats': 'http' });
		const { unmount } = render(CompliancePage);
		// no alerts: the score is 100 whatever the investigations
		await vi.waitFor(() => expect(heading('Alert response')).toBeInTheDocument());
		expect(within(categoryCard('Alert response')).getByText('100%')).toBeInTheDocument();
		unmount();

		DAEMON_REPLIES['/api/alerts/count'] = { from: '', to: '', counts: { total: 3, high: 1, medium: 2, low: 0 } };
		try {
			render(CompliancePage);
			await vi.waitFor(() => expect(heading('Alert response')).toBeInTheDocument());
			const card = categoryCard('Alert response');
			expect(within(card).getAllByText("Couldn't load investigation stats: the request failed.").length).toBeGreaterThan(0);
			expect(within(card).queryByText('0%')).not.toBeInTheDocument();
		} finally {
			DAEMON_REPLIES['/api/alerts/count'] = { from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } };
		}
	});
});
