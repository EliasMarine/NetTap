/**
 * NET-340: the Reports page. KPIs from the card's schedule and the shown report, the hero with every
 * section's coverage line and status, the empty and error states, the history's sort and select,
 * and Generate now's 409 shown as the daemon words it.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, within, cleanup } from '@testing-library/svelte';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';
import { CARD_SCHEDULE, DAILY_SCHEDULE, DATA_CAP_OK, HISTORY, REPORT, SCHEDULES, SCHEDULES_EMPTY, WORST_LEFT_OUT } from '../../../e2e/visual/fixtures/reports';
import type { Report } from '$lib/api/reports';
import { zonedClock, zonedDay } from './report-words';

type Reply = { status: number; body: unknown };
const ok = (body: unknown): Reply => ({ status: 200, body });

/** The older manual report, answered by its own id. */
const OLDER: Report = {
	...REPORT,
	id: HISTORY.reports[1].id,
	trigger: 'manual',
	generated_at: HISTORY.reports[1].generated_at,
	delivery: { result: 'not_emailed', at: null, recipients: 0, refused: 0, error: null },
	period: { ...REPORT.period, first: '2026-11-02', last: '2026-11-08' },
};

let calls: { url: string; method: string }[] = [];

type Answer = Reply | Promise<Reply>;

/** Routes by path; `generate` answers Generate now. A reply may be a promise, so a test can hold it. */
// OLD CODE: schedules?: Reply; report?: (id: string) => Reply; (TypeScript review: the race tests hold replies)
function stubFetch({ schedules = () => ok(SCHEDULES), history = ok(HISTORY), report = (id: string) => ok(id === OLDER.id ? OLDER : REPORT), generate = ok(REPORT) }: {
	schedules?: () => Answer;
	history?: Reply;
	report?: (id: string) => Answer;
	generate?: Reply;
} = {}) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string, init?: RequestInit) => {
			calls.push({ url, method: init?.method ?? 'GET' });
			const path = url.split('?')[0];
			const r = await (
				path === '/api/reports/schedules' ? schedules()
				: path === '/api/reports/history' ? history
				: path.startsWith('/api/reports/history/') ? report(decodeURIComponent(path.split('/').pop()!))
				: path.startsWith('/api/reports/generate/') ? generate
				: { status: 404, body: { error: 'Not found' } }
			);
			return { ok: r.status < 400, status: r.status, json: async () => r.body };
		}),
	);
}

/** A reply the test lets through when it chooses. */
function held() {
	let release: (r: Reply) => void = () => {};
	const reply = new Promise<Reply>((resolve) => (release = resolve));
	return { reply, release };
}

/** The report on screen: its head (from the history row) and its sections (from the report itself). */
async function shownReport(period: string) {
	expect(await screen.findByRole('heading', { name: `Report for ${period}` })).toBeInTheDocument();
	expect(await screen.findByRole('region', { name: 'Internet use' })).toBeInTheDocument();
}

const rowButton = (name: RegExp) => within(screen.getByRole('table', { name: 'Report history' })).getByRole('button', { name });
const NEWEST = /^Show the report for 9–15 Nov 2026/;
const OLDER_ROW = /^Show the report for 2–8 Nov 2026, generated Thu 12 Nov/;

const kpi = (label: string) => screen.getByText(label, { selector: '.kpi-top span' }).closest('.kpi') as HTMLElement;

