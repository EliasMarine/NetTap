import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within, waitFor } from '@testing-library/svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import { formatTime } from '$lib/utils/time';
// OLD CODE: import Page from './+page.svelte'; (NET-273: the page is a Settings tab now)
import Page from './SuricataRulesTab.svelte';

/** NET-191 slice 3: the engine facts, and how the page feeds OwnerRulesCard (its own states are in OwnerRulesCard.test.ts). */

const LIVE = {
	available: true,
	enabled_rules: 64307,
	disabled_rules: 15954,
	last_updated: '2026-11-07T00:00:36+00:00',
	sources: ['https://sslbl.abuse.ch/blacklist/sslblacklist.rules'],
	schedule: '0 0 * * *',
	error: null,
	engine: { loaded: 64309, failed: 4, reload_time: '2026-11-07T00:01:00+00:00' },
	owner_rules: 2,
};

const TWO_RULES = [
	'alert tcp $HOME_NET any -> any 23 (msg:"Telnet out"; sid:1000001; rev:1;)',
	'alert ip 192.168.1.50 any -> any any (msg:"Camera talks out"; sid:1000002; rev:1;)',
].join('\n');

const OWNER = { content: TWO_RULES, rule_count: 2, max_rules: 2000, max_bytes: 262144 };
const OWNER_EMPTY = { ...OWNER, content: '', rule_count: 0 };
const ETPRO_OFF = { configured: false, active: false, last_update_ok: null, applying: false, activation: null };

const LIVE_URL = '/api/suricata/rules/live';
const OWNER_URL = '/api/suricata/rules/custom';

type Reply = { status: number; body: unknown };

/** GETs answer from `gets` (HTTP 500 when absent); POSTs answer from `writes`, keyed by URL. */
function stubApi(gets: Record<string, unknown>, writes: Record<string, Reply> = {}) {
	const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
		const method = init?.method ?? 'GET';
		const reply: Reply =
			method === 'GET'
				? gets[url]
					? { status: 200, body: gets[url] }
					: { status: 500, body: {} }
				: (writes[url] ?? { status: 500, body: {} });
		return { ok: reply.status >= 200 && reply.status < 300, status: reply.status, json: async () => reply.body };
	});
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

function page(live: object = {}, owner: object = OWNER, etpro: object = ETPRO_OFF) {
	return {
		[LIVE_URL]: { ...LIVE, ...live },
		[OWNER_URL]: owner,
		'/api/suricata/rules/commercial': etpro,
	};
}

/** POSTs never answer, so the page stays mid-request. */
function holdWrites(f: ReturnType<typeof stubApi>) {
	const answer = f.getMockImplementation()!;
	f.mockImplementation(async (url, init) => {
		if (init?.method) await new Promise(() => {});
		return answer(url, init);
	});
}

