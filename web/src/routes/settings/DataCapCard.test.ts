/**
 * F6 (NET-339): Settings › Network's "Monthly data cap" card loads the cap and this month's use,
 * checks the typed GB, saves it, and keeps the typed value when the daemon refuses it.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import type { BandwidthCap } from '$lib/api/bandwidth';
import Card from './DataCapCard.svelte';

const GB = 1e9;
const CAP: BandwidthCap = {
	monthly_cap_bytes: 100 * GB, monthly_cap_gb: 100, enabled: true, current_usage_bytes: 82.4 * GB, usage_percent: 82.4,
	tz: 'Europe/London', since: '2026-10-01', complete: true, lower_bound_bytes: 82.4 * GB, first_day: '2026-11-01',
};
const NO_CAP: BandwidthCap = { ...CAP, monthly_cap_bytes: 0, monthly_cap_gb: 0, enabled: false, usage_percent: 0 };

type Reply = { status: number; body: unknown };

/** GET /api/bandwidth/cap answers `cap` (or `get`), PUT answers `put` or what a saved cap would. */
function stubCap(cap: BandwidthCap | Reply, put?: Reply) {
	const fn = vi.fn(async (url: string, init?: RequestInit) => {
		if (url === '/api/settings/bandwidth-cap' && init?.method === 'PUT') {
			const gb = JSON.parse(String(init.body)).monthly_cap_gb as number;
			const reply = put ?? { status: 200, body: { result: 'saved', monthly_cap_gb: Math.round(gb * 10) / 10, monthly_cap_bytes: Math.round(gb * GB) } };
			return { ok: reply.status < 400, status: reply.status, json: async () => reply.body };
		}
		const reply = 'status' in cap ? cap : { status: 200, body: cap };
		return { ok: reply.status < 400, status: reply.status, json: async () => reply.body };
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

const input = () => screen.getByLabelText('Monthly cap in GB') as HTMLInputElement;
const saveButton = () => screen.getByRole('button', { name: 'Save data cap' });
const puts = (fn: ReturnType<typeof stubCap>) => fn.mock.calls.filter(([, init]) => init?.method === 'PUT');

describe('Monthly data cap card (F6)', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows loading until the cap lands, then the saved cap and the helper text', async () => {
		stubCap(CAP);
		render(Card);
		expect(screen.getByRole('status')).toHaveTextContent('Loading your data cap');

		expect(await screen.findByText('82.4 GB of 100.0 GB used this month')).toBeInTheDocument();
		expect(input().value).toBe('100');
		expect(screen.getByText(/^NetTap warns you at 80%, at 100%, and when the month is on track to go over\./)).toBeInTheDocument();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it('a failed load says so, with no form to save, and Try again reloads it', async () => {
		stubCap({ status: 503, body: {} });
		render(Card);
		expect(await screen.findByText("Couldn't load your data cap: the request failed.")).toBeInTheDocument();
		expect(screen.queryByLabelText('Monthly cap in GB')).not.toBeInTheDocument();

		stubCap(CAP);
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(await screen.findByText('82.4 GB of 100.0 GB used this month')).toBeInTheDocument();
	});

	it('no cap: a blank field and the use without "of …"', async () => {
		stubCap(NO_CAP);
		render(Card);
		expect(await screen.findByText('82.4 GB used this month')).toBeInTheDocument();
		expect(input().value).toBe('');
		expect(input()).toHaveAttribute('placeholder', 'No cap');
	});

	it.each([
		['at least, counted since a day inside the month', { complete: false, since: '2026-11-13' }, ['At least 82.4 GB of 100.0 GB used this month, counted since 13 Nov']],
		[
			'at least, counting began before the month',
			{ complete: false, since: '2026-10-01' },
			['At least 82.4 GB of 100.0 GB used this month, some days are still being counted'],
		],
		[
			'recounting, with the lower bound and never the total',
			{ complete: false, since: '2026-11-13', lower_bound_bytes: 50 * GB },
			['At least 50.0 GB of 100.0 GB used this month, counted since 13 Nov', 'Recounting under your new exclusions'],
		],
		['still counting, before the first count', { since: null, complete: false, current_usage_bytes: 0, lower_bound_bytes: 0 }, ['Still counting']],
	] as const)('use line: %s', async (_name, extra, lines) => {
		stubCap({ ...CAP, ...extra });
		render(Card);
		for (const line of lines) expect(await screen.findByText(line)).toBeInTheDocument();
		// only the line's own figure: the total never shows as "used" when it isn't safe
		expect(screen.queryByText(/^82\.4 GB/)).not.toBeInTheDocument();
	});

	it('saves the typed GB, then shows it as saved', async () => {
		const fn = stubCap(CAP);
		render(Card);
		await screen.findByText('82.4 GB of 100.0 GB used this month');

		await fireEvent.input(input(), { target: { value: ' 250.5 ' } });
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
		await fireEvent.click(saveButton());

		expect(await screen.findByText('Data cap saved.')).toBeInTheDocument();
		expect(JSON.parse(String(puts(fn)[0][1]?.body))).toEqual({ monthly_cap_gb: 250.5 });
		expect(input().value).toBe('250.5');
		expect(screen.getByText('82.4 GB of 250.5 GB used this month')).toBeInTheDocument();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it.each(['', '0'])('saving %j removes the cap', async (typed) => {
		const fn = stubCap(CAP);
		render(Card);
		await screen.findByText('82.4 GB of 100.0 GB used this month');

		await fireEvent.input(input(), { target: { value: typed } });
		await fireEvent.click(saveButton());

		expect(await screen.findByText('Data cap removed. NetTap sends no cap warnings.')).toBeInTheDocument();
		expect(JSON.parse(String(puts(fn)[0][1]?.body))).toEqual({ monthly_cap_gb: 0 });
		expect(input().value).toBe('');
		expect(screen.getByText('82.4 GB used this month')).toBeInTheDocument();
	});

	it.each(['-1', '1000001', 'lots', 'Infinity'])('refuses %j inline, without a request', async (typed) => {
		const fn = stubCap(CAP);
		render(Card);
		await screen.findByText('82.4 GB of 100.0 GB used this month');

		await fireEvent.input(input(), { target: { value: typed } });
		await fireEvent.click(saveButton());

		const error = screen.getByRole('alert');
		expect(error).toHaveTextContent('Enter a number of GB from 0 to 1,000,000 (1 PB), or leave it blank for no cap.');
		expect(error).toHaveClass('field-error');
		expect(input()).toHaveAttribute('aria-invalid', 'true');
		expect(puts(fn)).toHaveLength(0);

		// typing again clears it
		await fireEvent.input(input(), { target: { value: '5' } });
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
		expect(input()).not.toHaveAttribute('aria-invalid');
	});

	it('takes 1 PB, the most the daemon keeps', async () => {
		const fn = stubCap(CAP);
		render(Card);
		await screen.findByText('82.4 GB of 100.0 GB used this month');

		await fireEvent.input(input(), { target: { value: '1000000' } });
		await fireEvent.click(saveButton());

		expect(await screen.findByText('Data cap saved.')).toBeInTheDocument();
		expect(JSON.parse(String(puts(fn)[0][1]?.body))).toEqual({ monthly_cap_gb: 1_000_000 });
	});

	it("a refused save shows the daemon's reason and keeps the typed value", async () => {
		stubCap(CAP, { status: 500, body: { error: "Couldn't save the cap" } });
		render(Card);
		await screen.findByText('82.4 GB of 100.0 GB used this month');

		await fireEvent.input(input(), { target: { value: '300' } });
		await fireEvent.click(saveButton());

		expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't save the cap");
		expect(input().value).toBe('300');
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
		// the use line still reads the saved cap
		expect(screen.getByText('82.4 GB of 100.0 GB used this month')).toBeInTheDocument();
	});

	it('the button says it is saving, and is off until the reply lands', async () => {
		let answer: () => void = () => {};
		const gate = new Promise<void>((resolve) => (answer = resolve));
		vi.stubGlobal(
			'fetch',
			vi.fn(async (_url: string, init?: RequestInit) => {
				if (init?.method === 'PUT') {
					await gate;
					return { ok: true, status: 200, json: async () => ({ result: 'saved', monthly_cap_gb: 5, monthly_cap_bytes: 5 * GB }) };
				}
				return { ok: true, status: 200, json: async () => CAP };
			}),
		);
		render(Card);
		await screen.findByText('82.4 GB of 100.0 GB used this month');

		await fireEvent.input(input(), { target: { value: '5' } });
		await fireEvent.click(saveButton());
		expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();

		answer();
		expect(await screen.findByText('Data cap saved.')).toBeInTheDocument();
		expect(saveButton()).toBeEnabled();
	});
});
