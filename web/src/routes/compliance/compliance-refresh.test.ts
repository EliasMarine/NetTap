/**
 * Security posture against the refresh contract (PLAN.md §5.5) and its redesigned cards:
 * what the loader reports, a stale load dropped, the loading and error states, the table.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import CompliancePage from './+page.svelte';

const REPLIES: Record<string, unknown> = {
	'/api/traffic/protocols': {
		protocols: [],
		services: [{ name: 'ssl', count: 80 }],
		encryption: { eligible: 200, encrypted: 120 },
		dns: { plain: 90, over_tls: 10 },
	},
	'/api/alerts/count': { from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } },
	'/api/devices/count': { from: '', to: '', count: 2 },
	'/api/risk/scores': { devices: [{ ip: '192.168.1.10' }, { ip: '192.168.1.11' }] },
	'/api/investigations/stats': { total: 0, by_status: {} },
	// NET-228: the zero-alert finding reads the pipeline's state
	'/api/system/health': {
		status: 'healthy', healthy: true, opensearch_reachable: true,
		pipeline: { state: 'fresh', newest_record_at: '', age_seconds: 40, threshold_seconds: 900, sensors: {}, checked_at: '' },
	},
};

type Reply = { ok: boolean; status: number; json: () => Promise<unknown> };
const okReply = (body: unknown): Reply => ({ ok: true, status: 200, json: async () => body });
const failReply: Reply = { ok: false, status: 502, json: async () => ({}) };

/** Each path answers from `replies`, or fails when it is listed in `failing`. */
function stubDaemon(failing: string[] = [], replies: Record<string, unknown> = REPLIES) {
	const fn = vi.fn(async (url: string) => {
		const path = url.split('?')[0];
		return failing.includes(path) ? failReply : okReply(replies[path]);
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

afterEach(() => {
	vi.unstubAllGlobals();
});

const card = (title: string) => screen.getByRole('heading', { name: title }).closest('.card') as HTMLElement;

describe('Security posture refresh contract', () => {
	it('reports ok when every input loads', async () => {
		stubDaemon();
		render(CompliancePage);

		await waitFor(() => expect(get(pageRefresh).status).toBe('ok'));
		expect(get(pageRefresh).updatedAt).not.toBeNull();
		expect(within(card('Score by category')).getByRole('img', { name: /^Score by category: lowest is/ })).toBeInTheDocument();
	});

	it('reports partial when one input fails, and leaves only that input’s categories out', async () => {
		stubDaemon(['/api/risk/scores']);
		render(CompliancePage);

		await waitFor(() => expect(get(pageRefresh).status).toBe('partial'));
		expect(get(pageRefresh).updatedAt).toBeNull();
		expect(within(card('Overall security posture')).getByRole('alert')).toHaveTextContent(
			"Couldn't compute the overall score",
		);
		expect(screen.getByText(/^Not shown: Network segmentation, Monitoring coverage/)).toBeInTheDocument();
	});

	it('reports failed when every input fails, with Try again on the error states', async () => {
		const fetchMock = stubDaemon(Object.keys(REPLIES));
		render(CompliancePage);

		await waitFor(() => expect(get(pageRefresh).status).toBe('failed'));
		const radar = within(card('Score by category')).getByRole('alert');
		expect(radar).toHaveTextContent("Couldn't compute enough categories to draw them.");
		const calls = fetchMock.mock.calls.length;

		await fireEvent.click(within(radar).getByRole('button', { name: 'Try again' }));
		// OLD CODE: await waitFor(() => expect(fetchMock.mock.calls.length).toBe(calls + 5)); (NET-228: and the health)
		await waitFor(() => expect(fetchMock.mock.calls.length).toBe(calls + 6));
	});

	it('shows the loading state and no figures until the first load returns', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(CompliancePage);

		expect(await screen.findAllByRole('status')).toHaveLength(4);
		for (const label of ['Good', 'Needs attention', 'Poor']) {
			const kpi = screen.getByText(label, { selector: '.kpi-top span' }).closest('.kpi') as HTMLElement;
			expect(within(kpi).getByText('—')).toBeInTheDocument();
		}
		expect(screen.queryByText(/^\d+%$/)).not.toBeInTheDocument();
	});

	it('drops an older load that finishes after a newer one', async () => {
		let release!: () => void;
		const held = new Promise<void>((r) => (release = r));
		let firstCount = true;
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const path = url.split('?')[0];
				if (path === '/api/devices/count' && firstCount) {
					// the first load's device count arrives last, and says something else
					firstCount = false;
					await held;
					return okReply({ from: '', to: '', count: 40 });
				}
				return okReply(REPLIES[path]);
			}),
		);
		render(CompliancePage);
		await waitFor(() => expect(firstCount).toBe(false));

		// the top bar's Refresh (the page's own button is disabled while a load runs)
		expect(await refreshPage()).toBe('ok');
		const monitoring = card('Monitoring coverage');
		expect(within(monitoring).getByText('2 of 2 device(s) have risk scores computed')).toBeInTheDocument();

		release();
		await new Promise((r) => setTimeout(r, 0));
		expect(within(card('Monitoring coverage')).queryByText(/of 40 device/)).not.toBeInTheDocument();
		expect(within(card('Monitoring coverage')).getByText('100%')).toBeInTheDocument();
	});
});

describe('Security posture recommendations', () => {
	it('lists them highest priority first, and both columns sort', async () => {
		// Encryption at 60% gives a medium recommendation; DNS at 10% a high one
		stubDaemon();
		render(CompliancePage);
		const table = await screen.findByRole('table', { name: 'Recommendations' });

		const rows = within(table).getAllByRole('row').slice(1);
		expect(rows[0]).toHaveTextContent('High');
		expect(rows[0]).toHaveTextContent(/DNS-over-HTTPS/);

		for (const header of within(table).getAllByRole('columnheader')) {
			await fireEvent.click(within(header).getByRole('button'));
			expect(header).not.toHaveAttribute('aria-sort', 'none');
		}
	});
});
