import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ThreatsPage from './+page.svelte';
import type { BeaconingSnapshot, BeaconSuspect, ThreatReport } from '$api/threats';
import { formatTime } from '$lib/utils/time';

// NET-192 PR 3: the 24h/7d/30d pills read the background beaconing scan. Until a scan has
// finished nothing may say "no beaconing", and a stale or partial result says so.

const LAST_GOOD = '2026-11-07T11:45:00+00:00';
const ROW: BeaconSuspect = {
	source_ip: '192.168.1.188', destination_ip: '188.166.201.72', destination_port: 443, connection_count: 204,
	interval_seconds: 3600, jitter_coefficient: 0.0012, confidence: 100, assessment: '', pattern: 'beacon',
};
const BASE: ThreatReport = {
	from: '',
	to: '',
	generated_at: '',
	summary: { threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, categories: {}, top_threats: [], kill_chains: [], baseline: null },
	kill_chains: [],
	beaconing: [],
	dns_anomalies: { dga_suspects: [], tunnel_suspects: [], nxdomain_spikes: [], suspicious_tlds: [] },
	lateral_movement: [],
	investigations: [],
	failed_checks: [],
	incomplete_checks: [],
};
const INTEL = { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 };

function snap(state: BeaconingSnapshot['state'], extra: Partial<BeaconingSnapshot> = {}): BeaconingSnapshot {
	const succeeded = state === 'ready' || state === 'stale';
	return {
		window: '24h',
		state,
		computed_at: state === 'pending' ? null : LAST_GOOD,
		last_success_at: succeeded ? LAST_GOOD : null,
		last_error: state === 'failed' ? 'the beaconing query failed' : null,
		from: null,
		to: null,
		...extra,
	};
}

/** Answers each report request with the next of `reports` (the last one repeats); returns the report URLs asked for. */
function stubDaemon(...reports: ThreatReport[]): string[] {
	const asked: string[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			if (url.startsWith('/api/threats/report')) {
				asked.push(url);
				const body = reports[Math.min(asked.length, reports.length) - 1];
				return { ok: true, status: 200, json: async () => body };
			}
			if (url.startsWith('/api/threats/intel')) return { ok: true, status: 200, json: async () => INTEL };
			return { ok: false, status: 503, json: async () => ({}) };
		}),
	);
	return asked;
}

const kpi = () => screen.getByText('Beaconing', { selector: '.kpi-top span' }).closest('.kpi')?.querySelector('.kpi-num')?.textContent;
const brief = () => document.querySelector('.brief-sub')?.textContent ?? '';
const flush = () => vi.advanceTimersByTimeAsync(0);

