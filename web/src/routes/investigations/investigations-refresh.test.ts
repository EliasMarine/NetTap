/**
 * Investigations against the refresh contract (PLAN.md §5.5) and the redesigned cards:
 * what the loader reports, stale loads dropped, the loading/empty/error states, the table.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh } from '$lib/stores/pageRefresh';
import * as api from '$api/investigations';
import type { Investigation, InvestigationStats } from '$api/investigations';
import InvestigationsPage from './+page.svelte';

vi.mock('$api/investigations', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/investigations')>()),
	getInvestigations: vi.fn(),
	getInvestigationStats: vi.fn(),
}));

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

function inv(id: string, over: Partial<Investigation> = {}): Investigation {
	return {
		id,
		title: `Case ${id}`,
		description: '',
		status: 'open',
		severity: 'medium',
		created_at: '2026-11-01T10:00:00Z',
		updated_at: '2026-11-01T10:00:00Z',
		alert_ids: [],
		device_ips: [],
		notes: [],
		tags: [],
		...over,
	};
}

const STATS: InvestigationStats = { total: 3, by_status: { open: 2, in_progress: 1 }, by_severity: {} };
const list = vi.mocked(api.getInvestigations);
const stats = vi.mocked(api.getInvestigationStats);

afterEach(() => {
	vi.clearAllMocks();
});

/** The number on the KPI card whose label is `label` (the h1 also says "Investigations"). */
const kpiValue = (label: string) =>
	within(screen.getByText(label, { selector: '.kpi-top span' }).closest('.kpi') as HTMLElement).getByText(/./, {
		selector: '.kpi-num',
	});

describe('Investigations refresh contract', () => {
	it('reports ok when the list and the counts load', async () => {
		list.mockResolvedValue({ investigations: [inv('a')] });
		stats.mockResolvedValue(STATS);
		render(InvestigationsPage);

		await waitFor(() => expect(get(pageRefresh).status).toBe('ok'));
		expect(get(pageRefresh).updatedAt).not.toBeNull();
		expect(kpiValue('Investigations')).toHaveTextContent('3');
		expect(kpiValue('In progress')).toHaveTextContent('1');
	});

	it('reports partial when only the counts fail, and the KPIs say — rather than 0', async () => {
		list.mockResolvedValue({ investigations: [inv('a')] });
		stats.mockRejectedValue(new Error('boom'));
		render(InvestigationsPage);

		await waitFor(() => expect(get(pageRefresh).status).toBe('partial'));
		expect(get(pageRefresh).updatedAt).toBeNull();
		expect(kpiValue('Investigations')).toHaveTextContent('—');
		expect(screen.getAllByText("Couldn't load the counts")).toHaveLength(4);
		expect(screen.getByRole('table', { name: 'Investigations' })).toBeInTheDocument();
	});

	it('reports failed when both fail, and Try again loads again', async () => {
		list.mockRejectedValue(new Error('boom'));
		stats.mockRejectedValue(new Error('boom'));
		render(InvestigationsPage);

		await waitFor(() => expect(get(pageRefresh).status).toBe('failed'));
		const alert = screen.getByRole('alert');
		expect(alert).toHaveTextContent("Couldn't load investigations: the request failed.");

		list.mockResolvedValue({ investigations: [] });
		stats.mockResolvedValue({ total: 0, by_status: {}, by_severity: {} });
		await fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));

		await waitFor(() => expect(get(pageRefresh).status).toBe('ok'));
		expect(list).toHaveBeenCalledTimes(2);
		expect(screen.getByText('No investigations yet')).toBeInTheDocument();
	});

	it('shows the loading state, and no counts, until the first load returns', async () => {
		list.mockReturnValue(new Promise(() => {}));
		stats.mockReturnValue(new Promise(() => {}));
		render(InvestigationsPage);

		expect(await screen.findByRole('status')).toHaveTextContent('Loading investigations');
		expect(kpiValue('Open')).toHaveTextContent('—');
		expect(get(pageRefresh).status).toBeNull();
	});

	it('drops an older load that finishes after a newer one (filter change mid-load)', async () => {
		const all = deferred<{ investigations: Investigation[] }>();
		const open = deferred<{ investigations: Investigation[] }>();
		list.mockReturnValueOnce(all.promise).mockReturnValueOnce(open.promise);
		stats.mockResolvedValue(STATS);
		render(InvestigationsPage);
		await waitFor(() => expect(list).toHaveBeenCalledTimes(1));

		await fireEvent.click(screen.getByRole('button', { name: /^Open ·/ }));
		expect(list).toHaveBeenLastCalledWith({ status: 'open' });

		open.resolve({ investigations: [inv('fresh', { title: 'Open case' })] });
		await screen.findByText('Open case');
		all.resolve({ investigations: [inv('stale', { title: 'Stale case' })] });
		await new Promise((r) => setTimeout(r, 0));

		expect(screen.queryByText('Stale case')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: /^Open ·/ })).toHaveAttribute('aria-pressed', 'true');
	});

	it('writes nothing after the page has gone', async () => {
		const pending = deferred<{ investigations: Investigation[] }>();
		list.mockReturnValue(pending.promise);
		stats.mockResolvedValue(STATS);
		const view = render(InvestigationsPage);
		await waitFor(() => expect(list).toHaveBeenCalled());

		view.unmount();
		pending.resolve({ investigations: [inv('late')] });
		await new Promise((r) => setTimeout(r, 0));

		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null, status: null });
	});
});

describe('Investigations table', () => {
	const ROWS = [
		inv('a', { title: 'Beacon', severity: 'critical', status: 'open', alert_ids: ['x', 'y'], tags: ['malware'] }),
		inv('b', { title: 'Alpha scan', severity: 'low', status: 'resolved', device_ips: ['192.0.2.1'] }),
	];

	it('sorts on every column', async () => {
		list.mockResolvedValue({ investigations: ROWS });
		stats.mockResolvedValue(STATS);
		render(InvestigationsPage);
		const table = await screen.findByRole('table', { name: 'Investigations' });

		const headers = within(table).getAllByRole('columnheader');
		expect(headers.map((h) => h.textContent?.trim())).toEqual([
			'Investigation', 'Severity', 'Status', 'Alerts', 'Devices', 'Notes', 'Tags', 'Created',
		]);
		for (const header of headers) {
			await fireEvent.click(within(header).getByRole('button'));
			expect(header).not.toHaveAttribute('aria-sort', 'none');
		}
	});

	it('opens a row in the detail card and closes it again', async () => {
		list.mockResolvedValue({ investigations: ROWS });
		stats.mockResolvedValue(STATS);
		render(InvestigationsPage);

		await fireEvent.click(await screen.findByRole('button', { name: 'Open investigation Alpha scan' }));
		const detail = screen.getByRole('heading', { name: 'Alpha scan' }).closest('.card') as HTMLElement;
		// OLD CODE START: expect(within(detail).getByRole('link', { name: '192.0.2.1' })).toHaveAttribute('href', '/devices/192.0.2.1'); OLD CODE END
		// NET-160: an internet address opens its address page, not a device page
		expect(within(detail).getByRole('link', { name: '192.0.2.1' })).toHaveAttribute('href', '/address/192.0.2.1');
		expect(within(detail).getByLabelText('Status')).toHaveValue('resolved');

		await fireEvent.click(within(detail).getByRole('button', { name: 'Close details' }));
		expect(screen.queryByRole('heading', { name: 'Alpha scan' })).not.toBeInTheDocument();
	});
});
