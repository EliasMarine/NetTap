import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { refreshPage } from '$lib/stores/pageRefresh';
import type { SuricataRuleFigures } from '$lib/api/drilldown';
import { LAN_POLICY } from '../../../../../e2e/visual/fixtures/drilldown';
import { RULE_NAME, SURICATA_RULE, SURICATA_RULE_EMPTY } from '../../../../../e2e/visual/fixtures/suricata-rule';
import { expectNoNestedInteractive } from '../../../../tests/nested-interactive';
import { windowWords } from '$lib/utils/drilldown';

// The rule page: every figure links to the Alerts list holding exactly it (signature= this name,
// on the page's list, over the response's own window), and the explanation links only out to https

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/alerts/rule/x'), params: { name: 'x' } });
	return { page: pageStore.value };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Page } = await import('./+page.svelte');

const REGISTRY = { devices: [{ mac: 'aa', display_name: 'Living room TV', ips: ['192.168.1.22'], last_seen: '2026-11-05T00:00:00Z' }], total: 1 };
const WIN = { from: SURICATA_RULE.from, to: SURICATA_RULE.to, range: '24h' };

let calls: URL[] = [];
let figures: () => SuricataRuleFigures | null;
function stubDaemon(f: SuricataRuleFigures | null | (() => SuricataRuleFigures | null) | Promise<never>, reason = 'Something went wrong working this out; the daemon log has the details.') {
	calls = [];
	figures = typeof f === 'function' ? f : () => f as SuricataRuleFigures | null;
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			if (url.pathname === '/api/network/lan') return { ok: true, status: 200, json: async () => LAN_POLICY };
			if (url.pathname === '/api/devices/registry') return { ok: true, status: 200, json: async () => REGISTRY };
			if (f instanceof Promise) return f;
			const body = url.pathname.startsWith('/api/alerts/rule/') ? figures() : null;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 502, json: async () => ({ error: reason }) };
		}),
	);
}

const goTo = (name: string, query = '') => pageStore.value.set({ url: new URL(`http://localhost/alerts/rule/${encodeURIComponent(name)}${query}`), params: { name } });
const figuresCall = () => calls.filter((u) => u.pathname.startsWith('/api/alerts/rule/')).at(-1)!;
const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const card = (title: string) => screen.getByRole('heading', { name: title }).closest('.card') as HTMLElement;
const query = (href: string | null) => Object.fromEntries(new URL(href!, 'http://x').searchParams);
const loaded = (n = '180') => vi.waitFor(() => expect(kpi('Alerts')).toHaveTextContent(n));

