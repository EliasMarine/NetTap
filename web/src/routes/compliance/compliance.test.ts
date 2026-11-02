import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import CompliancePage from './+page.svelte';

// #81: the page read riskScores.scores, but /api/risk/scores sends `devices`, so it crashed on
// `.length` and stayed on "Calculating security posture..." for good. It also compared counts
// per IP: a second address of one device (G11: an AP's VLAN 40 IP) gave coverage above 100%.

const DAEMON_REPLIES: Record<string, unknown> = {
	'/api/traffic/protocols': { protocols: [], services: [{ name: 'ssl', count: 80 }] },
	'/api/alerts/count': { from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } },
	'/api/devices': { from: '', to: '', limit: 100, devices: [{ ip: '192.168.1.10' }, { ip: '192.168.1.198' }] },
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
	return screen.getByText(name).closest('.category-card') as HTMLElement;
}

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

		await vi.waitFor(() => expect(screen.getByText('Monitoring Coverage')).toBeInTheDocument());
		expect(screen.queryByText('Calculating security posture...')).not.toBeInTheDocument();
		expect(within(categoryCard('Monitoring Coverage')).getByText('100%')).toBeInTheDocument();
		expect(within(categoryCard('Network Segmentation')).getByText('100%')).toBeInTheDocument();
	});
});
