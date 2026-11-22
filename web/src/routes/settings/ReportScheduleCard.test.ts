/**
 * NET-340: Settings › Notifications' weekly report card binds to the `card: true` schedule (not the
 * first listed), confirms on every save with the token and rev it was shown, says what is sent and
 * in which zone, and shows the daemon's refusals as it words them.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import type { ReportSchedule } from '$lib/api/reports';
import { CARD_SCHEDULE, SCHEDULES, SCHEDULES_EMPTY } from '../../../e2e/visual/fixtures/reports';
import Card from './ReportScheduleCard.svelte';

type Reply = { status: number; body: unknown };

/** GET /api/reports/schedules answers `list`; PUT /api/reports/card answers `put`, or echoes the body onto the card schedule. */
function stub(list: Reply, put?: Reply) {
	const fn = vi.fn(async (url: string, init?: RequestInit) => {
		if (url === '/api/reports/card' && init?.method === 'PUT') {
			const body = JSON.parse(String(init.body));
			const reply = put ?? { status: 200, body: { ...CARD_SCHEDULE, ...body, rev: (body.rev ?? 0) + 1, needs_review: false } };
			return { ok: reply.status < 400, status: reply.status, json: async () => reply.body };
		}
		return { ok: list.status < 400, status: list.status, json: async () => list.body };
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

const putBodies = (fn: ReturnType<typeof stub>) => fn.mock.calls.filter(([, init]) => init?.method === 'PUT').map(([, init]) => JSON.parse(String(init!.body)));
const recipients = () => screen.getByLabelText('Email addresses, one per line') as HTMLTextAreaElement;
const save = () => fireEvent.click(screen.getByRole('button', { name: 'Save weekly report' }));
const listed = (schedules: ReportSchedule[], tz = 'Europe/London'): Reply => ({ status: 200, body: { schedules, tz } });

describe('Weekly report card (NET-340)', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('binds to the card schedule when a daily schedule is listed first', async () => {
		stub({ status: 200, body: SCHEDULES });
		render(Card);

		expect(await screen.findByDisplayValue('Monday')).toBeInTheDocument();
		expect((screen.getByLabelText('Time') as HTMLSelectElement).value).toBe('8');
		expect(recipients().value).toBe('owner@example.com\nfamily@example.com');
		expect(screen.getByRole('switch', { name: 'Email a weekly report' })).toBeChecked();
		expect(screen.queryByDisplayValue(/noc@example.com/)).not.toBeInTheDocument();
	});

	it('says what is sent and in which zone', async () => {
		stub({ status: 200, body: SCHEDULES });
		render(Card);

		expect(await screen.findByText('Times are in Europe/London.')).toBeInTheDocument();
		expect(
			screen.getByText(/^Internet use, alerts, new devices, offline incidents and the data cap, as plain-text email to these addresses\./),
		).toBeInTheDocument();
	});

	it('Save confirms with the token and rev it was shown, sending one trimmed address per line', async () => {
		const fn = stub({ status: 200, body: SCHEDULES });
		render(Card);
		await screen.findByDisplayValue('Monday');

		await fireEvent.input(recipients(), { target: { value: ' owner@example.com \n\nnew@example.com\n' } });
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
		await save();

		expect(await screen.findByText('Saved. The weekly report is on.')).toBeInTheDocument();
		expect(putBodies(fn)).toEqual([
			{ enabled: true, weekday: 0, hour: 8, recipients: ['owner@example.com', 'new@example.com'], confirm: true, confirm_token: CARD_SCHEDULE.confirm_token, rev: CARD_SCHEDULE.rev },
		]);
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it('an unchanged Save still confirms (the daemon decides what it changes)', async () => {
		const fn = stub({ status: 200, body: SCHEDULES });
		render(Card);
		await screen.findByDisplayValue('Monday');

		await save();
		await screen.findByText('Saved. The weekly report is on.');
		expect(putBodies(fn)[0]).toMatchObject({ confirm: true, confirm_token: CARD_SCHEDULE.confirm_token, rev: CARD_SCHEDULE.rev });
	});

	it('with no card schedule, the first save creates it: no token or rev, and the list zone named', async () => {
		const fn = stub({ status: 200, body: SCHEDULES_EMPTY });
		render(Card);

		expect(await screen.findByText('Times are in Europe/London.')).toBeInTheDocument();
		expect(recipients().value).toBe('');
		await fireEvent.change(screen.getByLabelText('Day'), { target: { value: '4' } });
		await save();

		await screen.findByText(/^Saved\./);
		expect(putBodies(fn)).toEqual([{ enabled: true, weekday: 4, hour: 8, recipients: [], confirm: true }]);
	});

	it("names NetTap's zone when the daemon sends none", async () => {
		stub({ status: 200, body: { schedules: [] } });
		render(Card);
		expect(await screen.findByText("Times are in NetTap's time zone.")).toBeInTheDocument();
	});

	it('a schedule changed without confirming says it is paused', async () => {
		stub(listed([{ ...CARD_SCHEDULE, needs_review: true, confirmed: false }]));
		render(Card);
		expect(await screen.findByText('Paused until you check the recipients and save.')).toBeInTheDocument();
	});

	it("while a report is being sent, Save shows the daemon's 409 and keeps the form", async () => {
		const sending = 'A report is being sent. Try again in a minute.';
		stub(listed([{ ...CARD_SCHEDULE, sending: true }]), { status: 409, body: { error: sending } });
		render(Card);
		await screen.findByDisplayValue('Monday');

		await fireEvent.input(recipients(), { target: { value: 'other@example.com' } });
		await save();

		expect(await screen.findByRole('alert')).toHaveTextContent(sending);
		expect(recipients().value).toBe('other@example.com');
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
	});

	it("settings changed in another window: the stale-token 409 shows as the daemon words it", async () => {
		const stale = 'These settings changed in another window. Reload and check them.';
		stub({ status: 200, body: SCHEDULES }, { status: 409, body: { error: stale } });
		render(Card);
		await screen.findByDisplayValue('Monday');

		await save();
		expect(await screen.findByRole('alert')).toHaveTextContent(stale);
	});

	it('a failed load says so, with no form to save, and Try again reloads it', async () => {
		stub({ status: 503, body: {} });
		render(Card);
		expect(await screen.findByText("Couldn't load the weekly report: the request failed.")).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Save weekly report' })).not.toBeInTheDocument();

		stub({ status: 200, body: SCHEDULES });
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(await screen.findByDisplayValue('Monday')).toBeInTheDocument();
	});
});
