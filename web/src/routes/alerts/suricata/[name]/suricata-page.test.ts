import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { refreshPage } from '$lib/stores/pageRefresh';
import type { SuricataCategoryFigures } from '$lib/api/drilldown';
import { LAN_POLICY } from '../../../../../e2e/visual/fixtures/drilldown';
import { SURICATA_CATEGORY, SURICATA_CATEGORY_EMPTY } from '../../../../../e2e/visual/fixtures/suricata-category';
import { expectNoNestedInteractive } from '../../../../tests/nested-interactive';

// NET-160 slice 2b-2: every figure on the page links to the Alerts list that holds exactly it,
// over the response's own window, and says when a list is not the whole set

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/alerts/suricata/Misc%20activity'), params: { name: 'Misc activity' } });
	return { page: pageStore.value };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Page } = await import('./+page.svelte');

const NAME = 'Misc activity';
const FROM = '2026-11-01T08:00:00.000Z';
const TO = '2026-11-01T20:00:00.000Z';

let calls: URL[] = [];
/** The daemon: the LAN policy, and the figures (or an error with its own reason and status). */
function stubDaemon(figures: SuricataCategoryFigures | Promise<never> | undefined, error = { status: 502, reason: 'Something went wrong working this out; the daemon log has the details.' }) {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			if (url.pathname === '/api/network/lan') return { ok: true, status: 200, json: async () => LAN_POLICY };
			if (figures instanceof Promise) return figures;
			if (url.pathname.startsWith('/api/alerts/suricata/') && figures) return { ok: true, status: 200, json: async () => figures };
			return { ok: false, status: error.status, json: async () => ({ error: error.reason }) };
		}),
	);
}

const goTo = (name: string, query = '') =>
	pageStore.value.set({ url: new URL(`http://localhost/alerts/suricata/${encodeURIComponent(name)}${query}`), params: { name } });
const figuresCall = () => calls.find((u) => u.pathname.startsWith('/api/alerts/suricata/'))!;
const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const card = (title: string) => screen.getByRole('heading', { name: title }).closest('.card') as HTMLElement;
const query = (href: string | null) => Object.fromEntries(new URL(href!, 'http://x').searchParams);
/** The response's own window, as every link carries it */
const WIN = { from: SURICATA_CATEGORY.from, to: SURICATA_CATEGORY.to, range: '24h' };
const loaded = () => vi.waitFor(() => expect(kpi('Alerts')).toHaveTextContent('1,240'));

