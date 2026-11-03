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

	it('counts a device that contacts many hosts on schedules once, not as many suspects', async () => {
		const peer = (h: number) => ({
			source_ip: '192.168.1.205', destination_ip: `198.51.100.${h}`, destination_port: 6881, connection_count: 30,
			interval_seconds: 2206, jitter_coefficient: 0.01, confidence: 60, assessment: '', pattern: 'many_hosts', host_count: 12,
		});
		const beacon = {
			source_ip: '192.168.1.188', destination_ip: '188.166.201.72', destination_port: 443, connection_count: 204,
			interval_seconds: 3600.6, jitter_coefficient: 0.0012, confidence: 100, assessment: '', pattern: 'beacon',
		};
		stubDaemon({
			'/api/threats/report': {
				...REPORT,
				failed_checks: [],
				incomplete_checks: [],
				beaconing: [beacon, ...Array.from({ length: 12 }, (_, h) => peer(h))],
			},
			'/api/threats/intel': { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 },
		});
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText('1 suspects')).toBeInTheDocument());
		expect(screen.getByText(/contacts 12 internet hosts on regular schedules/)).toBeInTheDocument();
		expect(screen.queryByText('198.51.100.3', { exact: false })).not.toBeInTheDocument();
	});

	it('says a failed auto-investigation failed instead of hiding it', async () => {
		stubDaemon({
			'/api/threats/report': { ...REPORT, failed_checks: ['investigations'], incomplete_checks: [] },
			'/api/threats/intel': { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 },
		});
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText(/Couldn't investigate one or more critical alerts/)).toBeInTheDocument());
		expect(screen.getByText(/Couldn't check auto-investigations/)).toBeInTheDocument();
	});
});

