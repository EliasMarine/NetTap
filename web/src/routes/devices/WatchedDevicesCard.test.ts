/**
 * NET-331: the Watched devices card. It shows what the page loaded (rows, states, sort), says when the
 * check is stale or paused, clears a watch with Stop watching, and hides itself in bridge mode.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Card from './WatchedDevicesCard.svelte';
import { setWatch, WATCH_BRIDGE_NOTE, type WatchCheck, type WatchedDevice, type WatchedDevicesResponse } from '$api/devices-watched';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

vi.mock('$api/devices-watched', async (original) => ({
	...(await original<typeof import('$api/devices-watched')>()),
	setWatch: vi.fn(),
}));

const MIN = 60_000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

const check = (over: Partial<WatchCheck> = {}): WatchCheck => ({
	attempt_at: ago(MIN),
	success_at: ago(MIN),
	capture_at: ago(2 * MIN),
	coverage_since: ago(60 * MIN),
	skipped: null,
	error: null,
	...over,
});

const NAS: WatchedDevice = { mac: 'AA:BB:CC:00:00:01', name: 'NAS', after_min: 60, state: 'down', seen_at: '2026-11-20T09:00:00Z', since: '2026-11-20T09:25:00Z' };
const PRINTER: WatchedDevice = { mac: 'AA:BB:CC:00:00:02', name: null, after_min: 1440, state: 'unknown', seen_at: null, since: null };
const TV: WatchedDevice = { mac: 'AA:BB:CC:00:00:03', name: 'TV', after_min: 15, state: 'up', seen_at: '2026-11-20T10:00:00Z', since: '2026-11-20T08:00:00Z' };

const reply = (over: Partial<WatchedDevicesResponse> = {}): WatchedDevicesResponse => ({ check: check(), devices: [TV, NAS, PRINTER], ...over });

// OLD CODE: Partial<{ …; failed: boolean; …; onreload: () => void }>, with failed: false (review M4/L1)
function renderCard(props: Partial<{ data: WatchedDevicesResponse | null; error: string | null; bridge: boolean; onreload: () => Promise<void> }> = {}) {
	const onreload = props.onreload ?? vi.fn(async () => {});
	const view = render(Card, { data: reply(), error: null, bridge: false, onreload, ...props });
	return { ...view, onreload };
}

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => ((resolve = res), (reject = rej)));
	return { promise, resolve, reject };
}

/** A row's Stop watching button, named for its device (review M3). */
const stopButton = (name: string) => screen.getByRole('button', { name: `Stop watching ${name}` });

const table = () => screen.getByRole('table', { name: 'Watched devices' });
/** Each body row's first cell, top to bottom. */
const firstCells = () => within(table()).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[0].textContent?.trim());

