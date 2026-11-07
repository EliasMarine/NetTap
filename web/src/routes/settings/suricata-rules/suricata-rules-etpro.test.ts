import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { formatTime } from '$lib/utils/time';
import Page from './+page.svelte';

/** NET-191 slice 2: the last rule update, suricata-update's sources and the ET Pro code. */

const LIVE = {
	available: true,
	enabled_rules: 64307,
	disabled_rules: 15954,
	last_updated: '2026-11-07T00:00:36+00:00',
	sources: ['https://sslbl.abuse.ch/blacklist/sslblacklist.rules'],
	schedule: '0 0 * * *',
	error: null,
};

const UPDATE = {
	state: 'active',
	attempt: '2026-11-07T00:00:10+00:00',
	exit_code: 0,
	reason: '',
	last_success: '2026-11-07T00:00:36+00:00',
	last_activation: '2026-11-07T00:01:00+00:00',
	stale: false,
	recovery_pending: false,
};

const ETPRO_OFF = { configured: false, active: false, last_update_ok: null, applying: false, activation: null };
const ETPRO_ON = {
	configured: true,
	active: true,
	last_update_ok: true,
	applying: false,
	activation: {
		state: 'active',
		finished_at: '2026-11-07T00:05:00+00:00',
		rules_loaded: 70000,
		rules_failed: 0,
		etpro_rules: 48211,
		enabled_sources: ['et/pro'],
		update_state: 'active',
		message: 'ET Pro is active.',
	},
};

type Reply = { status: number; body: unknown };

/** GETs answer from `gets` (HTTP 500 when absent); POST/DELETE answer from `writes`, keyed "METHOD url". */
function stubApi(gets: Record<string, unknown>, writes: Record<string, Reply> = {}) {
	const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
		const method = init?.method ?? 'GET';
		const reply: Reply =
			method === 'GET'
				? gets[url]
					? { status: 200, body: gets[url] }
					: { status: 500, body: {} }
				: (writes[`${method} ${url}`] ?? { status: 500, body: {} });
		return { ok: reply.status >= 200 && reply.status < 300, status: reply.status, json: async () => reply.body };
	});
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

function page(live: object = {}, etpro: object = ETPRO_OFF) {
	return {
		'/api/suricata/rules/live': { ...LIVE, ...live },
		'/api/suricata/rules/custom': { content: '' },
		'/api/suricata/rules/commercial': etpro,
	};
}

const writesTo = (f: ReturnType<typeof stubApi>, method: string) =>
	f.mock.calls.filter(([url, init]) => url === '/api/suricata/rules/commercial' && init?.method === method);

afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('Suricata rules page — last rule update', () => {
	it('says when the rules last updated', async () => {
		stubApi(page({ update: UPDATE }));
		render(Page);

		expect(await screen.findByText(`Rules last updated ${formatTime(UPDATE.last_success)}.`)).toBeInTheDocument();
	});

	it('says prepared rules load when Suricata next starts', async () => {
		stubApi(page({ update: { ...UPDATE, state: 'prepared' } }));
		render(Page);

		expect(
			await screen.findByText(`Rules last updated ${formatTime(UPDATE.last_success)}. Suricata loads them when it next starts.`),
		).toBeInTheDocument();
	});

	it('warns that a failed update left the last good rules running', async () => {
		stubApi(page({ update: { ...UPDATE, state: 'failed', exit_code: 1, reason: 'the ET Open download timed out' } }));
		render(Page);

		const line = await screen.findByText(
			`The last rule update failed ${formatTime(UPDATE.attempt)}: the ET Open download timed out. Suricata keeps running the last good rules.`,
		);
		expect(line.closest('.notice')).toHaveClass('is-warn');
	});

	it('flags an unconfirmed restore as an error, ahead of the failure', async () => {
		stubApi(page({ update: { ...UPDATE, state: 'failed', recovery_pending: true, reason: 'Suricata did not answer' } }));
		render(Page);

		const line = await screen.findByText(
			"Restoring the last good rules isn't confirmed: Suricata did not answer. It is retried at the next update or restart.",
		);
		expect(line.closest('.notice')).toHaveClass('is-error');
		expect(screen.queryByText(/The last rule update failed/)).not.toBeInTheDocument();
	});

	it('warns when no update has succeeded in 48 hours', async () => {
		stubApi(page({ update: { ...UPDATE, stale: true } }));
		render(Page);

		const line = await screen.findByText(`No successful rule update in 48 hours (last ${formatTime(UPDATE.last_success)}).`);
		expect(line.closest('.notice')).toHaveClass('is-warn');
	});

	it("gives the daemon's reason when Update rules now fails", async () => {
		const failed = { ...UPDATE, state: 'failed', reason: 'the ET Open download timed out' };
		const body = { success: false, output: 'a long suricata-update log', reload_output: '', status: failed };
		stubApi(page({ update: UPDATE }), { 'POST /api/suricata/rules/update': { status: 500, body } });
		render(Page);
		await screen.findByText(/^Rules last updated/);

		await fireEvent.click(screen.getByRole('button', { name: 'Update rules now' }));

		expect(await screen.findByText('Rule update failed: the ET Open download timed out')).toBeInTheDocument();
	});

	it('says an update still running is not a failure', async () => {
		stubApi(page({ update: UPDATE }), {
			'POST /api/suricata/rules/update': { status: 202, body: { success: false, output: '', reload_output: '', running: true } },
		});
		render(Page);
		await screen.findByText(/^Rules last updated/);

		await fireEvent.click(screen.getByRole('button', { name: 'Update rules now' }));

		const note = await screen.findByText('The rule update is still running. Refresh this page in a few minutes to see the result.');
		expect(note.closest('.notice')).toHaveClass('is-ok');
	});

	it('says nothing is recorded when an older daemon sends no update', async () => {
		stubApi(page());
		render(Page);

		expect(await screen.findByText('No rule update has been recorded yet.')).toBeInTheDocument();
	});
});

