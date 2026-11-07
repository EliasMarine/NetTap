import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

/** The page shows what Suricata really runs, and controls that are not wired up are off (#58). */

const LIVE = {
	available: true,
	enabled_rules: 64307,
	disabled_rules: 15954,
	last_updated: '2026-11-02T00:00:36+00:00',
	sources: [
		'https://rules.emergingthreats.net/open/suricata-%(__version__)s/emerging.rules.tar.gz',
		'https://sslbl.abuse.ch/blacklist/sslblacklist.rules',
	],
	schedule: '0 0 * * *',
	error: null,
};

const ETPRO_OFF = { configured: false, active: false, last_update_ok: null, applying: false, activation: null };
const OWNER_EMPTY = { content: '', rule_count: 0, max_rules: 2000, max_bytes: 262144 };

function stubFetch(live: { status: number; body: unknown }) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			if (url === '/api/suricata/rules/live') {
				return { ok: live.status < 400, status: live.status, json: async () => live.body };
			}
			if (url === '/api/suricata/rules/sources') {
				return { ok: true, status: 200, json: async () => ({ sources: [], last_update: null }) };
			}
			return { ok: false, status: 500, json: async () => ({}) };
		}),
	);
}

describe('Suricata rules page — live status', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the real rule count, sources and schedule', async () => {
		stubFetch({ status: 200, body: LIVE });
		render(Page);

		expect(await screen.findByText('64,307')).toBeInTheDocument();
		expect(screen.getByText('Emerging Threats Open')).toBeInTheDocument();
		expect(screen.getByText('abuse.ch SSL Blacklist')).toBeInTheDocument();
		expect(screen.getByText('Rules refresh automatically every day at 00:00 UTC.')).toBeInTheDocument();
		expect(screen.queryByText('Active Sources')).not.toBeInTheDocument();
	});

	it('says it could not read Suricata instead of showing 0 rules', async () => {
		stubFetch({ status: 502, body: { available: false, error: 'Could not reach the Suricata container.' } });
		render(Page);

		expect(await screen.findByText(/Could not read Suricata's rules: Could not reach the Suricata container\./)).toBeInTheDocument();
		expect(screen.queryByText('Never')).not.toBeInTheDocument();
		// OLD CODE START — the three figures read "--"; the card now shows its error state instead of them
		// expect(screen.getAllByText('--').length).toBe(3);
		// OLD CODE END
		expect(screen.queryByText('Enabled rules')).not.toBeInTheDocument();
		expect(screen.queryByText('0')).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't read the rule sources: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't read the update schedule: the request failed.")).toBeInTheDocument();
	});

	it('turns off the controls that do not reach Suricata', async () => {
		stubFetch({ status: 200, body: LIVE });
		render(Page);
		await screen.findByText('64,307');

		// OLD CODE START — NET-191 slice 3: the read-only custom rules box is gone; "Your own rules" loads its rules
		// expect(screen.getByRole('button', { name: 'Save custom rules' })).toBeDisabled();
		// OLD CODE END
		expect(screen.queryByRole('button', { name: 'Save custom rules' })).not.toBeInTheDocument();
		// OLD CODE START — NET-191 slice 2: the commercial licence form is gone; the ET Pro card is wired up
		// expect(screen.getByRole('button', { name: 'Add commercial licence' })).toBeDisabled();
		// OLD CODE END
		expect(screen.queryByRole('button', { name: 'Add commercial licence' })).not.toBeInTheDocument();
		expect(screen.queryByRole('combobox', { name: /Auto-update interval/ })).not.toBeInTheDocument();
	});

	// #96: a failure showed an empty editor and "no license", as if nothing were saved
	it('says the custom rules and license status could not be loaded', async () => {
		stubFetch({ status: 200, body: LIVE });
		render(Page);
		await screen.findByText('64,307');

		// OLD CODE START — NET-191 slice 3: the owner rules card shows its own error state
		// expect(screen.getByText("Couldn't load the saved custom rules: the request failed.")).toBeInTheDocument();
		// OLD CODE END
		expect(screen.getByText("Couldn't load your own rules: the request failed.")).toBeInTheDocument();
		// OLD CODE START — NET-191 slice 2: the ET Pro card shows its own error state instead
		// expect(screen.getByText("Couldn't load the commercial licence status: the request failed.")).toBeInTheDocument();
		// OLD CODE END
		expect(screen.getByText("Couldn't read the ET Pro status: the request failed.")).toBeInTheDocument();
	});

	it('shows the saved custom rules and license without a failure note when they load', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const replies: Record<string, unknown> = {
					'/api/suricata/rules/live': LIVE,
					// OLD CODE START — NET-191 slice 3: the owner rules shape, with a sid in the owner range
					// '/api/suricata/rules/custom': { content: 'alert tcp any any -> any any (sid:9999001;)' },
					// OLD CODE END
					'/api/suricata/rules/custom': { ...OWNER_EMPTY, content: 'alert tcp any any -> any any (sid:1000001;)', rule_count: 1 },
					// OLD CODE START — NET-191 slice 2: the ET Pro status shape
					// '/api/suricata/rules/commercial': { configured: false },
					// OLD CODE END
					'/api/suricata/rules/commercial': ETPRO_OFF,
				};
				const body = replies[url];
				return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 500, json: async () => ({}) };
			}),
		);
		render(Page);
		await screen.findByText('64,307');

		// OLD CODE START — NET-191 slice 3
		// expect(screen.getByDisplayValue('alert tcp any any -> any any (sid:9999001;)')).toBeInTheDocument();
		// OLD CODE END
		expect(screen.getByDisplayValue('alert tcp any any -> any any (sid:1000001;)')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load/)).not.toBeInTheDocument();
	});
});