describe('Suricata category page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.mocked(goto).mockClear();
		goTo(NAME);
	});

	it('shows loading, not zeros, before the first answer', () => {
		stubDaemon(new Promise(() => {}) as Promise<never>);
		render(Page);
		expect(kpi('Alerts')).toHaveTextContent('—');
		expect(screen.getAllByRole('status').some((s) => s.getAttribute('aria-busy') === 'true')).toBe(true);
	});

	it('asks for the name over the URL window and shows every card', async () => {
		goTo(NAME, '?range=7d');
		stubDaemon(SURICATA_CATEGORY);
		const { container } = render(Page);
		await loaded();
		const sent = figuresCall();
		expect(sent.pathname).toBe('/api/alerts/suricata/Misc%20activity');
		expect((Date.parse(sent.searchParams.get('to')!) - Date.parse(sent.searchParams.get('from')!)) / 3_600_000).toBe(168);
		expect(screen.getByRole('heading', { level: 1, name: NAME })).toBeInTheDocument();
		expect(screen.getByText('Suricata category')).toHaveClass('eyebrow');
		expect(screen.getByText(/MITRE ATT&CK tactic beside\s+it, so category totals overlap · last 7 days/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText('Alerts per 6 hours · last 7 days')).toBeInTheDocument();
		expect(screen.getByRole('img', { name: /^Busiest at / })).toBeInTheDocument();
		for (const title of ['By severity', 'Also tagged', 'Rules', 'Sources', 'Targets']) expect(card(title)).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('opens an exact window from the URL as Custom, and the range pills replace it', async () => {
		goTo(NAME, `?from=${FROM}&to=${TO}&range=6h`);
		stubDaemon(SURICATA_CATEGORY);
		render(Page);
		await loaded();
		expect([figuresCall().searchParams.get('from'), figuresCall().searchParams.get('to')]).toEqual([FROM, TO]);
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText(/Alerts per hour · window /)).toBeInTheDocument();
		// the links carry the URL's range for their words, beside the response's bounds
		expect(query(kpi('Alerts').getAttribute('href'))).toEqual({ suricata_category: NAME, from: WIN.from, to: WIN.to, range: '6h' });
		await fireEvent.click(screen.getByRole('button', { name: '30d' }));
		expect(goto).toHaveBeenCalledWith('/alerts/suricata/Misc%20activity?range=30d', { replaceState: true, keepFocus: true, noScroll: true });
	});

	it("links the total and each severity to the list with this category over the response's own window", async () => {
		stubDaemon(SURICATA_CATEGORY);
		render(Page);
		await loaded();
		// the request's window is now; the links keep the bounds the figures answered for
		expect(figuresCall().searchParams.get('from')).not.toBe(WIN.from);
		expect(new URL(kpi('Alerts').getAttribute('href')!, 'http://x').pathname).toBe('/alerts');
		expect(query(kpi('Alerts').getAttribute('href'))).toEqual({ suricata_category: NAME, ...WIN });
		for (const [level, n] of [['high', '40'], ['medium', '300'], ['low', '880'], ['info', '20']]) {
			const tile = screen.getByRole('link', { name: `Show the ${level} alerts in this category (${n})` });
			expect(query(tile.getAttribute('href'))).toEqual({ severity: level, suricata_category: NAME, ...WIN });
		}
	});

	it('links named rules with the category kept, and leaves a missing or empty rule name plain', async () => {
		stubDaemon(SURICATA_CATEGORY);
		const { container } = render(Page);
		await loaded();
		const rules = card('Rules');
		const rule = within(rules).getByRole('link', { name: 'ET INFO Observed DNS Query to .cloud TLD' });
		expect(query(rule.getAttribute('href'))).toEqual({ signature: 'ET INFO Observed DNS Query to .cloud TLD', suricata_category: NAME, ...WIN });
		// null and "" are two rows that read the same, neither a link
		const none = within(rules).getAllByText('No rule name');
		expect(none).toHaveLength(2);
		for (const n of none) expect(n.closest('a')).toBeNull();
		// a rule literally named "Unknown" is an ordinary rule
		expect(query(within(rules).getByRole('link', { name: 'Unknown' }).getAttribute('href'))).toEqual({ signature: 'Unknown', suricata_category: NAME, ...WIN });
		expect(within(rules).getByText('5 rules')).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('links each address to its page and its count to the list from or to it', async () => {
		stubDaemon(SURICATA_CATEGORY);
		const { container } = render(Page);
		await loaded();
		const sources = card('Sources');
		await vi.waitFor(() => expect(within(sources).getByRole('link', { name: '192.168.1.20' })).toHaveAttribute('href', '/devices/192.168.1.20'));
		expect(within(sources).getByRole('link', { name: '2001:db8::5' })).toHaveAttribute('href', '/address/2001%3Adb8%3A%3A5');
		expect(query(within(sources).getByRole('link', { name: '800' }).getAttribute('href'))).toEqual({ src: '192.168.1.20', suricata_category: NAME, ...WIN });
		expect(within(sources).getByText('3 addresses')).toBeInTheDocument();
		expect(within(sources).getByText("20 alerts had no source address, so they aren't listed.")).toBeInTheDocument();
		const targets = card('Targets');
		expect(query(within(targets).getByRole('link', { name: '600' }).getAttribute('href'))).toEqual({ dst: '198.51.100.10', suricata_category: NAME, ...WIN });
		expect(within(targets).queryByText(/had no destination address/)).not.toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('says a list the snapshot could not read in full holds the highest counts among those read', async () => {
		stubDaemon(SURICATA_CATEGORY);
		render(Page);
		await loaded();
		expect(within(card('Targets')).getByRole('status')).toHaveTextContent(
			'Highest counts among the 5,000 addresses read; the full set was too large to read.',
		);
		expect(within(card('Targets')).queryByText(/^Top /)).not.toBeInTheDocument();
	});

	it('says Top N of M when a complete list is cut', async () => {
		const rows = SURICATA_CATEGORY.sources.rows;
		stubDaemon({ ...SURICATA_CATEGORY, sources: { ...SURICATA_CATEGORY.sources, rows: rows.slice(0, 2), distinct: 312 } });
		render(Page);
		await loaded();
		expect(within(card('Sources')).getByText('Top 2 of 312 addresses')).toBeInTheDocument();
	});

	it('links an also-tagged category to its own page over the same window, with its count plain', async () => {
		stubDaemon(SURICATA_CATEGORY);
		const { container } = render(Page);
		await loaded();
		const tagged = card('Also tagged');
		const link = within(tagged).getByRole('link', { name: 'Command_And_Control' });
		const href = new URL(link.getAttribute('href')!, 'http://x');
		expect(href.pathname).toBe('/alerts/suricata/Command_And_Control');
		expect(Object.fromEntries(href.searchParams)).toEqual(WIN);
		const count = within(tagged).getByText('30 of these alerts');
		expect(count.closest('a')).toBeNull();
		expect(within(tagged).getByText(/counts every alert carrying it/)).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('asks for a name with a slash, an ampersand and a percent sign encoded once', async () => {
		const odd = 'A/B & C 50%';
		goTo(odd);
		stubDaemon({ ...SURICATA_CATEGORY, name: odd });
		render(Page);
		await loaded();
		expect(figuresCall().pathname).toBe('/api/alerts/suricata/A%2FB%20%26%20C%2050%25');
		expect(screen.getByRole('heading', { level: 1, name: odd })).toBeInTheDocument();
		expect(query(kpi('Alerts').getAttribute('href')).suricata_category).toBe(odd);
	});

	it('shows the empty state with the window in words when no alert carries the category', async () => {
		stubDaemon(SURICATA_CATEGORY_EMPTY);
		render(Page);
		await vi.waitFor(() => expect(kpi('Alerts')).toHaveTextContent('0'));
		expect(screen.getAllByText('No alerts in “Misc activity” over the last 24 hours').length).toBeGreaterThan(0);
		expect(screen.getByText('No source addresses in the last 24 hours')).toBeInTheDocument();
	});

	it.each([
		[400, "That isn't a Suricata category name."],
		[400, 'Invalid time range: from must be before to'],
		[503, 'Two other look-ups are being worked out right now; try again in a minute.'],
		[502, 'Something went wrong working this out; the daemon log has the details.'],
	])("shows the daemon's own reason on HTTP %s, never zeros", async (status, reason) => {
		stubDaemon(undefined, { status, reason });
		render(Page);
		await screen.findByText("Couldn't load alerts over time: the request failed.");
		expect(screen.getAllByText(reason).length).toBeGreaterThan(0);
		expect(kpi('Alerts')).toHaveTextContent('—');
		expect(screen.queryByRole('link', { name: /Show the high alerts/ })).not.toBeInTheDocument();
	});

	it('reports ok and failed to the top bar, keeping the last figures', async () => {
		stubDaemon(SURICATA_CATEGORY);
		render(Page);
		await loaded();
		expect(await refreshPage()).toBe('ok');
		stubDaemon(undefined);
		expect(await refreshPage()).toBe('failed');
		expect(screen.getByText(/Couldn't refresh this category; showing the last figures loaded/)).toBeInTheDocument();
		expect(kpi('Alerts')).toHaveTextContent('1,240');
	});
});