describe('Threats page — background beaconing', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it('asks for the 24h snapshot by default', async () => {
		const asked = stubDaemon({ ...BASE, beaconing_snapshot: snap('ready') });
		render(ThreatsPage);
		await vi.waitFor(() => expect(asked).toEqual(['/api/threats/report?snapshot=24h']));
	});

	it('while the first check runs: "—", a loading card, and no "none found" anywhere', async () => {
		stubDaemon({ ...BASE, beaconing_snapshot: snap('pending') });
		render(ThreatsPage);
		await vi.waitFor(() => expect(kpi()).toBe('—'));
		expect(screen.getAllByText(/Beaconing check running, ready in a few minutes/).length).toBeGreaterThan(0);
		expect(screen.getByText('checking…')).toBeInTheDocument();
		expect(screen.queryByText('No beaconing patterns detected.')).not.toBeInTheDocument();
		expect(brief()).toContain('Beaconing check running');
		expect(brief()).not.toMatch(/No kill chains, beaconing/);
	});

	it('when no check has succeeded: "—" and an error card', async () => {
		stubDaemon({ ...BASE, beaconing_snapshot: snap('failed') });
		render(ThreatsPage);
		await vi.waitFor(() => expect(kpi()).toBe('—'));
		expect(screen.getByText("Couldn't check for beaconing: the latest check failed.")).toBeInTheDocument();
		expect(screen.queryByText('No beaconing patterns detected.')).not.toBeInTheDocument();
		expect(brief()).toContain("Couldn't check beaconing");
	});

	it('when ready with nothing found: 0, the empty state, and when it was checked', async () => {
		stubDaemon({ ...BASE, beaconing_snapshot: snap('ready') });
		render(ThreatsPage);
		await vi.waitFor(() => expect(kpi()).toBe('0'));
		expect(screen.getByText('No beaconing patterns detected.')).toBeInTheDocument();
		expect(brief()).toBe('No kill chains, beaconing or threat intel matches.');
		expect(screen.getByText(`Connections repeated on a schedule · last 24 hours · checked ${formatTime(LAST_GOOD, 'short')}`)).toBeInTheDocument();
	});

	it('when stale: the last rows, with a note that the latest check failed', async () => {
		stubDaemon({ ...BASE, beaconing: [ROW], beaconing_snapshot: snap('stale', { last_error: 'scan hit the bucket cap' }) });
		render(ThreatsPage);
		await vi.waitFor(() => expect(kpi()).toBe('1'));
		expect(screen.getByRole('table', { name: 'Beaconing suspects' })).toBeInTheDocument();
		expect(screen.getByText(`Last checked ${formatTime(LAST_GOOD, 'short')}; the latest check failed.`)).toBeInTheDocument();
	});

	it('when stale with nothing found: the empty state stays, under the note', async () => {
		stubDaemon({ ...BASE, beaconing_snapshot: snap('stale', { last_error: 'the beaconing query failed' }) });
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText('No beaconing patterns detected.')).toBeInTheDocument());
		expect(screen.getByText(/the latest check failed\./)).toBeInTheDocument();
	});

	it('a live scan the cap cut short says "Partial scan" instead of the clean empty state', async () => {
		const asked = stubDaemon(
			{ ...BASE, beaconing_snapshot: snap('ready') },
			{ ...BASE, incomplete_checks: ['beaconing'] },
		);
		render(ThreatsPage);
		await vi.waitFor(() => expect(asked).toHaveLength(1));
		await fireEvent.click(screen.getByRole('button', { name: '1h' }));
		await vi.waitFor(() => expect(screen.getByText(/^Partial scan:/)).toBeInTheDocument());
		expect(asked[1]).toMatch(/^\/api\/threats\/report\?from=.+&to=.+$/);
		expect(screen.queryByText('No beaconing patterns detected.')).not.toBeInTheDocument();
		expect(brief()).toContain('Partial beaconing scan');
	});

	it('asks again every 20 s while pending, and stops once the check is ready', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
		const asked = stubDaemon(
			{ ...BASE, beaconing_snapshot: snap('pending') },
			{ ...BASE, beaconing_snapshot: snap('pending') },
			{ ...BASE, beaconing: [ROW], beaconing_snapshot: snap('ready') },
		);
		render(ThreatsPage);
		await flush();
		expect(asked).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(19_000);
		expect(asked).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(1_000);
		expect(asked).toHaveLength(2);
		await vi.advanceTimersByTimeAsync(20_000);
		expect(asked).toHaveLength(3);
		expect(kpi()).toBe('1');
		await vi.advanceTimersByTimeAsync(5 * 60_000);
		expect(asked).toHaveLength(3);
	});

	it('stops asking after 10 minutes of pending', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
		const asked = stubDaemon({ ...BASE, beaconing_snapshot: snap('pending') });
		render(ThreatsPage);
		await flush();
		await vi.advanceTimersByTimeAsync(10 * 60_000);
		const atTenMinutes = asked.length;
		expect(atTenMinutes).toBe(1 + 30); // the first load, then every 20 s for 10 min
		await vi.advanceTimersByTimeAsync(10 * 60_000);
		expect(asked).toHaveLength(atTenMinutes);
		expect(kpi()).toBe('—');
	});
});
