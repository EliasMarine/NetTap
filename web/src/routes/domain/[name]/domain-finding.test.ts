import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import type { DomainSummary } from '$lib/api/drilldown';
import { DOMAIN, LAN_POLICY } from '../../../../e2e/visual/fixtures/drilldown';
import { DOMAIN_FINDING } from '../../../../e2e/visual/fixtures/threats';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';
import { windowWords } from '$lib/utils/drilldown';

// A Threats DNS row opens the domain page with ?finding=<the raw name the check read>: the page
// shows the check's own evidence, counts every device as the check does, and never mixes the
// two modes' figures

const NAME = DOMAIN_FINDING.name;
const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/domain/x'), params: { name: 'x' } });
	return { page: pageStore.value };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const goTo = (query: string) => pageStore.value.set({ url: new URL(`http://localhost/domain/${NAME}${query}`), params: { name: NAME } });
const { default: Page } = await import('./+page.svelte');

const PLAIN: DomainSummary = { ...DOMAIN, name: NAME };
let calls: URL[] = [];
/** Answers each domain request from `answer`, which sees the request URL (return a promise to hold it). */
function stubDaemon(answer: (url: URL) => DomainSummary | Promise<DomainSummary>) {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			if (url.pathname === '/api/network/lan') return { ok: true, status: 200, json: async () => LAN_POLICY };
			if (url.pathname.startsWith('/api/domains/')) {
				const body = await answer(url);
				return { ok: true, status: 200, json: async () => body };
			}
			return { ok: false, status: 502, json: async () => ({ error: 'no' }) };
		}),
	);
}
const byMode = (url: URL) => (url.searchParams.has('finding') ? DOMAIN_FINDING : PLAIN);
const domainCalls = () => calls.filter((u) => u.pathname.startsWith('/api/domains/'));
const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const WHY = "Why NetTap's DNS check lists this name";

describe('Domain page in finding mode', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		goTo('');
	});

	it("explains the check's measurement and counts excluded devices", async () => {
		goTo(`?range=24h&finding=${encodeURIComponent(NAME)}`);
		stubDaemon(byMode);
		const { container } = render(Page);
		await vi.waitFor(() => expect(screen.getByRole('heading', { name: WHY })).toBeInTheDocument());
		expect(domainCalls()[0].searchParams.get('finding')).toBe(NAME);
		const why = screen.getByRole('heading', { name: WHY }).closest('.card') as HTMLElement;
		expect(why).toHaveTextContent('“kq3z8wxv1m7tbn5r6yhp” (20 characters)');
		expect(why).toHaveTextContent('It scored 4.322');
		expect(why).toHaveTextContent('Every one of its 48 lookups from 2 devices in this window came back as “no such name”');
		expect(within(why).getByText('What to do')).toBeInTheDocument();
		expect(screen.getByText('Counted as the Threats page counts: every device, including 1 excluded in Settings.')).toBeInTheDocument();
		const askers = screen.getByRole('table', { name: 'Devices that looked it up' });
		expect(within(askers).getAllByText('Excluded in Settings')).toHaveLength(1);
		expect(kpi('Lookups')).toHaveTextContent('48');
		expectNoNestedInteractive(container);
	});

	it('starts on the range the link carries', async () => {
		goTo(`?range=7d&finding=${encodeURIComponent(NAME)}`);
		stubDaemon(byMode);
		render(Page);
		await vi.waitFor(() => expect(domainCalls()).toHaveLength(1));
		const call = domainCalls()[0];
		expect(Date.parse(call.searchParams.get('to')!) - Date.parse(call.searchParams.get('from')!)).toBe(168 * 3_600_000);
		expect(call.searchParams.get('interval')).toBe('1h');
	});

	it("opens a failed-lookups link's exact window as Custom", async () => {
		const from = '2026-11-15T00:00:00.000Z';
		const to = '2026-11-16T00:00:00.000Z';
		goTo(`?finding=${encodeURIComponent(NAME)}&from=${from}&to=${to}&range=24h`);
		stubDaemon(byMode);
		render(Page);
		await vi.waitFor(() => expect(screen.getByRole('heading', { name: WHY })).toBeInTheDocument());
		expect(domainCalls()[0].searchParams.get('from')).toBe(from);
		expect(domainCalls()[0].searchParams.get('to')).toBe(to);
		// OLD CODE: expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true'); (NET-348: the pill is named by its window)
		expect(screen.getByRole('button', { name: windowWords(from, to) })).toHaveAttribute('aria-pressed', 'true');
	});

	it('refetches when it moves between ordinary and finding mode, and never shows the other mode', async () => {
		stubDaemon(byMode);
		render(Page);
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('420'));
		expect(screen.queryByRole('heading', { name: WHY })).not.toBeInTheDocument();

		goTo(`?finding=${encodeURIComponent(NAME)}`);
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('48'));
		expect(screen.getByRole('heading', { name: WHY })).toBeInTheDocument();

		goTo('');
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('420'));
		expect(screen.queryByRole('heading', { name: WHY })).not.toBeInTheDocument();
		expect(screen.queryByText(/Counted as the Threats page counts/)).not.toBeInTheDocument();
		expect(domainCalls().map((u) => u.searchParams.has('finding'))).toEqual([false, true, false]);
	});

	it("drops a late finding reply once the page has moved back to ordinary mode", async () => {
		let release: (body: DomainSummary) => void = () => {};
		stubDaemon((url) => (url.searchParams.has('finding') ? new Promise<DomainSummary>((r) => (release = r)) : PLAIN));
		goTo(`?finding=${encodeURIComponent(NAME)}`);
		render(Page);
		await vi.waitFor(() => expect(domainCalls()).toHaveLength(1));
		goTo('');
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('420'));
		release(DOMAIN_FINDING);
		await new Promise((r) => setTimeout(r, 0));
		expect(kpi('Lookups')).toHaveTextContent('420');
		expect(screen.queryByRole('heading', { name: WHY })).not.toBeInTheDocument();
	});
});