describe('Watched devices card (NET-331)', () => {
	afterEach(() => vi.clearAllMocks());

	it('lists each watched device with its link, state, time and sightings, offline first', () => {
		const { container } = renderCard();
		expect(firstCells()).toEqual(['NAS', 'AA:BB:CC:00:00:02', 'TV']);
		expect(screen.getByRole('link', { name: 'NAS' })).toHaveAttribute('href', '/devices/mac/AA%3ABB%3ACC%3A00%3A00%3A01');
		// no owner's name: the MAC, in mono
		expect(screen.getByRole('link', { name: 'AA:BB:CC:00:00:02' })).toHaveClass('mono');

		const row = (name: string) => screen.getByRole('link', { name }).closest('tr') as HTMLElement;
		expect(within(row('NAS')).getByText('Offline')).toHaveClass('chip', 'is-bad');
		expect(within(row('TV')).getByText('Online')).toHaveClass('chip', 'is-ok');
		expect(within(row('AA:BB:CC:00:00:02')).getByText('Waiting for first sighting')).toHaveClass('chip');
		expect(within(row('NAS')).getByText('1 hour')).toBeInTheDocument();
		expect(within(row('AA:BB:CC:00:00:02')).getByText('1 day')).toBeInTheDocument();
		// a device not yet seen has no sighting and no state time
		expect(within(row('AA:BB:CC:00:00:02')).getAllByText('—')).toHaveLength(2);
		expect(within(row('NAS')).getAllByRole('cell')[3]).toHaveTextContent('20 Nov');
		expect(screen.queryByRole('status')).not.toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('sorts on every column, both ways', async () => {
		renderCard();
		const header = (name: string) => screen.getByRole('columnheader', { name });
		expect(header('State')).toHaveAttribute('aria-sort', 'descending');

		await fireEvent.click(within(header('Device')).getByRole('button'));
		expect(firstCells()).toEqual(['TV', 'NAS', 'AA:BB:CC:00:00:02']);
		await fireEvent.click(within(header('Device')).getByRole('button'));
		expect(firstCells()).toEqual(['AA:BB:CC:00:00:02', 'NAS', 'TV']);

		await fireEvent.click(within(header('Alert after')).getByRole('button'));
		expect(firstCells()).toEqual(['AA:BB:CC:00:00:02', 'NAS', 'TV']);
		await fireEvent.click(within(header('Alert after')).getByRole('button'));
		expect(firstCells()).toEqual(['TV', 'NAS', 'AA:BB:CC:00:00:02']);

		// review M5: the time columns put rows in time order; a device not yet seen has no time, so it is last both ways
		await fireEvent.click(within(header('Last seen')).getByRole('button'));
		expect(firstCells()).toEqual(['TV', 'NAS', 'AA:BB:CC:00:00:02']);
		await fireEvent.click(within(header('Last seen')).getByRole('button'));
		expect(firstCells()).toEqual(['NAS', 'TV', 'AA:BB:CC:00:00:02']);
		await fireEvent.click(within(header('Since')).getByRole('button'));
		expect(firstCells()).toEqual(['NAS', 'TV', 'AA:BB:CC:00:00:02']);
		await fireEvent.click(within(header('Since')).getByRole('button'));
		expect(firstCells()).toEqual(['TV', 'NAS', 'AA:BB:CC:00:00:02']);

		await fireEvent.click(within(header('Action')).getByRole('button'));
		expect(header('Action')).toHaveAttribute('aria-sort', 'descending');
	});

	it('names each Stop watching button for its device', () => {
		renderCard();
		expect(within(table()).getAllByRole('button', { name: /^Stop watching/ }).map((b) => b.getAttribute('aria-label'))).toEqual([
			'Stop watching NAS',
			'Stop watching AA:BB:CC:00:00:02',
			'Stop watching TV',
		]);
	});

	// OLD CODE: it('Stop watching clears that watch, then asks the page to reload', …) (review M2: the row goes, it says so, focus moves)
	it('Stop watching clears that watch, drops its row, says so, reloads the list, then focuses the heading', async () => {
		vi.mocked(setWatch).mockResolvedValue({} as never);
		const reload = deferred<void>();
		const { onreload } = renderCard({ onreload: vi.fn(() => reload.promise) });
		await fireEvent.click(stopButton('TV'));
		expect(setWatch).toHaveBeenCalledWith('AA:BB:CC:00:00:03', null);
		expect((await screen.findByText('Stopped watching TV.')).closest('p')).toHaveAttribute('role', 'status');
		expect(screen.queryByRole('link', { name: 'TV' })).not.toBeInTheDocument();
		expect(firstCells()).toEqual(['NAS', 'AA:BB:CC:00:00:02']);
		expect(onreload).toHaveBeenCalledTimes(1);

		reload.resolve();
		await vi.waitFor(() => expect(screen.getByRole('heading', { name: 'Watched devices' })).toHaveFocus());
	});

	it("keeps a stopped watch's row gone when the reload fails, and shows the empty state after the last one", async () => {
		vi.mocked(setWatch).mockResolvedValue({} as never);
		const view = renderCard({ data: reply({ devices: [TV] }) });
		await fireEvent.click(stopButton('TV'));
		// the reload failed: the page passes the same list with the failure
		await view.rerender({ data: reply({ devices: [TV] }), error: 'NetTap answered HTTP 503.' });
		expect(await screen.findByText('No devices are watched')).toBeInTheDocument();
		expect(screen.getByText('Stopped watching TV.')).toBeInTheDocument();
	});

	// OLD CODE: it('says why Stop watching failed, and reloads nothing', …) clicked { name: 'Stop watching' } (review M3)
	it('says why Stop watching failed, keeps the row, and reloads nothing', async () => {
		vi.mocked(setWatch).mockRejectedValue(new Error("Couldn't save the change (HTTP 503)."));
		const { onreload } = renderCard();
		await fireEvent.click(stopButton('NAS'));
		expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't stop watching NAS. Couldn't save the change (HTTP 503).");
		expect(screen.getByRole('link', { name: 'NAS' })).toBeInTheDocument();
		expect(screen.queryByText(/^Stopped watching/)).not.toBeInTheDocument();
		expect(onreload).not.toHaveBeenCalled();
	});

	it('runs one stop at a time: a second click is ignored, every button waits, and they come back after a failure', async () => {
		const save = deferred<never>();
		vi.mocked(setWatch).mockReturnValueOnce(save.promise);
		renderCard();
		await fireEvent.click(stopButton('NAS'));
		await fireEvent.click(stopButton('NAS'));
		await fireEvent.click(stopButton('TV'));
		expect(setWatch).toHaveBeenCalledTimes(1);
		expect(stopButton('NAS')).toHaveTextContent('Stopping…');
		for (const button of within(table()).getAllByRole('button', { name: /^Stop watching/ })) expect(button).toBeDisabled();

		save.reject(new Error('NetTap answered HTTP 502.'));
		await screen.findByRole('alert');
		for (const button of within(table()).getAllByRole('button', { name: /^Stop watching/ })) expect(button).toBeEnabled();
		expect(stopButton('NAS')).toHaveTextContent('Stop watching');
	});

	it('warns when the last successful check is over 15 minutes old', () => {
		renderCard({ data: reply({ check: check({ success_at: ago(20 * MIN) }) }) });
		expect(screen.getByRole('status')).toHaveTextContent('The last check was over 15 minutes ago, so these states may be out of date.');
	});

	it('says nothing for a check 10 minutes old', () => {
		renderCard({ data: reply({ check: check({ success_at: ago(10 * MIN) }) }) });
		expect(screen.queryByRole('status')).not.toBeInTheDocument();
	});

	it("shows the check's error, whatever its age", () => {
		renderCard({ data: reply({ check: check({ error: "The watched devices file can't be read." }) }) });
		expect(screen.getByRole('status')).toHaveTextContent("Couldn't check the watched devices: The watched devices file can't be read.");
	});

	it('says watching is paused while nothing new is indexed, before any success, and Stop watching still works', () => {
		renderCard({ data: reply({ check: check({ success_at: null, skipped: 'pipeline' }) }) });
		expect(screen.getByRole('status')).toHaveTextContent('Watching is paused: no new traffic has been indexed for 10 minutes');
		// OLD CODE: getAllByRole('button', { name: 'Stop watching' }) (review M3: each names its device)
		expect(within(table()).getAllByRole('button', { name: /^Stop watching/ })).toHaveLength(3);
		expect(within(table()).getAllByRole('button', { name: /^Stop watching/ })[0]).toBeEnabled();
	});

	it("says watching is paused while capture isn't ready, without a second stale warning", () => {
		renderCard({ data: reply({ check: check({ success_at: ago(40 * MIN), skipped: 'mode' }) }) });
		const statuses = screen.getAllByRole('status');
		expect(statuses).toHaveLength(1);
		expect(statuses[0]).toHaveTextContent("Watching is paused: capture isn't ready.");
	});

	it("names the daemon's reason when capture isn't ready", () => {
		renderCard({ data: reply({ check: check({ skipped: 'mode', reason: 'promiscuous mode is off' }) }) });
		expect(screen.getByRole('status')).toHaveTextContent('Checks are paused: promiscuous mode is off.');
		expect(screen.queryByText(/System page/)).not.toBeInTheDocument();
	});

	it('falls back to the System page line when the daemon gives no reason', () => {
		renderCard({ data: reply({ check: check({ skipped: 'mode', reason: null }) }) });
		expect(screen.getByRole('status')).toHaveTextContent("Watching is paused: capture isn't ready. Check the capture status on the System page.");
	});

	it('is hidden in bridge mode, with the reason in its place', () => {
		renderCard({ bridge: true });
		expect(screen.queryByRole('table')).not.toBeInTheDocument();
		expect(screen.queryByRole('heading', { name: 'Watched devices' })).not.toBeInTheDocument();
		expect(screen.getByRole('note')).toHaveTextContent(WATCH_BRIDGE_NOTE);
	});

	it('says how to watch a device when none is watched', () => {
		renderCard({ data: reply({ devices: [] }) });
		expect(screen.getByText('No devices are watched')).toBeInTheDocument();
		expect(screen.getByText('Open a device and choose Watch.')).toBeInTheDocument();
		expect(screen.queryByRole('table')).not.toBeInTheDocument();
	});

	// OLD CODE: rerender({ data: null, failed: true }) (review M4: the daemon's reason shows too)
	it("loads, then fails with the daemon's reason and Try again, never an empty list", async () => {
		const { rerender, onreload } = renderCard({ data: null });
		expect(screen.getByRole('status')).toHaveTextContent('Loading watched devices');
		await rerender({ data: null, error: "Watched devices can't be listed: the device details file is unreadable." });
		expect(screen.getByText("Couldn't load watched devices: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Watched devices can't be listed: the device details file is unreadable.")).toBeInTheDocument();
		expect(screen.queryByText('No devices are watched')).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(onreload).toHaveBeenCalledTimes(1);
	});

	// OLD CODE: renderCard({ failed: true }) (review M4)
	it('keeps the last list on a failed refresh and says why', () => {
		renderCard({ error: 'NetTap answered HTTP 503.' });
		expect(screen.getByRole('status')).toHaveTextContent("Couldn't refresh watched devices; showing the last figures loaded. NetTap answered HTTP 503.");
		expect(table()).toBeInTheDocument();
	});
});