beforeEach(() => {
	calls = [];
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => vi.unstubAllGlobals());

describe('Reports page (NET-340)', () => {
	it("shows the card's schedule, never the daily one listed first", async () => {
		stubFetch();
		render(Page);

		expect(await screen.findByRole('heading', { name: 'Report for 9–15 Nov 2026' })).toBeInTheDocument();
		expect(calls.map((c) => c.url)).toContain(`/api/reports/history?schedule=${CARD_SCHEDULE.id}`);
		expect(calls.some((c) => c.url.includes(DAILY_SCHEDULE.id))).toBe(false);
	});

	it('KPIs: next send in the ledger zone, last delivery, where it goes, and the days covered', async () => {
		stubFetch();
		render(Page);
		await shownReport('9–15 Nov 2026');

		expect(within(kpi('Next report')).getByText(zonedDay(CARD_SCHEDULE.next_send, 'Europe/London'))).toBeInTheDocument();
		expect(within(kpi('Next report')).getByText(`${zonedClock(CARD_SCHEDULE.next_send, 'Europe/London')} · Europe/London`)).toBeInTheDocument();
		expect(within(kpi('Last sent')).getByText('16 Nov')).toBeInTheDocument();
		expect(within(kpi('Last sent')).getByText('Mon 08:00 · 9–15 Nov 2026')).toBeInTheDocument();
		expect(within(kpi('Delivery')).getByText('Sent')).toBeInTheDocument();
		expect(within(kpi('Delivery')).getByText('To 2 addresses')).toBeInTheDocument();
		expect(within(kpi('Days covered')).getByText('7 of 7')).toBeInTheDocument();
		expect(within(kpi('Days covered')).getByText('6 of 7 days of alerts stored')).toBeInTheDocument();
	});

	it('hero: five sections, each with its status and coverage line; a partial one shows its note', async () => {
		stubFetch();
		render(Page);
		await shownReport('9–15 Nov 2026');

		for (const name of ['Internet use', 'Alerts', 'New devices', 'Offline incidents', 'Data cap']) {
			expect(screen.getByRole('heading', { name, level: 3 })).toBeInTheDocument();
		}
		const alerts = screen.getByRole('region', { name: 'Alerts' });
		expect(within(alerts).getByText('Partial')).toBeInTheDocument();
		expect(within(alerts).getByText('Alerts stored for 6 of 7 days')).toBeInTheDocument();
		expect(within(alerts).getByText('Only part of Wednesday 11 November is stored.')).toBeInTheDocument();
		// a stored day with no alerts can't look like a quiet one, and a partial day keeps its count
		expect(within(alerts).getByText("No alerts recorded: a quiet day, or Suricata wasn't running")).toBeInTheDocument();
		expect(within(alerts).getByText('Only part of this day is stored')).toBeInTheDocument();
		expect(within(alerts).getByText('Severity unknown')).toBeInTheDocument();
		expect(within(screen.getByRole('region', { name: 'Internet use' })).getByText('7 of 7 days counted')).toBeInTheDocument();
		// with no return time the daemon's detail is the end, shown once; an unnamed device shows its MAC
		const offline = screen.getByRole('region', { name: 'Offline incidents' });
		expect(within(offline).getAllByText('Return time not recorded')).toHaveLength(1);
		expect(within(offline).getByText('Returned before 14 Nov 09:12, time not recorded')).toBeInTheDocument();
		expect(within(offline).getByText('02:00:5e:10:00:33')).toBeInTheDocument();
		// the fixture's unavailable section: its note, and neither its coverage nor any figure
		const cap = screen.getByRole('region', { name: 'Data cap' });
		expect(within(cap).getByText('Unavailable')).toBeInTheDocument();
		expect(within(cap).getByText('This section took too long and was left out.')).toBeInTheDocument();
		expect(within(cap).queryByText('Not available this time')).not.toBeInTheDocument();
		expect(within(cap).queryByText(/No data cap set/)).not.toBeInTheDocument();
		expectNoNestedInteractive(document.body);
	});

	it('an unavailable section shows its reason and no figures', async () => {
		const broken: Report = {
			...REPORT,
			sections: { ...REPORT.sections, traffic: { status: 'unavailable', coverage: 'Not available this time', note: 'The usage ledger is unavailable.' } },
		};
		stubFetch({ report: () => ok(broken) });
		render(Page);

		const traffic = await screen.findByRole('region', { name: 'Internet use' });
		expect(within(traffic).getByText('Unavailable')).toBeInTheDocument();
		expect(within(traffic).getByText('The usage ledger is unavailable.')).toBeInTheDocument();
		expect(within(traffic).queryByText('Total')).not.toBeInTheDocument();
		expect(within(traffic).queryByText(/No usage was counted/)).not.toBeInTheDocument();
		expect(within(traffic).queryByText('Not available this time')).not.toBeInTheDocument();
		expect(within(kpi('Days covered')).getByText('—')).toBeInTheDocument();
	});

	it('data cap: the counted figure, the provisional total beside it, and each warning in words', async () => {
		stubFetch({ report: () => ok({ ...REPORT, sections: { ...REPORT.sections, data_cap: DATA_CAP_OK } }) });
		render(Page);

		const cap = await screen.findByRole('region', { name: 'Data cap' });
		expect(within(cap).getByText('812.3 GB')).toBeInTheDocument();
		expect(within(cap).getByText('830.1 GB')).toBeInTheDocument();
		expect(within(cap).getByText('81.2%')).toBeInTheDocument();
		expect(within(cap).getByText('Passed 80% of 1,000 GB on Sat 14 Nov, 09:12.')).toBeInTheDocument();
		expect(within(cap).getByText('On track to go over 1,000 GB, noted Sun 15 Nov, 09:00.')).toBeInTheDocument();
	});

	it("says when the cap warnings couldn't be read, when there were no alerts, and why the ranking was left out", async () => {
		const quiet: Report = {
			...REPORT,
			sections: { ...REPORT.sections, data_cap: { ...DATA_CAP_OK, crossings: null }, alerts: { ...REPORT.sections.alerts, worst: [] } },
		};
		stubFetch({ report: () => ok(quiet) });
		render(Page);

		expect(await screen.findByText("Couldn't read the cap warnings this time.")).toBeInTheDocument();
		expect(screen.getByText('No alerts this week.')).toBeInTheDocument();
		cleanup();

		// the daemon's note already starts "Not included this time", so the page shows it as it is, once
		const unranked: Report = { ...REPORT, sections: { ...REPORT.sections, alerts: { ...REPORT.sections.alerts, worst: null, worst_note: WORST_LEFT_OUT } } };
		stubFetch({ report: () => ok(unranked) });
		render(Page);
		expect(await screen.findByText(WORST_LEFT_OUT)).toBeInTheDocument();
		expect(screen.getAllByText(/Not included this time/)).toHaveLength(1);
		cleanup();

		const noNote: Report = { ...REPORT, sections: { ...REPORT.sections, alerts: { ...REPORT.sections.alerts, worst: null, worst_note: null } } };
		stubFetch({ report: () => ok(noNote) });
		render(Page);
		expect(await screen.findByText('Not included this time.')).toBeInTheDocument();
	});

	it('the "at least" figure is floored, so a minimum never reads above what was counted', async () => {
		const recounting: Report = {
			...REPORT,
			sections: { ...REPORT.sections, traffic: { ...REPORT.sections.traffic, provisional: true, counted_total: 82_460_000_000 } },
		};
		stubFetch({ report: () => ok(recounting) });
		render(Page);

		// rounded, 82.46 GB would read "82.5 GB"
		expect(await screen.findByText('At least 82.4 GB counted under your current exclusions.')).toBeInTheDocument();
		expect(screen.queryByText(/82\.5 GB/)).not.toBeInTheDocument();
	});

	it('links to Security posture under the sections, as the email does', async () => {
		stubFetch();
		render(Page);

		const link = await screen.findByRole('link', { name: 'Open Security posture' });
		expect(link).toHaveAttribute('href', '/compliance');
		expect(link.closest('p')).toHaveTextContent("Security posture isn't part of this report. Open Security posture for the full picture.");
	});

	it('empty: no card schedule points to Settings › Notifications, and Generate now is off', async () => {
		stubFetch({ schedules: () => ok(SCHEDULES_EMPTY) });
		render(Page);

		expect(await screen.findByText('No weekly report set up.')).toBeInTheDocument();
		const links = screen.getAllByRole('link', { name: 'Open Settings › Notifications' });
		expect(links[0]).toHaveAttribute('href', '/settings?tab=notifications');
		expect(screen.getByRole('button', { name: 'Generate now' })).toBeDisabled();
		expect(within(kpi('Next report')).getByText('Not set up')).toBeInTheDocument();
		expect(calls.some((c) => c.url.startsWith('/api/reports/history'))).toBe(false);
	});

	// NET-357: the copy names the switch and the save, and says email is optional
	it('empty: the hero and History name the step that sets the report up', async () => {
		stubFetch({ schedules: () => ok(SCHEDULES_EMPTY) });
		render(Page);

		expect(
			await screen.findByText(
				'Turn on Make a weekly report in Settings › Notifications and save. NetTap keeps each report here. To have it emailed too, add addresses there and set up the email server in Settings › API keys.',
			),
		).toBeInTheDocument();
		expect(screen.getByText('No reports yet.')).toBeInTheDocument();
		expect(screen.getByText('Turn on Make a weekly report in Settings › Notifications and save.')).toBeInTheDocument();
	});

	it('a schedule with no reports yet says when the first one comes', async () => {
		stubFetch({ history: ok({ reports: [] }) });
		render(Page);

		expect(await screen.findAllByText('No reports yet.')).toHaveLength(2);
		expect(screen.getByText(/^The first one is made on /)).toBeInTheDocument();
		expect(within(kpi('Days covered')).getByText('—')).toBeInTheDocument();
	});

	it('a failed load says so, never "no reports", and Try again reloads', async () => {
		stubFetch({ schedules: () => ({ status: 503, body: { error: 'Report schedules are unavailable.' } }) });
		render(Page);

		expect(await screen.findByText("Couldn't load the reports: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the report history: the request failed.")).toBeInTheDocument();
		// TypeScript review: the daemon's own reason, not "check that NetTap is running"
		expect(screen.getAllByText('Report schedules are unavailable.')).toHaveLength(2);
		expect(screen.queryByText(/Check that NetTap is running/)).not.toBeInTheDocument();
		expect(screen.queryByText('No weekly report set up.')).not.toBeInTheDocument();
		expect(within(kpi('Next report')).getByText('—')).toBeInTheDocument();

		stubFetch();
		await fireEvent.click(screen.getAllByRole('button', { name: 'Try again' })[0]);
		expect(await screen.findByRole('heading', { name: 'Report for 9–15 Nov 2026' })).toBeInTheDocument();
	});

	it('a load that never reaches NetTap keeps the generic hint', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		render(Page);

		expect(await screen.findAllByText('Check that NetTap is running on the System page, then try again.')).toHaveLength(2);
	});

	it("a report that fails shows the daemon's reason", async () => {
		stubFetch({ report: () => ({ status: 404, body: { error: 'That report is no longer kept.' } }) });
		render(Page);

		expect(await screen.findByText("Couldn't load this report: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('That report is no longer kept.')).toBeInTheDocument();
	});

	// TypeScript review: A shown, B picked and hanging, A picked again and its refetch failing left the spinner for ever
	it('picking back the report on screen shows it, even when its refetch fails, and a later pick clears the notice', async () => {
		const b = held();
		let failA = false;
		stubFetch({ report: (id) => (id === OLDER.id ? b.reply : failA ? { status: 503, body: {} } : ok(REPORT)) });
		render(Page);
		await shownReport('9–15 Nov 2026');

		await fireEvent.click(rowButton(OLDER_ROW));
		expect(await screen.findByText('Loading the report')).toBeInTheDocument();

		failA = true;
		await fireEvent.click(rowButton(NEWEST));
		expect(await screen.findByRole('region', { name: 'Internet use' })).toBeInTheDocument();
		expect(await screen.findByText(/^Couldn't refresh the reports; showing figures from/)).toBeInTheDocument();
		expect(screen.queryByText('Loading the report')).not.toBeInTheDocument();

		// B's late answer belongs to a superseded pick
		b.release(ok(OLDER));
		await Promise.resolve();
		expect(screen.getByRole('heading', { name: 'Report for 9–15 Nov 2026' })).toBeInTheDocument();

		// a later pick that loads clears the stale notice that A's refetch set
		stubFetch();
		await fireEvent.click(rowButton(OLDER_ROW));
		expect(await screen.findByRole('heading', { name: 'Report for 2–8 Nov 2026' })).toBeInTheDocument();
		expect(await screen.findByRole('region', { name: 'Internet use' })).toBeInTheDocument();
		expect(screen.queryByText(/^Couldn't refresh the reports/)).not.toBeInTheDocument();
	});

	it("Generate now's report can't be overwritten by a pick still in flight", async () => {
		const b = held();
		const schedulesAgain = held();
		let loads = 0;
		const NEW: Report = { ...REPORT, id: '20261121T153000Z-abcdef', trigger: 'manual', period: { ...REPORT.period, first: '2026-11-14', last: '2026-11-20' } };
		stubFetch({
			// the refresh after Generate now waits, so a late pick can land before it
			schedules: () => (++loads === 1 ? ok(SCHEDULES) : schedulesAgain.reply),
			report: (id) => (id === OLDER.id ? b.reply : ok(REPORT)),
			generate: ok(NEW),
		});
		render(Page);
		await shownReport('9–15 Nov 2026');

		await fireEvent.click(rowButton(OLDER_ROW));
		await fireEvent.click(screen.getByRole('button', { name: 'Generate now' }));
		expect(await screen.findByRole('heading', { name: 'Report for 14–20 Nov 2026' })).toBeInTheDocument();

		b.release(ok(OLDER));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.getByRole('heading', { name: 'Report for 14–20 Nov 2026' })).toBeInTheDocument();
		expect(within(screen.getByRole('region', { name: 'Data cap' })).getByText('Unavailable')).toBeInTheDocument();
		schedulesAgain.release(ok(SCHEDULES));
	});

	it('a report that fails to load shows its own error, with the history still there', async () => {
		stubFetch({ report: () => ({ status: 503, body: {} }) });
		render(Page);

		expect(await screen.findByText("Couldn't load this report: the request failed.")).toBeInTheDocument();
		expect(screen.getByRole('table', { name: 'Report history' })).toBeInTheDocument();
	});

	it('history sorts both ways on every column, and choosing a row shows that report', async () => {
		stubFetch();
		render(Page);
		await shownReport('9–15 Nov 2026');
		const table = screen.getByRole('table', { name: 'Report history' });

		for (const name of ['Period', 'Generated', 'Trigger', 'Delivery']) {
			const header = within(table).getByRole('columnheader', { name: new RegExp(name) });
			await fireEvent.click(within(header).getByRole('button'));
			const first = header.getAttribute('aria-sort');
			await fireEvent.click(within(header).getByRole('button'));
			expect([first, header.getAttribute('aria-sort')].sort()).toEqual(['ascending', 'descending']);
		}

		await fireEvent.click(within(table).getByRole('button', { name: /^Show the report for 2–8 Nov 2026, generated Thu 12 Nov/ }));
		expect(await screen.findByRole('heading', { name: 'Report for 2–8 Nov 2026' })).toBeInTheDocument();
		expect(calls.map((c) => c.url)).toContain(`/api/reports/history/${CARD_SCHEDULE.id}/${OLDER.id}`);
		expect(within(table).getByRole('button', { name: /generated Thu 12 Nov/ }).closest('tr')).toHaveAttribute('aria-current', 'true');
		expect(screen.getByText('Generated Thu 12 Nov, 14:15 · Manual · Not emailed')).toBeInTheDocument();
	});

	it("Generate now shows the daemon's 409 as it words it, and makes nothing", async () => {
		const busy = "A report is being generated. It will appear in the history when it's done.";
		stubFetch({ generate: { status: 409, body: { error: busy } } });
		render(Page);
		await shownReport('9–15 Nov 2026');

		await fireEvent.click(screen.getByRole('button', { name: 'Generate now' }));
		const notice = await screen.findByText(busy);
		expect(notice.closest('.notice')).toHaveClass('is-warn');
		expect(calls.filter((c) => c.method === 'POST').map((c) => c.url)).toEqual([`/api/reports/generate/${CARD_SCHEDULE.id}`]);
	});

	it('Generate now shows the new report and says it is not emailed', async () => {
		stubFetch({ generate: ok(OLDER) });
		render(Page);
		await shownReport('9–15 Nov 2026');

		await fireEvent.click(screen.getByRole('button', { name: 'Generate now' }));
		expect(await screen.findByText("Report made for 2–8 Nov 2026. Generate now keeps it here and doesn't email it.")).toBeInTheDocument();
		expect(await screen.findByRole('heading', { name: 'Report for 2–8 Nov 2026' })).toBeInTheDocument();
	});
});
