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
// OLD CODE: const save = () => fireEvent.click(screen.getByRole('button', { name: 'Save weekly report' })); (the 409 reload holds "Saving…" a moment longer)
const save = async () => fireEvent.click(await screen.findByRole('button', { name: 'Save weekly report' }));
const listed = (schedules: ReportSchedule[], tz = 'Europe/London'): Reply => ({ status: 200, body: { schedules, tz } });
const toggle = () => screen.getByRole('switch', { name: 'Make a weekly report' });

describe('Weekly report card (NET-340)', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('binds to the card schedule when a daily schedule is listed first', async () => {
		stub({ status: 200, body: SCHEDULES });
		render(Card);

		expect(await screen.findByDisplayValue('Monday')).toBeInTheDocument();
		expect((screen.getByLabelText('Time') as HTMLSelectElement).value).toBe('8');
		expect(recipients().value).toBe('owner@example.com\nfamily@example.com');
		// OLD CODE: expect(screen.getByRole('switch', { name: 'Email a weekly report' })).toBeChecked(); (NET-357: with no addresses the report is only kept)
		expect(screen.getByRole('switch', { name: 'Make a weekly report' })).toBeChecked();
		expect(screen.queryByDisplayValue(/noc@example.com/)).not.toBeInTheDocument();
	});

	it('says what is sent and in which zone', async () => {
		stub({ status: 200, body: SCHEDULES });
		render(Card);

		expect(await screen.findByText('Times are in Europe/London.')).toBeInTheDocument();
		expect(
			screen.getByText(/^Internet use, alerts, new devices, offline incidents and the data cap, by email to these addresses\./),
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
		// NET-357: a new schedule starts off, so turning it on is part of the first save
		await fireEvent.click(toggle());
		await save();

		await screen.findByText(/^Saved\./);
		expect(putBodies(fn)).toEqual([{ enabled: true, weekday: 4, hour: 8, recipients: [], confirm: true }]);
	});

	it('with no card schedule the switch starts off, and saving it untouched keeps it off (NET-357)', async () => {
		const fn = stub({ status: 200, body: SCHEDULES_EMPTY });
		render(Card);

		expect(await screen.findByRole('switch', { name: 'Make a weekly report' })).not.toBeChecked();
		await save();

		expect(await screen.findByText('Saved. The weekly report is off.')).toBeInTheDocument();
		expect(putBodies(fn)[0]).toMatchObject({ enabled: false });
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

	// OLD CODE START — TypeScript review: the card kept the stale token, so every retry met the same 409
	// it("settings changed in another window: the stale-token 409 shows as the daemon words it", async () => { … });
	// OLD CODE END
	describe('after a stale-token 409', () => {
		const STALE = 'These settings changed in another window. Reload and check them.';
		/** The schedule another window saved: a new token and rev, and 18:00. */
		const CHANGED = { ...CARD_SCHEDULE, hour: 18, rev: 4, confirm_token: 'fresh-token' };

		// OLD CODE: /** The list answers SCHEDULES, then the changed schedule; the first PUT is refused, later ones save. */ function stubStale() { (NET-357: per test)
		/** The list answers `first`, then `changed`; the first PUT is refused, later ones save. */
		function stubStale(first: unknown = SCHEDULES, changed: ReportSchedule = CHANGED) {
			let lists = 0;
			let puts = 0;
			const fn = vi.fn(async (url: string, init?: RequestInit) => {
				if (url === '/api/reports/card' && init?.method === 'PUT') {
					const body = JSON.parse(String(init.body));
					const reply = ++puts === 1 ? { status: 409, body: { error: STALE } } : { status: 200, body: { ...changed, ...body, rev: 5, confirm_token: 'next-token' } };
					return { ok: reply.status < 400, status: reply.status, json: async () => reply.body };
				}
				const body = ++lists === 1 ? first : { schedules: [changed], tz: 'Europe/London' };
				return { ok: true, status: 200, json: async () => body };
			});
			vi.stubGlobal('fetch', fn);
			return fn;
		}

		it('reloads the schedule, so the next Save carries the fresh token and rev', async () => {
			const fn = stubStale();
			render(Card);
			await screen.findByDisplayValue('Monday');

			await save();
			expect(await screen.findByText('These settings changed in another window. NetTap loaded them: check them and save again.')).toBeInTheDocument();
			// nothing was edited here, so the other window's 18:00 shows
			expect((screen.getByLabelText('Time') as HTMLSelectElement).value).toBe('18');

			await save();
			expect(await screen.findByText('Saved. The weekly report is on.')).toBeInTheDocument();
			const [first, second] = putBodies(fn);
			expect(first).toMatchObject({ confirm_token: CARD_SCHEDULE.confirm_token, rev: CARD_SCHEDULE.rev });
			expect(second).toMatchObject({ confirm_token: 'fresh-token', rev: 4, hour: 18 });
		});

		it("keeps the owner's unsaved edits through the reload", async () => {
			const fn = stubStale();
			render(Card);
			await screen.findByDisplayValue('Monday');

			await fireEvent.input(recipients(), { target: { value: 'mine@example.com' } });
			await save();
			expect(await screen.findByText(/NetTap loaded them and kept your edits: check them and save again\.$/)).toBeInTheDocument();
			expect(recipients().value).toBe('mine@example.com');
			expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

			await save();
			await screen.findByText('Saved. The weekly report is on.');
			expect(putBodies(fn)[1]).toMatchObject({ recipients: ['mine@example.com'], confirm_token: 'fresh-token', rev: 4 });
		});

		// NET-357: the retry sent this window's whole form, so the other window's switch and addresses were undone
		it("an edit to the day alone keeps the other window's switch and addresses", async () => {
			const fn = stubStale(SCHEDULES, { ...CHANGED, enabled: false, recipients: ['owner@example.com'] });
			render(Card);
			await screen.findByDisplayValue('Monday');

			await fireEvent.change(screen.getByLabelText('Day'), { target: { value: '4' } });
			await save();
			expect(await screen.findByText(/NetTap loaded them and kept your edits: check them and save again\.$/)).toBeInTheDocument();
			expect(toggle()).not.toBeChecked();
			expect(recipients().value).toBe('owner@example.com');

			await save();
			await screen.findByText('Saved. The weekly report is off.');
			expect(putBodies(fn)[1]).toMatchObject({ enabled: false, weekday: 4, hour: 18, recipients: ['owner@example.com'], confirm_token: 'fresh-token', rev: 4 });
		});

		it('when both windows changed the addresses, the saved list shows, yours is named, and a removed one is not sent back', async () => {
			const withBob = { ...CARD_SCHEDULE, recipients: ['owner@example.com', 'bob@example.com'] };
			const fn = stubStale({ schedules: [withBob], tz: 'Europe/London' }, { ...CHANGED, recipients: ['owner@example.com'] });
			render(Card);
			await screen.findByDisplayValue('Monday');

			await fireEvent.input(recipients(), { target: { value: 'owner@example.com\nbob@example.com\nnew@example.com' } });
			await save();
			expect(
				await screen.findByText(
					'These settings changed in another window. NetTap loaded them and kept your other edits. The addresses changed there too, so the saved ones are shown; yours were: owner@example.com, bob@example.com, new@example.com. Check them and save again.',
				),
			).toBeInTheDocument();
			expect(recipients().value).toBe('owner@example.com');

			await save();
			await screen.findByText('Saved. The weekly report is on.');
			expect(putBodies(fn)[1]).toMatchObject({ recipients: ['owner@example.com'], confirm_token: 'fresh-token', rev: 4 });
		});

		it("a 409 where nothing changed (a send in progress) keeps the daemon's words", async () => {
			stub({ status: 200, body: SCHEDULES }, { status: 409, body: { error: STALE } });
			render(Card);
			await screen.findByDisplayValue('Monday');

			await save();
			expect(await screen.findByRole('alert')).toHaveTextContent(STALE);
		});
	});

	it("a failed load shows the daemon's reason, with no form to save, and Try again reloads it", async () => {
		// OLD CODE: stub({ status: 503, body: {} }); (TypeScript review: the daemon's sentence was dropped, and this test locked that in)
		stub({ status: 503, body: { error: 'Report schedules are unavailable.' } });
		render(Card);
		expect(await screen.findByText("Couldn't load the weekly report: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('Report schedules are unavailable.')).toBeInTheDocument();
		expect(screen.queryByText(/Check that NetTap is running/)).not.toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Save weekly report' })).not.toBeInTheDocument();

		stub({ status: 200, body: SCHEDULES });
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(await screen.findByDisplayValue('Monday')).toBeInTheDocument();
	});

	it('a load that never reaches NetTap keeps the generic hint', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		render(Card);
		expect(await screen.findByText('Check that NetTap is running on the System page, then try again.')).toBeInTheDocument();
	});
});
