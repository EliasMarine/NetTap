import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ThreatsPage from './+page.svelte';

// #96: a failed detector returned [] and the page said "No beaconing patterns detected"; a
// failed report request was replaced with an all-zero report reading threat level "none".

const REPORT = {
	from: '',
	to: '',
	generated_at: '',
	summary: { threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, categories: {}, top_threats: [], kill_chains: [], baseline: null },
	kill_chains: [],
	beaconing: [],
	dns_anomalies: { dga_suspects: [], tunnel_suspects: [], nxdomain_spikes: [], suspicious_tlds: [] },
	lateral_movement: [{ source_ip: '192.168.1.66', destination_ip: '192.168.1.10', port: 445, service: 'SMB', connection_count: 2 }],
	investigations: [],
	failed_checks: ['beaconing'],
	incomplete_checks: ['lateral_movement'],
};

function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

describe('Threats page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('names a failed check instead of saying nothing was detected', async () => {
		stubDaemon({ '/api/threats/report': REPORT });
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText(/Couldn't check for beaconing/)).toBeInTheDocument());
		expect(screen.queryByText('No beaconing patterns detected.')).not.toBeInTheDocument();
		expect(screen.getByText('check failed')).toBeInTheDocument();
		expect(screen.getByText(/Not every connection pair was checked/)).toBeInTheDocument();
		expect(screen.getByText(/Couldn't load threat intel/)).toBeInTheDocument();
		// a check that ran and found nothing still says so
		expect(screen.getByText('No DNS anomalies detected.')).toBeInTheDocument();
	});

	it('says the report failed instead of showing threat level none', async () => {
		stubDaemon({});
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText('Failed to load threat intelligence data.')).toBeInTheDocument());
		expect(screen.queryByText('NONE')).not.toBeInTheDocument();
	});
});