describe('Suricata rules page — rule sources', () => {
	it("lists suricata-update's sources by name, counting them", async () => {
		stubApi(page({ enabled_sources: ['et/open', 'abuse.ch/sslbl-blacklist', 'echap/stalkerware', 'ipfire/dbl', 'oisf/trafficid'] }));
		render(Page);

		expect(await screen.findByText('Emerging Threats Open')).toBeInTheDocument();
		expect(screen.getByText('abuse.ch/sslbl-blacklist')).toBeInTheDocument();
		expect(screen.getByText('Echap stalkerware indicators')).toBeInTheDocument();
		expect(screen.getByText('IPFire DBL (malware and phishing only)')).toBeInTheDocument();
		// a source without a friendly name shows its own name
		expect(screen.getAllByText('oisf/trafficid')).toHaveLength(2);
		expect(screen.queryByText(LIVE.sources[0])).not.toBeInTheDocument();
		expect(screen.getByText('Sources').nextElementSibling).toHaveTextContent(/^5$/);
	});

	it('falls back to the URL list when the daemon sends no enabled sources', async () => {
		stubApi(page({ enabled_sources: [] }));
		render(Page);

		expect(await screen.findByText('abuse.ch SSL Blacklist')).toBeInTheDocument();
		expect(screen.getByText(LIVE.sources[0])).toBeInTheDocument();
	});
});

