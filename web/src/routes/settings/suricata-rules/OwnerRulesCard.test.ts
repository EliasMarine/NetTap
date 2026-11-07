import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import OwnerRulesCard from './OwnerRulesCard.svelte';

/** NET-191 slice 3: the "Your own rules" editor's states, check and save. The page's wiring is in suricata-rules-owner.test.ts. */

const TWO_RULES = [
	'alert tcp $HOME_NET any -> any 23 (msg:"Telnet out"; sid:1000001; rev:1;)',
	'alert ip 192.168.1.50 any -> any any (msg:"Camera talks out"; sid:1000002; rev:1;)',
].join('\n');

const OWNER = { content: TWO_RULES, rule_count: 2, max_rules: 2000, max_bytes: 262144 };
const OWNER_EMPTY = { ...OWNER, content: '', rule_count: 0 };

const SAVE_URL = '/api/suricata/rules/custom';
const CHECK_URL = '/api/suricata/rules/custom/check';

type Reply = { status: number; body: unknown };

/** POSTs answer from `replies`, keyed by URL (HTTP 500 when absent). */
function stubPosts(replies: Record<string, Reply> = {}) {
	const f = vi.fn(async (url: string, _init?: RequestInit) => {
		const r = replies[url] ?? { status: 500, body: {} };
		return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body };
	});
	vi.stubGlobal('fetch', f);
	return f;
}

/** Requests never answer, so the card stays mid-request. */
const holdPosts = () => vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));

function props(over: object = {}) {
	return { loaded: true, owner: OWNER, failed: false, unmounted: false, busy: false, reload: vi.fn(async () => 'ok'), ...over };
}