const posts = (f: ReturnType<typeof stubApi>, url: string) => f.mock.calls.filter(([u, init]) => u === url && init?.method === 'POST');
const gets = (f: ReturnType<typeof stubApi>, url: string) => f.mock.calls.filter(([u, init]) => u === url && !init);
const editor = () => screen.findByLabelText('Rules') as Promise<HTMLTextAreaElement>;
const card = (el: HTMLElement) => el.closest('.card') as HTMLElement;
/** A StatStrip figure or a facts row's value, by its label. */
const figure = (label: string) => screen.getByText(label).nextElementSibling;

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('Suricata rules page — downloaded and active', () => {
	it("shows the downloaded count, the engine's loaded and failed counts and your rules", async () => {
		stubApi(page());
		render(Page);
		await screen.findByText('64,307');

		expect(figure('Rules downloaded')).toHaveTextContent(/^64,307$/);
		expect(figure('Rules active')).toHaveTextContent(/^64,309$/);
		expect(figure('Your rules')).toHaveTextContent(/^2$/);
		expect(figure('Rules that failed to load')).toHaveTextContent(/^4$/);
		expect(figure('Rules last loaded')).toHaveTextContent(formatTime(LIVE.engine.reload_time));
		expect(figure('Rules file updated')).toHaveTextContent(formatTime(LIVE.last_updated));
		expect(screen.queryByText(/Suricata didn't answer/)).not.toBeInTheDocument();
	});

	it("says the active count is unknown when Suricata didn't answer", async () => {
		stubApi(page({ engine: null }));
		render(Page);

		expect(await screen.findByText("Suricata didn't answer, so how many rules it has loaded is unknown.")).toBeInTheDocument();
		expect(figure('Rules active')).toHaveTextContent(/^Unknown$/);
		expect(figure('Rules that failed to load')).toHaveTextContent(/^Unknown$/);
		expect(figure('Rules downloaded')).toHaveTextContent(/^64,307$/);
	});

	it('shows 0 of your rules as a number', async () => {
		stubApi(page({ owner_rules: 0 }, OWNER_EMPTY));
		render(Page);
		await screen.findByText('64,307');

		expect(figure('Your rules')).toHaveTextContent(/^0$/);
	});

	it("says your rules aren't connected, and turns off Save and load, when Suricata can't see the folder", async () => {
		stubApi(page({ owner_rules: null }));
		render(Page);
		await editor();

		expect(figure('Your rules')).toHaveTextContent(/^Not connected$/);
		expect(screen.getByText(/Suricata isn't connected to your rules folder yet, so saving is off/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Save and load' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Check rules' })).toBeEnabled();
	});

	it("treats an older daemon that doesn't send owner_rules the same as not connected", async () => {
		const { owner_rules: _owner, ...olderLive } = LIVE;
		stubApi({ ...page(), [LIVE_URL]: olderLive });
		render(Page);
		await editor();

		expect(figure('Your rules')).toHaveTextContent(/^Not connected$/);
		expect(screen.getByRole('button', { name: 'Save and load' })).toBeDisabled();
	});

	it("doesn't turn off Save and load just because the live status failed to load", async () => {
		const { [LIVE_URL]: _live, ...withoutLive } = page();
		stubApi(withoutLive);
		render(Page);
		await editor();

		expect(screen.queryByText(/Suricata isn't connected to your rules folder yet/)).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Save and load' })).toBeEnabled();
	});

	it('gives the editor the full width', async () => {
		stubApi(page());
		render(Page);

		expect(card(await editor())).toHaveClass('c-12');
	});
});

describe('Suricata rules page — retired controls', () => {
	it('loads neither the source toggles, the schedule nor the rule stats, and shows no picker', async () => {
		const f = stubApi(page());
		render(Page);
		await editor();

		const urls = f.mock.calls.map(([url]) => url);
		for (const retired of ['/api/suricata/rules/sources', '/api/suricata/rules/stats', '/api/suricata/rules/schedule']) {
			expect(urls).not.toContain(retired);
		}
		expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
		expect(screen.queryByRole('switch')).not.toBeInTheDocument();
		expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
		expect(screen.queryByText('Custom rules')).not.toBeInTheDocument();
	});
});

describe('Suricata rules page — feeding your own rules', () => {
	it("shows the card loading until the page's first load lands", () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);

		expect(screen.getByText('Loading your own rules')).toBeInTheDocument();
	});

	it('loads the file into the editor', async () => {
		stubApi(page());
		render(Page);

		expect((await editor()).value).toBe(TWO_RULES);
	});

	it("shows the card's error state when the file fails to load, and retries the page", async () => {
		const { [OWNER_URL]: _owner, ...withoutOwner } = page();
		stubApi(withoutOwner);
		render(Page);

		const title = await screen.findByText("Couldn't load your own rules: the request failed.");
		expect(screen.queryByLabelText('Rules')).not.toBeInTheDocument();

		stubApi(page());
		await fireEvent.click(within(card(title)).getByRole('button', { name: 'Try again' }));

		expect((await editor()).value).toBe(TWO_RULES);
	});

	it('shows the empty state when the file is empty', async () => {
		stubApi(page({ owner_rules: 0 }, OWNER_EMPTY));
		render(Page);

		expect(await screen.findByText('No rules of your own yet')).toBeInTheDocument();
	});

	it('keeps the last rules and says so when a refresh fails', async () => {
		stubApi(page());
		render(Page);
		await editor();

		const { [OWNER_URL]: _owner, ...withoutOwner } = page();
		stubApi(withoutOwner);
		expect(await refreshPage()).toBe('partial');

		expect(await screen.findByText("Couldn't refresh your own rules; showing the last figures loaded.")).toBeInTheDocument();
		expect((await editor()).value).toBe(TWO_RULES);
	});

	it('never overwrites what you are typing when the page refreshes', async () => {
		stubApi(page());
		render(Page);
		const box = await editor();

		await fireEvent.input(box, { target: { value: `${TWO_RULES}\n# draft` } });
		stubApi(page({}, { ...OWNER, content: 'alert ip any any -> any any (msg:"elsewhere"; sid:1000009;)', rule_count: 1 }));
		await refreshPage();

		expect(box.value).toBe(`${TWO_RULES}\n# draft`);
	});

	it('reads the counts again after a save', async () => {
		const saved = { saved: true, rule_count: 2, engine: { loaded: 65432, failed: 0 } };
		const f = stubApi(page(), { [OWNER_URL]: { status: 200, body: saved } });
		render(Page);
		await editor();

		await fireEvent.click(screen.getByRole('button', { name: 'Save and load' }));

		expect(await screen.findByText('Saved and loaded 2 rules of your own. Suricata has 65,432 rules loaded.')).toBeInTheDocument();
		expect(posts(f, OWNER_URL)).toHaveLength(1);
		// the result shows as soon as it arrives; the page's counts are read after it
		await waitFor(() => expect(gets(f, OWNER_URL)).toHaveLength(2));
		expect(gets(f, LIVE_URL)).toHaveLength(2);
	});
});

describe('Suricata rules page — one change at a time, with your own rules', () => {
	it('turns off Update rules now and the ET Pro buttons while your rules save', async () => {
		holdWrites(stubApi(page()));
		render(Page);
		await editor();

		await fireEvent.click(screen.getByRole('button', { name: 'Save and load' }));

		for (const name of ['Saving and loading…', 'Check rules', 'Update rules now', 'Save code']) {
			expect(screen.getByRole('button', { name })).toBeDisabled();
		}
	});

	it('turns off Check rules and Save and load while a rule update runs', async () => {
		holdWrites(stubApi(page()));
		render(Page);
		await editor();

		await fireEvent.click(screen.getByRole('button', { name: 'Update rules now' }));

		expect(screen.getByRole('button', { name: 'Check rules' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Save and load' })).toBeDisabled();
	});

	it('turns them off while Suricata restarts for ET Pro', async () => {
		stubApi(page({}, OWNER, { ...ETPRO_OFF, configured: true, applying: true }));
		render(Page);
		await screen.findByText(/Suricata is restarting with the new rules/);

		expect(screen.getByRole('button', { name: 'Check rules' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Save and load' })).toBeDisabled();
	});

	it('leaves the other changes on while your rules are only checked', async () => {
		holdWrites(stubApi(page()));
		render(Page);
		await editor();

		await fireEvent.click(screen.getByRole('button', { name: 'Check rules' }));

		expect(screen.getByRole('button', { name: 'Checking…' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Update rules now' })).toBeEnabled();
		expect(screen.getByRole('button', { name: 'Save code' })).toBeEnabled();
	});
});