describe('Suricata rule page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.mocked(goto).mockClear();
		goTo('x');
	});

	it('shows loading, not zeros, before the first answer', () => {
		goTo(RULE_NAME);
		stubDaemon(new Promise(() => {}) as Promise<never>);
		render(Page);
		expect(kpi('Alerts')).toHaveTextContent('—');
		expect(screen.getAllByRole('status').some((s) => s.getAttribute('aria-busy') === 'true')).toBe(true);
	});

	it('asks for the exact name encoded once and shows every card', async () => {
		goTo(RULE_NAME, '?range=7d');
		stubDaemon(SURICATA_RULE);
		const { container } = render(Page);
		await loaded();
		const sent = figuresCall();
		expect(sent.pathname).toBe(`/api/alerts/rule/${encodeURIComponent(RULE_NAME)}`);
		expect(sent.searchParams.get('activity')).toBeNull();
		expect((Date.parse(sent.searchParams.get('to')!) - Date.parse(sent.searchParams.get('from')!)) / 3_600_000).toBe(168);
		expect(screen.getByRole('heading', { level: 1, name: RULE_NAME })).toBeInTheDocument();
		expect(screen.getByText('Suricata rule')).toHaveClass('eyebrow');
		expect(screen.getByRole('button', { name: 'Counted · 180' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('button', { name: 'Activity · 12' })).toHaveAttribute('aria-pressed', 'false');
		expect(kpi('Your devices involved')).toHaveTextContent('3');
		// the remote list stopped at its cap: "at least" what it read
		expect(kpi('Remote addresses')).toHaveTextContent('5,000+');
		for (const title of ['Alerts over time', 'What this rule means', 'Rule details', 'Your devices', 'Remote addresses', 'Locality unknown']) expect(card(title)).toBeInTheDocument();
		expect(container.textContent).not.toMatch(/\bTop \d|Highest counts/);
		expectNoNestedInteractive(container);
	});

	it("links the total to the list with this rule over the response's own window", async () => {
		goTo(RULE_NAME);
		stubDaemon(SURICATA_RULE);
		render(Page);
		await loaded();
		expect(new URL(kpi('Alerts').getAttribute('href')!, 'http://x').pathname).toBe('/alerts');
		expect(query(kpi('Alerts').getAttribute('href'))).toEqual({ signature: RULE_NAME, ...WIN, count: '180' });
		const show = within(card('What this rule means')).getByRole('link', { name: 'Show these 180 alerts in the list' });
		expect(query(show.getAttribute('href'))).toEqual({ signature: RULE_NAME, ...WIN, count: '180' });
	});

	it('explains the rule and links out to each source in a new tab', async () => {
		goTo(RULE_NAME);
		stubDaemon(SURICATA_RULE);
		render(Page);
		await loaded();
		const means = card('What this rule means');
		for (const text of Object.values(SURICATA_RULE.explanation).slice(1)) expect(within(means).getByText(text)).toBeInTheDocument();
		expect(within(means).getByText('High')).toBeInTheDocument();
		const docs = within(means).getByRole('link', { name: 'How Suricata rules work' });
		expect(docs).toHaveAttribute('href', 'https://docs.suricata.io/en/latest/rules/intro.html');
		expect(docs).toHaveAttribute('target', '_blank');
		expect(docs).toHaveAttribute('rel', 'noopener noreferrer');
	});

	it('opens an exact window from the URL as Custom, and the range pills replace it', async () => {
		const [from, to] = ['2026-11-01T08:00:00.000Z', '2026-11-01T20:00:00.000Z'];
		goTo(RULE_NAME, `?from=${from}&to=${to}&range=6h`);
		stubDaemon(SURICATA_RULE);
		render(Page);
		await loaded();
		expect([figuresCall().searchParams.get('from'), figuresCall().searchParams.get('to')]).toEqual([from, to]);
		// OLD CODE: expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true'); (NET-348: the pill is named by its window)
		expect(screen.getByRole('button', { name: windowWords(from, to) })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText(/^What this rule means, when it fired and which addresses it involved · window /)).toBeInTheDocument();
		// the links carry the URL's range for their words, beside the response's bounds
		expect(query(kpi('Alerts').getAttribute('href'))).toEqual({ signature: RULE_NAME, ...WIN, range: '6h', count: '180' });
		await fireEvent.click(screen.getByRole('button', { name: '30d' }));
		expect(goto).toHaveBeenCalledWith(`/alerts/rule/${encodeURIComponent(RULE_NAME)}?range=30d`, { replaceState: true, keepFocus: true, noScroll: true });
	});

	it("links each SID's category to its page, except from the activity list", async () => {
		goTo(RULE_NAME);
		stubDaemon(SURICATA_RULE);
		render(Page);
		await loaded();
		const category = within(card('Rule details')).getByRole('link', { name: 'Attempted Administrator Privilege Gain' });
		const href = new URL(category.getAttribute('href')!, 'http://x');
		expect(href.pathname).toBe('/alerts/suricata/Attempted%20Administrator%20Privilege%20Gain');
		expect(Object.fromEntries(href.searchParams)).toEqual(WIN);
		goTo(RULE_NAME, '?activity=true');
		stubDaemon({ ...SURICATA_RULE, activity: true, total: 12, severity: { high: 0, medium: 0, low: 12, info: 0 }, timeline: [{ t: SURICATA_RULE.from, n: 12 }] });
		await refreshPage();
		await loaded('12');
		expect(within(card('Rule details')).getByText('Attempted Administrator Privilege Gain').closest('a')).toBeNull();
	});

	it("keeps each SID's own facts", async () => {
		goTo(RULE_NAME);
		stubDaemon(SURICATA_RULE);
		render(Page);
		await loaded();
		const details = card('Rule details');
		const [one, two] = within(details).getAllByRole('heading', { level: 3 }).map((h) => h.closest('section') as HTMLElement);
		expect(one).toHaveTextContent('SID 2034125 · 120 alerts');
		expect(within(one).getByText('CVE-2021-41773')).toBeInTheDocument();
		expect(within(one).getByText("On CISA's known exploited list")).toBeInTheDocument();
		expect(within(one).getByText('T1190 Exploit Public-Facing Application')).toBeInTheDocument();
		expect(within(one).getByRole('link', { name: 'CVE-2021-41773 in the National Vulnerability Database' })).toHaveAttribute('target', '_blank');
		expect(two).toHaveTextContent('SID 2034126 · 60 alerts');
		expect(within(two).getByText('Not recorded')).toBeInTheDocument();
		expect(within(two).queryByText(/CVE-|known exploited/)).toBeNull();
		expect(within(details).getByText('2 rules share this name; each keeps its own details.')).toBeInTheDocument();
		expect(within(details).queryByText(/Not every rule is listed/)).toBeNull();
	});

	it('names devices, gives each its role and links its count to the list with that address', async () => {
		goTo(RULE_NAME);
		stubDaemon(SURICATA_RULE);
		const { container } = render(Page);
		await loaded();
		const devices = card('Your devices');
		const tv = within(devices).getByRole('link', { name: 'Living room TV' });
		expect(tv.getAttribute('href')).toContain('192.168.1.22');
		const rowOf = (text: string) => within(devices).getByText(text).closest('tr') as HTMLElement;
		expect(rowOf('Living room TV')).toHaveTextContent('Both');
		expect(within(devices).getAllByText('Received it')).toHaveLength(1);
		expect(within(devices).getAllByText('Sent it')).toHaveLength(1);
		const count = within(rowOf('Living room TV')).getByRole('link', { name: '40' });
		expect(query(count.getAttribute('href'))).toEqual({ signature: RULE_NAME, ip: '192.168.1.22', ...WIN, count: '40' });
		expect(within(devices).getByText('3 addresses')).toBeInTheDocument();
		// the remote list stopped at its cap, and says how its rows were picked
		expect(within(card('Remote addresses')).getByRole('status')).toHaveTextContent('discovery stopped at its limit');
		expect(within(card('Locality unknown')).getByText(/covers IPv4 only/)).toBeInTheDocument();
		expect(within(card('Locality unknown')).getByText('2001:db8::5')).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('switches to the activity list, keeping the window, and its links keep it too', async () => {
		goTo(RULE_NAME, '?range=7d');
		stubDaemon(SURICATA_RULE);
		render(Page);
		await loaded();
		await fireEvent.click(screen.getByRole('button', { name: 'Activity · 12' }));
		expect(goto).toHaveBeenCalledWith(`/alerts/rule/${encodeURIComponent(RULE_NAME)}?range=7d&activity=true`, { replaceState: true, keepFocus: true, noScroll: true });
		goTo(RULE_NAME, '?range=7d&activity=true');
		stubDaemon({ ...SURICATA_RULE, activity: true, total: 12, severity: { high: 0, medium: 0, low: 12, info: 0 }, timeline: [{ t: SURICATA_RULE.from, n: 12 }], rules: [{ ...SURICATA_RULE.rules[0], alerts: 12 }] });
		await refreshPage();
		await loaded('12');
		expect(figuresCall().searchParams.get('activity')).toBe('true');
		expect(screen.getByText(/ET rates these rules Informational or Unknown/)).toBeInTheDocument();
		expect(query(kpi('Alerts').getAttribute('href'))).toEqual({ signature: RULE_NAME, activity: 'true', ...WIN, range: '7d', count: '12' });
	});

	it('offers the other list when this one is empty', async () => {
		goTo(RULE_NAME);
		stubDaemon({ ...SURICATA_RULE_EMPTY, activity_total: 7 });
		render(Page);
		await loaded('0');
		const hero = card('Alerts over time');
		expect(within(hero).getByText('No counted alerts for this rule in the last 24 hours')).toBeInTheDocument();
		expect(within(hero).getByText('The activity list has 7 alerts from it.')).toBeInTheDocument();
		await fireEvent.click(within(hero).getByRole('button', { name: 'Show the activity alerts' }));
		expect(String(vi.mocked(goto).mock.calls[0][0])).toBe(`/alerts/rule/${encodeURIComponent(RULE_NAME)}?activity=true`);
		expect(within(card('Your devices')).getByText('None of your devices in the last 24 hours')).toBeInTheDocument();
	});

	it("shows the daemon's reason on failure, and keeps the last good figures when a refresh fails", async () => {
		goTo(RULE_NAME);
		stubDaemon(null, "That isn't a rule name.");
		render(Page);
		await vi.waitFor(() => expect(within(card('What this rule means')).getByText("That isn't a rule name.")).toBeInTheDocument());
		let reply: SuricataRuleFigures | null = SURICATA_RULE;
		stubDaemon(() => reply);
		await refreshPage();
		await loaded();
		reply = null;
		await refreshPage();
		await vi.waitFor(() => expect(screen.getByText(/Something went wrong working this out/)).toBeInTheDocument());
		expect(kpi('Alerts')).toHaveTextContent('180');
	});

	it('links your own rule to its settings, and warns when not every SID is listed', async () => {
		goTo('NETTAP my own rule');
		stubDaemon({ ...SURICATA_RULE, name: 'NETTAP my own rule', rules_complete: false, no_sid: 3, explanation: { family: 'own', what: 'w', risk: 'r', todo: 't' } });
		render(Page);
		await loaded();
		expect(within(card('What this rule means')).getByRole('link', { name: 'Open your rules in Settings' })).toHaveAttribute('href', '/settings?tab=suricata-rules');
		expect(within(card('Rule details')).getByText(/Not every rule is listed/)).toBeInTheDocument();
		expect(within(card('Rule details')).getByText("3 alerts had no SID, so they aren't under any rule above.")).toBeInTheDocument();
	});

	it('a pick opens the list for this rule over the picked slots, with their figure', async () => {
		goTo(RULE_NAME);
		const pickable: SuricataRuleFigures = {
			...SURICATA_RULE,
			from: '2026-11-03T09:02:00.000Z',
			to: '2026-11-03T10:30:00.000Z',
			interval: '1h',
			total: 12,
			timeline: [
				{ t: '2026-11-03T09:00:00.000Z', n: 5 },
				{ t: '2026-11-03T10:00:00.000Z', n: 7 },
			],
		};
		stubDaemon(pickable);
		render(Page);
		await loaded('12');
		const chart = screen.getByRole('group', { name: /^Busiest at / });
		await fireEvent.keyDown(chart, { key: 'Home' });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(query(vi.mocked(goto).mock.calls[0][0] as string)).toEqual({ signature: RULE_NAME, from: pickable.from, to: '2026-11-03T09:59:59.999Z', range: '24h', count: '5' });
	});
});