describe('Suricata rules page — ET Pro card', () => {
	it('shows its loading state until the first load lands', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);

		expect(screen.getByText('Loading the ET Pro status')).toBeInTheDocument();
	});

	it('shows its error state and retries', async () => {
		const { '/api/suricata/rules/commercial': _etpro, ...withoutEtPro } = page();
		stubApi(withoutEtPro);
		render(Page);

		expect(await screen.findByText("Couldn't read the ET Pro status: the request failed.")).toBeInTheDocument();
		expect(screen.queryByLabelText('ET Pro code')).not.toBeInTheDocument();

		stubApi(page());
		const card = screen.getByText("Couldn't read the ET Pro status: the request failed.").closest('.card') as HTMLElement;
		await fireEvent.click(within(card).getByRole('button', { name: 'Try again' }));

		expect(await screen.findByLabelText('ET Pro code')).toBeInTheDocument();
	});

	it('shows the saved code, the ET Pro rule count and the last activation', async () => {
		stubApi(page({ etpro_rules: 48211 }, ETPRO_ON));
		render(Page);

		expect(await screen.findByText('Saved')).toBeInTheDocument();
		expect(screen.getByText('Yes — 48,211 ET Pro rules active')).toBeInTheDocument();
		expect(screen.getByText('OK')).toBeInTheDocument();
		expect(screen.getByText('ET Pro rules are active: 48,211 rules loaded.')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Remove code' })).toBeInTheDocument();
	});

	it('shows no code, no remove button and a failed activation message', async () => {
		const failed = { ...ETPRO_OFF, last_update_ok: false, activation: { ...ETPRO_ON.activation, state: 'timeout', message: 'Suricata took too long to restart.' } };
		stubApi(page({}, failed));
		render(Page);

		expect(await screen.findByText('Not set')).toBeInTheDocument();
		expect(screen.getByText('No')).toBeInTheDocument();
		expect(screen.getByText('Failed')).toBeInTheDocument();
		expect(screen.getByText('Suricata took too long to restart.').closest('.notice')).toHaveClass('is-warn');
		expect(screen.queryByRole('button', { name: 'Remove code' })).not.toBeInTheDocument();
	});

	it('rejects a malformed code without calling the daemon', async () => {
		const f = stubApi(page());
		render(Page);
		const input = await screen.findByLabelText('ET Pro code');

		await fireEvent.input(input, { target: { value: 'short-code!' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save code' }));

		expect(screen.getByText('An ET Pro code is 16 to 64 letters and digits.')).toBeInTheDocument();
		expect(input).toHaveAttribute('aria-invalid', 'true');
		expect(writesTo(f, 'POST')).toHaveLength(0);
	});

	it('posts a valid code once, clears it and says Suricata is restarting', async () => {
		const f = stubApi(page(), { 'POST /api/suricata/rules/commercial': { status: 202, body: { saved: true, applying: true } } });
		render(Page);
		const input = (await screen.findByLabelText('ET Pro code')) as HTMLInputElement;
		expect(input).toHaveAttribute('type', 'password');
		expect(input).toHaveAttribute('autocomplete', 'off');

		await fireEvent.input(input, { target: { value: 'abcd1234ABCD5678' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save code' }));

		expect(await screen.findByText('Code saved. Suricata is restarting with ET Pro.')).toBeInTheDocument();
		const posts = writesTo(f, 'POST');
		expect(posts).toHaveLength(1);
		expect(posts[0][1]?.body).toBe(JSON.stringify({ code: 'abcd1234ABCD5678' }));
		expect(input.value).toBe('');
		// the code is never written anywhere on the page
		expect(document.body.textContent).not.toContain('abcd1234ABCD5678');
	});

	it("shows the daemon's reason when the code is refused, and keeps it for a fix", async () => {
		stubApi(page(), { 'POST /api/suricata/rules/commercial': { status: 400, body: { error: 'Proofpoint did not accept this code.' } } });
		render(Page);
		const input = (await screen.findByLabelText('ET Pro code')) as HTMLInputElement;

		await fireEvent.input(input, { target: { value: 'abcd1234ABCD5678' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save code' }));

		const banner = await screen.findByText('Proofpoint did not accept this code.');
		expect(banner.closest('.notice')).toHaveClass('is-error');
		expect(input.value).toBe('abcd1234ABCD5678');
	});

	it('removes the code only after a confirm click, with a way to cancel', async () => {
		const f = stubApi(page({}, ETPRO_ON), { 'DELETE /api/suricata/rules/commercial': { status: 202, body: { cleared: true, applying: true } } });
		render(Page);

		await fireEvent.click(await screen.findByRole('button', { name: 'Remove code' }));
		expect(writesTo(f, 'DELETE')).toHaveLength(0);
		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
		expect(screen.getByRole('button', { name: 'Remove code' })).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Remove code' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Confirm: remove and restart Suricata' }));

		expect(await screen.findByText('Code removed. Suricata is restarting with ET Open.')).toBeInTheDocument();
		expect(writesTo(f, 'DELETE')).toHaveLength(1);
	});

	it('says Suricata is restarting and looks again every 15 s until it is done', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const f = stubApi(page({}, { ...ETPRO_ON, applying: true }));
		render(Page);

		expect(
			await screen.findByText('Suricata is restarting with the new rules. This takes a few minutes; this page refreshes by itself.'),
		).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Save code' })).toBeDisabled();
		const statusReads = (m: typeof f) => m.mock.calls.filter(([url, init]) => url === '/api/suricata/rules/commercial' && !init).length;
		expect(statusReads(f)).toBe(1);

		const done = stubApi(page({ etpro_rules: 48211 }, ETPRO_ON));
		await vi.advanceTimersByTimeAsync(15_000);

		expect(await screen.findByText('ET Pro rules are active: 48,211 rules loaded.')).toBeInTheDocument();
		expect(screen.queryByText(/Suricata is restarting with the new rules/)).not.toBeInTheDocument();
		expect(statusReads(done)).toBe(1);

		// done applying: the polling stops
		await vi.advanceTimersByTimeAsync(45_000);
		expect(statusReads(done)).toBe(1);
	});
});