/** Answer each URL with its body, or HTTP 500 when it has none. */
function stubReplies(replies: Record<string, unknown>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url];
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 500, json: async () => ({}) };
		}),
	);
}

const SHOWN = {
	'/api/suricata/rules/live': LIVE,
	// OLD CODE START — NET-191 slice 3: the owner rules shape
	// '/api/suricata/rules/custom': { content: '' },
	// OLD CODE END
	'/api/suricata/rules/custom': OWNER_EMPTY,
	// OLD CODE START — NET-191 slice 2: the ET Pro status shape
	// '/api/suricata/rules/commercial': { configured: false },
	// OLD CODE END
	'/api/suricata/rules/commercial': ETPRO_OFF,
};

describe('Suricata rules page — card states', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows each data card loading until the first load lands', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);

		expect(screen.getByText("Loading Suricata's rules")).toBeInTheDocument();
		expect(screen.getByText('Loading rule sources')).toBeInTheDocument();
		expect(screen.getByText('Loading the update schedule')).toBeInTheDocument();
	});

	it('says no sources are listed when the rule updater lists none', async () => {
		stubReplies({ ...SHOWN, '/api/suricata/rules/live': { ...LIVE, sources: [], schedule: null } });
		render(Page);

		expect(await screen.findByText('No rule sources listed')).toBeInTheDocument();
		expect(screen.getByText('No automatic refresh is scheduled. Use Update rules now.')).toBeInTheDocument();
	});

	it('retries from the error state', async () => {
		stubReplies({});
		render(Page);
		await screen.findByText(/Could not read Suricata's rules/);

		stubReplies(SHOWN);
		await fireEvent.click(screen.getAllByRole('button', { name: 'Try again' })[0]);

		expect(await screen.findByText('64,307')).toBeInTheDocument();
		expect(screen.queryByText(/Could not read Suricata's rules/)).not.toBeInTheDocument();
	});
});

describe('Suricata rules page — refresh contract (PLAN §5.5)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('registers its loader and reports ok, partial and failed from what the page shows', async () => {
		stubReplies(SHOWN);
		render(Page);
		expect(get(pageRefresh).available).toBe(true);
		// the source list, stats and schedule replies feed nothing on screen (#58), so their 500s don't count
		expect(await refreshPage()).toBe('ok');

		const { '/api/suricata/rules/custom': _custom, ...withoutCustom } = SHOWN;
		stubReplies(withoutCustom);
		expect(await refreshPage()).toBe('partial');

		stubReplies({});
		expect(await refreshPage()).toBe('failed');
	});

	it('writes nothing once the page has gone', async () => {
		let answer: () => void = () => {};
		const gate = new Promise<void>((resolve) => (answer = resolve));
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				await gate;
				const body = (SHOWN as Record<string, unknown>)[url];
				return { ok: !!body, status: body ? 200 : 500, json: async () => body ?? {} };
			}),
		);
		const { unmount } = render(Page);
		const pending = refreshPage();
		unmount();
		answer();

		expect(await pending).toBe('skipped');
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null });
	});
});