const box = () => screen.getByLabelText('Rules') as HTMLTextAreaElement;
const button = (name: string) => screen.getByRole('button', { name });
const sent = (f: ReturnType<typeof stubPosts>, url: string) => f.mock.calls.filter(([u]) => u === url).map(([, init]) => init?.body);

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('OwnerRulesCard — loading, empty and error', () => {
	it('shows its loading state until the first load lands', () => {
		render(OwnerRulesCard, props({ loaded: false, owner: null }));

		expect(screen.getByText('Loading your own rules')).toBeInTheDocument();
		expect(screen.queryByLabelText('Rules')).not.toBeInTheDocument();
	});

	it('shows its error state, and Try again reads the page again', async () => {
		const p = props({ owner: null });
		render(OwnerRulesCard, p);

		expect(screen.getByText("Couldn't load your own rules: the request failed.")).toBeInTheDocument();
		expect(screen.queryByLabelText('Rules')).not.toBeInTheDocument();
		await fireEvent.click(button('Try again'));

		expect(p.reload).toHaveBeenCalledTimes(1);
	});

	it('shows the empty state, then the editor and its limits on Write a rule', async () => {
		render(OwnerRulesCard, props({ owner: OWNER_EMPTY }));

		expect(screen.getByText('No rules of your own yet')).toBeInTheDocument();
		expect(screen.queryByLabelText('Rules')).not.toBeInTheDocument();

		await fireEvent.click(button('Write a rule'));

		expect(box().value).toBe('');
		const help = screen.getByText(/rule per line, each with a/);
		expect(help).toHaveTextContent('1000000 to 1999999');
		expect(help).toHaveTextContent('At most 2,000 rules or 256 KB.');
		expect(help).toHaveTextContent('Saving an empty box removes all your rules.');
	});

	it('shows a file of comments only, rather than the empty state', () => {
		render(OwnerRulesCard, props({ owner: { ...OWNER_EMPTY, content: '# later\n' } }));

		expect(box().value).toBe('# later\n');
	});

	it('keeps the last rules and says so when a refresh failed', () => {
		render(OwnerRulesCard, props({ failed: true }));

		expect(screen.getByText("Couldn't refresh your own rules; showing the last figures loaded.")).toBeInTheDocument();
		expect(box().value).toBe(TWO_RULES);
	});

	it("turns off Save and load, but not Check rules, when Suricata can't see the folder", () => {
		render(OwnerRulesCard, props({ unmounted: true }));

		expect(screen.getByText(/Suricata isn't connected to your rules folder yet, so saving is off/)).toBeInTheDocument();
		expect(button('Save and load')).toBeDisabled();
		expect(button('Check rules')).toBeEnabled();
	});

	it('turns off both buttons while another change runs', () => {
		render(OwnerRulesCard, props({ busy: true }));

		expect(button('Check rules')).toBeDisabled();
		expect(button('Save and load')).toBeDisabled();
	});
});

describe('OwnerRulesCard — the text in the box', () => {
	const OTHER = { ...OWNER, content: 'alert ip any any -> any any (msg:"elsewhere"; sid:1000009;)', rule_count: 1 };

	it('never overwrites what you are typing when a new file arrives', async () => {
		const { rerender } = render(OwnerRulesCard, props());

		await fireEvent.input(box(), { target: { value: `${TWO_RULES}\n# draft` } });
		await rerender(props({ owner: OTHER }));

		expect(box().value).toBe(`${TWO_RULES}\n# draft`);
	});

	it('takes a new file while the box is unedited', async () => {
		const { rerender } = render(OwnerRulesCard, props());

		await rerender(props({ owner: OTHER }));

		await waitFor(() => expect(box().value).toBe(OTHER.content));
	});
});

describe('OwnerRulesCard — Check rules', () => {
	it("posts the box's text to the validator only and says how many rules passed", async () => {
		const f = stubPosts({ [CHECK_URL]: { status: 200, body: { ok: true, rule_count: 2 } } });
		const p = props();
		render(OwnerRulesCard, p);

		await fireEvent.click(button('Check rules'));

		const note = await screen.findByText('No problems found in 2 rules. Suricata tests them again when you save.');
		expect(note.closest('.notice')).toHaveClass('is-ok');
		expect(sent(f, CHECK_URL)).toEqual([JSON.stringify({ content: TWO_RULES })]);
		expect(sent(f, SAVE_URL)).toHaveLength(0);
		expect(p.reload).not.toHaveBeenCalled();
	});

	it('shows each reason on its line, and file-wide reasons as returned', async () => {
		const errors = [
			{ line: 1, message: 'Only alert rules can be used.' },
			{ line: 2, message: 'The sid must be from 1000000 to 1999999.' },
			{ line: null, message: 'Your rules are over 256 KB.' },
		];
		stubPosts({ [CHECK_URL]: { status: 400, body: { error: 'Three problems need fixing.', errors } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Check rules'));

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent('Three problems need fixing.');
		expect(alert).toHaveClass('notice', 'is-error');
		const list = document.getElementById('owner-rules-errors') as HTMLElement;
		expect([...list.querySelectorAll('li')].map((li) => li.textContent)).toEqual([
			'Line 1: Only alert rules can be used.',
			'Line 2: The sid must be from 1000000 to 1999999.',
			'Your rules are over 256 KB.',
		]);
		expect(box()).toHaveAttribute('aria-invalid', 'true');
		expect(box()).toHaveAttribute('aria-describedby', 'owner-rules-errors');
	});

	it('turns off both buttons while it checks', async () => {
		holdPosts();
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Check rules'));

		expect(button('Checking…')).toBeDisabled();
		expect(button('Save and load')).toBeDisabled();
	});

	it('says the request failed when it never reaches the daemon', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Check rules'));

		expect(await screen.findByText("Couldn't check the rules: the request failed.")).toBeInTheDocument();
	});
});

describe('OwnerRulesCard — Save and load', () => {
	const saved = { saved: true, rule_count: 2, engine: { loaded: 65432, failed: 0 } };

	it('says what loaded, then reads the page again', async () => {
		const f = stubPosts({ [SAVE_URL]: { status: 200, body: saved } });
		const p = props();
		render(OwnerRulesCard, p);

		await fireEvent.click(button('Save and load'));

		const note = await screen.findByText('Saved and loaded 2 rules of your own. Suricata has 65,432 rules loaded.');
		expect(note.closest('.notice')).toHaveClass('is-ok');
		expect(sent(f, SAVE_URL)).toEqual([JSON.stringify({ content: TWO_RULES })]);
		await waitFor(() => expect(p.reload).toHaveBeenCalledTimes(1));
	});

	it('removes every rule from an empty box and keeps the editor open', async () => {
		const f = stubPosts({ [SAVE_URL]: { status: 200, body: { ...saved, rule_count: 0 } } });
		const { rerender } = render(OwnerRulesCard, props());

		await fireEvent.input(box(), { target: { value: '' } });
		await fireEvent.click(button('Save and load'));
		// the page's reload brings the empty file, which on a first load would show the empty state
		await rerender(props({ owner: OWNER_EMPTY }));

		expect(await screen.findByText('Saved. Your own rules are removed. Suricata has 65,432 rules loaded.')).toBeInTheDocument();
		expect(sent(f, SAVE_URL)).toEqual([JSON.stringify({ content: '' })]);
		expect(screen.queryByText('No rules of your own yet')).not.toBeInTheDocument();
		expect(box().value).toBe('');
	});

	it("shows the validator's line reasons on a 400", async () => {
		stubPosts({ [SAVE_URL]: { status: 400, body: { error: 'One line needs fixing.', errors: [{ line: 2, message: 'Lua scripts are not allowed.' }] } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		expect(await screen.findByText('One line needs fixing.')).toBeInTheDocument();
		expect(screen.getByText('Line 2: Lua scripts are not allowed.')).toHaveClass('field-error');
	});

	it("shows Suricata's refusal with its lines on a 422, and says the old rules still run", async () => {
		stubPosts({
			[SAVE_URL]: {
				status: 422,
				body: { error: 'Suricata refused the rules: unknown rule keyword "flowbitz".', errors: [{ line: 1, message: 'unknown rule keyword "flowbitz"' }] },
			},
		});
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent('Suricata refused the rules: unknown rule keyword "flowbitz". Suricata keeps running the rules it had.');
		expect(alert).toHaveClass('is-error');
		expect(screen.getByText('Line 1: unknown rule keyword "flowbitz"')).toBeInTheDocument();
	});

	it('shows a rule update in the way in amber on a 409', async () => {
		stubPosts({ [SAVE_URL]: { status: 409, body: { error: 'A Suricata rule update is running. Try again in a few minutes.' } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent('A Suricata rule update is running. Try again in a few minutes.');
		expect(alert).toHaveClass('is-warn');
		expect(document.getElementById('owner-rules-errors')).toBeNull();
	});

	it('says the previous rules were put back on a 502', async () => {
		stubPosts({ [SAVE_URL]: { status: 502, body: { error: "Suricata didn't reload. The previous rules were put back." } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent("Suricata didn't reload. The previous rules were put back.");
		expect(alert).toHaveClass('is-error');
	});

	// The browser can lose the request after the daemon got it, so a failed request is "unknown", not a refusal
	it("says the result can't be confirmed when the request fails, and still reads the page again", async () => {
		vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
		const p = props();
		render(OwnerRulesCard, p);

		await fireEvent.click(button('Save and load'));

		const alert = await screen.findByText("NetTap couldn't confirm the result. Check Rules active before saving again.");
		expect(alert.closest('.notice')).toHaveClass('is-warn');
		await waitFor(() => expect(p.reload).toHaveBeenCalledTimes(1));
	});

	it('says it can take minutes, locks the box and turns off both buttons while it saves', async () => {
		holdPosts();
		const p = props();
		render(OwnerRulesCard, p);

		await fireEvent.click(button('Save and load'));

		expect(screen.getByText('Suricata is testing and loading your rules. This can take up to 4 minutes.')).toBeInTheDocument();
		expect(button('Saving and loading…')).toBeDisabled();
		expect(button('Check rules')).toBeDisabled();
		expect(box()).toHaveAttribute('readonly');
		expect(p.reload).not.toHaveBeenCalled();
	});
});

/** Slice 3 review round: stale results, odd replies, focus and the result arriving early. */
describe('OwnerRulesCard — editing clears a stale answer (M1)', () => {
	const errors = [{ line: 2, message: 'Lua scripts are not allowed.' }];

	it('drops the line reasons, aria-invalid and the banner as soon as the text changes', async () => {
		stubPosts({ [CHECK_URL]: { status: 400, body: { error: 'One line needs fixing.', errors } } });
		render(OwnerRulesCard, props());
		await fireEvent.click(button('Check rules'));
		await screen.findByText('Line 2: Lua scripts are not allowed.');

		await fireEvent.input(box(), { target: { value: TWO_RULES.split('\n')[0] } });

		expect(screen.queryByText('One line needs fixing.')).not.toBeInTheDocument();
		expect(document.getElementById('owner-rules-errors')).toBeNull();
		expect(box()).not.toHaveAttribute('aria-invalid');
		expect(box()).not.toHaveAttribute('aria-describedby');
	});

	it('drops a stale green answer too', async () => {
		stubPosts({ [CHECK_URL]: { status: 200, body: { ok: true, rule_count: 2 } } });
		render(OwnerRulesCard, props());
		await fireEvent.click(button('Check rules'));
		await screen.findByText(/^No problems found/);

		await fireEvent.input(box(), { target: { value: 'pass ip any any -> any any (sid:1000003;)' } });

		expect(screen.queryByText(/^No problems found/)).not.toBeInTheDocument();
	});

	it('locks the box while a check runs, so the answer is about the text on screen', async () => {
		holdPosts();
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Check rules'));

		expect(box()).toHaveAttribute('readonly');
	});
});

describe('OwnerRulesCard — odd replies (M2, M4)', () => {
	it('shows a save whose engine count is null as saved, without a loaded count', async () => {
		stubPosts({ [SAVE_URL]: { status: 200, body: { saved: true, rule_count: 2, engine: { loaded: null, failed: null } } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		const note = await screen.findByText('Saved and loaded 2 rules of your own.');
		expect(note.closest('.notice')).toHaveClass('is-ok');
	});

	it("doesn't call a save with no rule count a removal", async () => {
		stubPosts({ [SAVE_URL]: { status: 200, body: { saved: true, engine: { loaded: 65432, failed: 0 } } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		expect(await screen.findByText('Saved and loaded. Suricata has 65,432 rules loaded.')).toBeInTheDocument();
	});

	it('shows a check with no rule count as passed, without a count', async () => {
		stubPosts({ [CHECK_URL]: { status: 200, body: { ok: true } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Check rules'));

		expect(await screen.findByText('No problems found. Suricata tests them again when you save.')).toBeInTheDocument();
	});

	it("shows a proxy timeout as unconfirmed in amber, not as Suricata's refusal", async () => {
		stubPosts({
			[SAVE_URL]: { status: 502, body: { error: 'Daemon unreachable: The operation was aborted due to timeout', daemonAvailable: false } },
		});
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent("NetTap couldn't confirm the result. Check Rules active before saving again.");
		expect(alert).toHaveClass('is-warn');
		expect(screen.queryByText(/Daemon unreachable/)).not.toBeInTheDocument();
	});

	it("shows the daemon's own 502 (its test couldn't run) as a red failure", async () => {
		stubPosts({ [SAVE_URL]: { status: 502, body: { error: "Suricata's test couldn't run (exit 137). Nothing was changed." } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent("Suricata's test couldn't run (exit 137). Nothing was changed.");
		expect(alert).toHaveClass('is-error');
	});

	it("shows a refused check's summary as the daemon wrote it, with nothing added in front", async () => {
		stubPosts({
			[CHECK_URL]: { status: 400, body: { error: 'Your rules have problems: line 1 ends in a backslash (and 1 more)', errors: [] } },
		});
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Check rules'));

		expect((await screen.findByRole('alert')).textContent).toBe('Your rules have problems: line 1 ends in a backslash (and 1 more)');
	});

	it('treats a 200 login page as not saved', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => ({ ok: true, status: 200, json: async () => Promise.reject(new SyntaxError('Unexpected token <')) })),
		);
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent('you may need to sign in again');
		expect(screen.queryByText(/^Saved/)).not.toBeInTheDocument();
	});
});

describe('OwnerRulesCard — too big to send', () => {
	it('refuses rules over the byte limit without sending them, counting bytes rather than characters', async () => {
		const f = stubPosts();
		render(OwnerRulesCard, props({ owner: { ...OWNER, max_bytes: 2048 } }));
		// 1,025 characters, 2,048 bytes: at the limit, so it is sent
		await fireEvent.input(box(), { target: { value: '# ' + 'é'.repeat(1023) } });
		await fireEvent.click(button('Check rules'));
		await waitFor(() => expect(sent(f, CHECK_URL)).toHaveLength(1));

		// 1,026 characters, 2,050 bytes: over it
		await fireEvent.input(box(), { target: { value: '# ' + 'é'.repeat(1024) } });
		await fireEvent.click(button('Check rules'));

		const alert = await screen.findByText("Your rules are over 2 KB, so they weren't sent. Remove some rules and try again.");
		expect(alert.closest('.notice')).toHaveClass('is-error');
		expect(sent(f, CHECK_URL)).toHaveLength(1);
	});

	it('says the limit in KB as the daemon does', async () => {
		const f = stubPosts();
		render(OwnerRulesCard, props());
		await fireEvent.input(box(), { target: { value: 'a'.repeat(262_145) } });

		await fireEvent.click(button('Save and load'));

		expect(await screen.findByText("Your rules are over 256 KB, so they weren't sent. Remove some rules and try again.")).toBeInTheDocument();
		expect(sent(f, SAVE_URL)).toHaveLength(0);
	});
});

describe('OwnerRulesCard — focus (M3)', () => {
	it('moves focus into the box after Write a rule', async () => {
		render(OwnerRulesCard, props({ owner: OWNER_EMPTY }));

		await fireEvent.click(button('Write a rule'));

		await waitFor(() => expect(document.activeElement).toBe(box()));
	});

	it('moves focus to the box after a refused check', async () => {
		stubPosts({ [CHECK_URL]: { status: 400, body: { error: 'One line needs fixing.', errors: [{ line: 1, message: 'Bad.' }] } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Check rules'));

		await screen.findByText('Line 1: Bad.');
		await waitFor(() => expect(document.activeElement).toBe(box()));
	});

	it('moves focus to the box after a failed save', async () => {
		stubPosts({ [SAVE_URL]: { status: 409, body: { error: 'A Suricata rule update is running. Try again in a few minutes.' } } });
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Save and load'));

		await waitFor(() => expect(document.activeElement).toBe(box()));
	});

	it('puts focus back on the button after a successful save', async () => {
		stubPosts({ [SAVE_URL]: { status: 200, body: { saved: true, rule_count: 2, engine: { loaded: 65432, failed: 0 } } } });
		render(OwnerRulesCard, props());
		const save = button('Save and load');

		await fireEvent.click(save);

		await screen.findByText(/^Saved and loaded/);
		await waitFor(() => expect(save).toBeEnabled());
		await waitFor(() => expect(document.activeElement).toBe(save));
	});

	it('leaves focus alone when the owner has moved it elsewhere meanwhile', async () => {
		let answer: () => void = () => {};
		const gate = new Promise<void>((resolve) => (answer = resolve));
		const refusal = { error: 'One line needs fixing.', errors: [] };
		vi.stubGlobal('fetch', vi.fn(async () => (await gate, { ok: false, status: 400, json: async () => refusal })));
		const elsewhere = document.body.appendChild(document.createElement('input'));
		render(OwnerRulesCard, props());

		await fireEvent.click(button('Check rules'));
		elsewhere.focus();
		answer();

		await screen.findByText('One line needs fixing.');
		await tick();
		expect(document.activeElement).toBe(elsewhere);
		elsewhere.remove();
	});
});

describe('OwnerRulesCard — the answer arrives before the page has refreshed', () => {
	it('shows the result at once and keeps the buttons off until the page has read the counts again', async () => {
		stubPosts({ [SAVE_URL]: { status: 200, body: { saved: true, rule_count: 2, engine: { loaded: 65432, failed: 0 } } } });
		let finish: () => void = () => {};
		const reload = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
		render(OwnerRulesCard, props({ reload }));

		await fireEvent.click(button('Save and load'));

		expect(await screen.findByText('Saved and loaded 2 rules of your own. Suricata has 65,432 rules loaded.')).toBeInTheDocument();
		expect(screen.queryByText(/Suricata is testing and loading your rules/)).not.toBeInTheDocument();
		expect(button('Saving and loading…')).toBeDisabled();
		expect(button('Check rules')).toBeDisabled();

		finish();

		await waitFor(() => expect(button('Save and load')).toBeEnabled());
		expect(button('Check rules')).toBeEnabled();
	});

	it('says a refresh failed in the empty state too', () => {
		render(OwnerRulesCard, props({ owner: OWNER_EMPTY, failed: true }));

		expect(screen.getByText('No rules of your own yet')).toBeInTheDocument();
		expect(screen.getByText("Couldn't refresh your own rules; showing the last figures loaded.")).toBeInTheDocument();
	});
});
