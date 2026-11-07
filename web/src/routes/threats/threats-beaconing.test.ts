import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh } from '$lib/stores/pageRefresh';
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
const kpiSub = () => screen.getByText('Beaconing', { selector: '.kpi-top span' }).closest('.kpi')?.querySelector('.kpi-sub')?.textContent;
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
		// the KPI's count is an older scan's: it says when, so it isn't read as live
		expect(kpiSub()).toBe(`Last checked ${formatTime(LAST_GOOD, 'short')}`);
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

});

// While the check is pending the page polls /api/threats/beaconing (not the whole report) every
// 20 s for at most 10 min per range, and loads the page again once the check has finished.
describe('Threats page — polling the background beaconing check', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	type Poll = { beacons: BeaconSuspect[]; total: number; complete: boolean; beaconing_snapshot: BeaconingSnapshot };
	const poll = (state: BeaconingSnapshot['state'], beacons: BeaconSuspect[] = []): Poll => ({
		beacons,
		total: beacons.length,
		complete: state !== 'pending',
		beaconing_snapshot: snap(state),
	});
	const PENDING: ThreatReport = { ...BASE, beaconing_snapshot: snap('pending') };

	/**
	 * Report requests get the next of `reports`, beaconing polls the next of `polls` (the last of
	 * each repeats). An Error reply rejects the request; a Promise answers when it resolves.
	 */
	function stubPolling(reports: ThreatReport[], polls: (Poll | Error | Promise<Poll>)[]) {
		const asked = { reports: [] as string[], polls: [] as string[] };
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url.startsWith('/api/threats/report')) {
					asked.reports.push(url);
					const body = reports[Math.min(asked.reports.length, reports.length) - 1];
					return { ok: true, status: 200, json: async () => body };
				}
				if (url.startsWith('/api/threats/beaconing')) {
					asked.polls.push(url);
					const reply = await polls[Math.min(asked.polls.length, polls.length) - 1];
					if (reply instanceof Error) throw reply;
					return { ok: true, status: 200, json: async () => reply };
				}
				if (url.startsWith('/api/threats/intel')) return { ok: true, status: 200, json: async () => INTEL };
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);
		return asked;
	}
	const fakeTimers = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });

	it('polls the beaconing check every 20 s while pending, then loads the page again once it is ready', async () => {
		fakeTimers();
		const asked = stubPolling([PENDING, { ...BASE, beaconing: [ROW], beaconing_snapshot: snap('ready') }], [poll('pending'), poll('ready', [ROW])]);
		render(ThreatsPage);
		await flush();
		const firstUpdate = get(pageRefresh).updatedAt;
		expect(asked.reports).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(19_000);
		expect(asked.polls).toHaveLength(0);
		await vi.advanceTimersByTimeAsync(1_000);
		expect(asked.polls).toEqual(['/api/threats/beaconing?snapshot=24h']);
		expect(asked.reports).toHaveLength(1); // a pending poll doesn't reload the report
		await vi.advanceTimersByTimeAsync(20_000);
		expect(asked.polls).toHaveLength(2);
		expect(asked.reports).toHaveLength(2); // ready: the page loads once more
		expect(kpi()).toBe('1');
		expect(get(pageRefresh).updatedAt).toBeGreaterThan(firstUpdate ?? 0); // "Updated" moved
		await vi.advanceTimersByTimeAsync(5 * 60_000);
		expect(asked.polls).toHaveLength(2);
		expect(asked.reports).toHaveLength(2);
	});

	it('stops after 10 minutes of pending, and then says to refresh instead of "a few minutes"', async () => {
		fakeTimers();
		const asked = stubPolling([PENDING], [poll('pending')]);
		render(ThreatsPage);
		await flush();
		expect(kpiSub()).toBe('Check running, ready in a few minutes');
		await vi.advanceTimersByTimeAsync(10 * 60_000);
		expect(asked.polls).toHaveLength(30); // every 20 s for 10 min
		await vi.advanceTimersByTimeAsync(10 * 60_000);
		expect(asked.polls).toHaveLength(30);
		expect(asked.reports).toHaveLength(1);
		expect(kpi()).toBe('—');
		expect(kpiSub()).toBe('Still running. Refresh to check again.');
		expect(screen.getAllByText('Beaconing check still running. Refresh to check again.').length).toBeGreaterThan(0);
		expect(screen.queryByText(/ready in a few minutes/)).not.toBeInTheDocument();
	});

	it('asks nothing more once the page has gone', async () => {
		fakeTimers();
		const asked = stubPolling([PENDING], [poll('pending')]);
		const { unmount } = render(ThreatsPage);
		await flush();
		await vi.advanceTimersByTimeAsync(20_000);
		expect(asked.polls).toHaveLength(1);
		unmount();
		await vi.advanceTimersByTimeAsync(5 * 60_000);
		expect(asked.polls).toHaveLength(1);
		expect(asked.reports).toHaveLength(1);
	});

	it('a poll still in flight when the range changes never overwrites the new range', async () => {
		fakeTimers();
		let release!: (p: Poll) => void;
		const slow = new Promise<Poll>((resolve) => (release = resolve));
		const asked = stubPolling([PENDING, { ...BASE, beaconing_snapshot: snap('failed', { window: '7d' }) }], [slow]);
		render(ThreatsPage);
		await flush();
		await vi.advanceTimersByTimeAsync(20_000); // the 24h poll is in flight
		expect(asked.polls).toHaveLength(1);
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await flush();
		expect(asked.reports[1]).toBe('/api/threats/report?snapshot=7d');
		expect(screen.getByText("Couldn't check for beaconing: the latest check failed.")).toBeInTheDocument();
		release(poll('ready', [ROW]));
		await flush();
		expect(kpi()).toBe('—');
		expect(screen.getByText("Couldn't check for beaconing: the latest check failed.")).toBeInTheDocument();
		expect(asked.reports).toHaveLength(2); // the late 24h answer didn't reload the page either
	});

	it('a poll that fails is tried again 20 s later, and the page recovers', async () => {
		fakeTimers();
		const asked = stubPolling([PENDING, { ...BASE, beaconing_snapshot: snap('ready') }], [new Error('network down'), poll('ready')]);
		render(ThreatsPage);
		await flush();
		await vi.advanceTimersByTimeAsync(20_000);
		expect(asked.polls).toHaveLength(1);
		expect(kpi()).toBe('—');
		await vi.advanceTimersByTimeAsync(20_000);
		expect(asked.polls).toHaveLength(2);
		expect(asked.reports).toHaveLength(2);
		expect(kpi()).toBe('0');
	});
});
