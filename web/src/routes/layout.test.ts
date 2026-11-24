import { describe, it, expect, vi, afterEach, beforeEach, onTestFinished } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import type { Writable } from 'svelte/store';
// OLD CODE: import { page } from '$app/stores'; (kit 3 removed it; the mock below keeps the store in pageHolder; NET-315)
import { goto } from '$app/navigation';
import { SIGN_IN_FIRST } from '$lib/auth-errors';
import { trackPasswordChange } from '$lib/password-change';
import * as captureApi from '$api/capture';
import * as systemApi from '$api/system';
import { get } from 'svelte/store';
import { _configure, alertSnapshots } from '$lib/stores/alertSnapshot';
import Layout from './+layout.svelte';
import AccountTab from './settings/tabs/AccountTab.svelte';
import { captureMode as modeStore, initCaptureMode } from '$lib/stores/captureMode';

// OLD CODE START — kit 3: $app/stores → $app/state (NET-315)
// vi.mock('$app/stores', async () => {
// 	const { writable } = await import('svelte/store');
// 	return { page: writable({ url: new URL('http://localhost/system') }) };
// });
// OLD CODE END
const pageHolder = vi.hoisted(() => ({ store: null as unknown as Writable<{ url: URL }> }));
vi.mock('$app/state', async () =>
	(await import('../tests/app-navigation.svelte')).stateFromStores(async () => {
		const { writable } = await import('svelte/store');
		pageHolder.store = writable({ url: new URL('http://localhost/system') });
		return { page: pageHolder.store };
	}),
);
vi.mock('$app/navigation', () => ({ goto: vi.fn(), afterNavigate: vi.fn() }));
vi.mock('$api/capture', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/capture')>()),
	getCaptureMode: vi.fn(),
	getCaptureHealth: vi.fn(),
}));
vi.mock('$api/system', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/system')>()),
	getStorageStatus: vi.fn(),
}));
// OLD CODE: vi.mock('$lib/stores/captureMode', () => ({ initCaptureMode: vi.fn() })); (NET-225: the chip reads the shared store)
vi.mock('$lib/stores/captureMode', async () => {
	const { writable } = await import('svelte/store');
	return { captureMode: writable(null), initCaptureMode: vi.fn() };
});

const children = createRawSnippet(() => ({ render: () => '<p>page body</p>' }));
const never = <T,>() => new Promise<T>(() => {});
const counts = (total: number) => ({ from: '', to: '', counts: { total, high: total, medium: 0, low: 0 } });
// OLD CODE: const pageStore = page as unknown as Writable<{ url: URL }>; (NET-315)
// The Layout import above has already run the $app/state mock, so the store exists
const pageStore = pageHolder.store;

function health(status: string, iface = 'enp1s0'): captureApi.CaptureHealthResponse {
	return { mode: 'bridge', status, capture_interface: iface, link_up: true, promisc_enabled: true, issues: [] };
}

/** /me refusing the session, as the web app does without a valid cookie. */
const meRefused = () => new Response(JSON.stringify({ authenticated: false }), { status: 401 });

// OLD CODE START — NET-358: the shell asks /api/auth/me again before it sends anyone to sign in
// /** /api/system/ping answers with `ping`; everything else (NotificationBell's requests) 503. */
// function stubFetch(ping: () => Response | Promise<Response> = () => new Response(JSON.stringify({ status: 'ok' }))) {
// 	const fetchMock = vi.fn(async (url: string) =>
// 		url === '/api/system/ping' ? ping() : new Response('{}', { status: 503 }),
// 	);
// OLD CODE END
/** /api/system/ping answers with `ping`, /api/auth/me with `me`; everything else with `other` (NotificationBell's requests: 503). */
function stubFetch(
	// OLD CODE: ping: () => Response | Promise<Response> = …, (NET-361: the ping carries a deadline signal now)
	ping: (init?: RequestInit) => Response | Promise<Response> = () => new Response(JSON.stringify({ status: 'ok' })),
	me: (init?: RequestInit) => Response | Promise<Response> = meRefused,
	other: (url: string, init?: RequestInit) => Response | Promise<Response> = () => new Response('{}', { status: 503 }),
) {
	const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
		// OLD CODE: url === '/api/system/ping' ? ping() : … (NET-361)
		url === '/api/system/ping' ? ping(init) : url === '/api/auth/me' ? me(init) : other(url, init),
	);
	vi.stubGlobal('fetch', fetchMock);
	vi.stubGlobal('EventSource', class { addEventListener() {} close() {} });
	return fetchMock;
}

const pingCalls = (f: ReturnType<typeof vi.fn>) => f.mock.calls.filter(([u]) => u === '/api/system/ping').length;

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((res) => (resolve = res));
	return { promise, resolve };
}

/** AbortSignal.timeout on the fake clock: Node's own timer doesn't follow vi.useFakeTimers. */
function timeoutsOnFakeClock() {
	const spy = vi.spyOn(AbortSignal, 'timeout').mockImplementation((ms) => {
		const controller = new AbortController();
		setTimeout(() => controller.abort(new DOMException('The operation timed out.', 'TimeoutError')), ms);
		return controller.signal;
	});
	onTestFinished(() => spy.mockRestore());
	return spy;
}
/** A request that never answers: it ends only when its signal aborts. */
const untilAborted = (init?: RequestInit) =>
	new Promise<Response>((_, reject) => init?.signal?.addEventListener('abort', () => reject(init.signal?.reason)));

function renderLayout(username: string | null = 'admin') {
	return render(Layout, { props: { children, data: { username } } });
}

beforeEach(() => {
	pageStore.set({ url: new URL('http://localhost/system') });
	_configure({ fetcher: () => never() });
	// OLD CODE: vi.mocked(captureApi.getCaptureMode).mockResolvedValue({ mode: 'bridge', interface: 'br0' }); (NET-225: the store answers now)
	vi.mocked(captureApi.getCaptureMode).mockReturnValue(never());
	modeStore.set('bridge');
	vi.mocked(captureApi.getCaptureHealth).mockReturnValue(never());
	vi.mocked(systemApi.getStorageStatus).mockReturnValue(never());
	stubFetch();
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.clearAllMocks();
});

describe('layout capture mode chip', () => {
	it.each([
		['dhcp_gateway', 'DHCP Gateway mode · eth1'],
		['mirror', 'Mirror mode · eth1'],
		['bridge', 'Bridge mode · eth1'],
	])('shows %s as "%s" while capture is healthy', async (mode, text) => {
		// OLD CODE: vi.mocked(captureApi.getCaptureMode).mockResolvedValue({ mode, interface: 'eth1' }); (NET-225)
		modeStore.set(mode as 'bridge');
		vi.mocked(captureApi.getCaptureHealth).mockResolvedValue(health('normal', 'eth1'));
		renderLayout();
		expect(await screen.findByText(text)).toBeInTheDocument();
	});

	it('says the mode is unknown instead of guessing Bridge (#96)', async () => {
		// OLD CODE: vi.mocked(captureApi.getCaptureMode).mockRejectedValue(new Error('503')); (NET-225: a failed or unrecognised reply)
		modeStore.set('unknown');
		renderLayout();
		expect(await screen.findByText('Mode unknown')).toBeInTheDocument();
		expect(screen.queryByText(/Bridge/)).not.toBeInTheDocument();
		expect(screen.getByText('page body')).toBeInTheDocument();
	});

	it('still shows capture health when the mode request fails', async () => {
		// OLD CODE: vi.mocked(captureApi.getCaptureMode).mockRejectedValue(new Error('503')); (NET-225)
		modeStore.set('unknown');
		vi.mocked(captureApi.getCaptureHealth).mockResolvedValue(health('down'));
		renderLayout();
		expect(await screen.findByText('Capture stopped')).toBeInTheDocument();
	});

	// NET-225: a backup restore re-reads the mode through the shared store; the chip loaded its own copy once
	it('follows the shared capture-mode store, so a re-read reaches the chip without a reload', async () => {
		modeStore.set('mirror');
		vi.mocked(captureApi.getCaptureHealth).mockResolvedValue(health('normal', 'eth1'));
		renderLayout();
		expect(await screen.findByText('Mirror mode · eth1')).toBeInTheDocument();
		expect(initCaptureMode).toHaveBeenCalled();

		modeStore.set('bridge');
		expect(await screen.findByText('Bridge mode · eth1')).toBeInTheDocument();
		expect(screen.queryByText(/Mirror/)).not.toBeInTheDocument();
	});

	it('says it is checking until the store has an answer', async () => {
		modeStore.set(null);
		renderLayout();
		expect(await screen.findByText('Checking mode…')).toBeInTheDocument();
	});

	it('says capture status is unknown when the health request fails', async () => {
		vi.mocked(captureApi.getCaptureHealth).mockRejectedValue(new Error('503'));
		renderLayout();
		expect(await screen.findByText('Capture status unknown')).toBeInTheDocument();
	});
});

// The top bar used to say "Online" even with the daemon down.
describe('layout daemon status', () => {

	it('shows no warning while the daemon answers', async () => {
		const f = stubFetch();
		renderLayout();
		await vi.waitFor(() => expect(pingCalls(f)).toBe(1));
		await tick();
		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
	});

	it("warns that it can't reach NetTap when the daemon doesn't answer", async () => {
		stubFetch(() => new Response(JSON.stringify({ error: 'Daemon unreachable' }), { status: 502 }));
		renderLayout();
		expect(await screen.findByText("Can't reach NetTap")).toBeInTheDocument();
	});

	it('does not take a login-page redirect for the daemon answering', async () => {
		stubFetch(() => new Response('<!doctype html><title>Login</title>', { status: 200 }));
		renderLayout();
		expect(await screen.findByText("Can't reach NetTap")).toBeInTheDocument();
	});

	it('does not warn before the first answer', async () => {
		stubFetch(() => never());
		renderLayout();
		await tick();
		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
	});

	it('re-checks every 30 s with capture health and storage, and stops after unmount', async () => {
		vi.useFakeTimers();
		// NET-361: they answer, so the next tick asks again (one still out is skipped)
		vi.mocked(captureApi.getCaptureHealth).mockRejectedValue(new Error('503'));
		vi.mocked(systemApi.getStorageStatus).mockRejectedValue(new Error('503'));
		let up = true;
		const f = stubFetch(() => (up ? new Response(JSON.stringify({ status: 'ok' })) : new Response('{}', { status: 502 })));
		const { unmount } = renderLayout();
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();

		up = false;
		await vi.advanceTimersByTimeAsync(30_000);
		expect(screen.getByText("Can't reach NetTap")).toBeInTheDocument();
		expect(captureApi.getCaptureHealth).toHaveBeenCalledTimes(2);
		expect(systemApi.getStorageStatus).toHaveBeenCalledTimes(2);
		// NET-225: a mode request that failed at startup is asked again, so the chip doesn't stay "Mode unknown"
		expect(initCaptureMode).toHaveBeenCalledTimes(2);

		const before = pingCalls(f);
		unmount();
		await vi.advanceTimersByTimeAsync(120_000);
		expect(pingCalls(f)).toBe(before);
	});

	it('pauses polling while the tab is hidden', async () => {
		vi.useFakeTimers();
		const f = stubFetch();
		renderLayout();
		await vi.advanceTimersByTimeAsync(0);
		const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
		await vi.advanceTimersByTimeAsync(90_000);
		expect(pingCalls(f)).toBe(1);
		hidden.mockRestore();
	});

	// NET-361: with several tabs open, QA saw 10 copies of the ping queued in one tab
	describe('one request at a time', () => {
		const shellCalls = (f: ReturnType<typeof vi.fn>) => [
			pingCalls(f),
			vi.mocked(captureApi.getCaptureHealth).mock.calls.length,
			vi.mocked(systemApi.getStorageStatus).mock.calls.length,
		];

		it('sends no second ping, capture-health or storage request while the last one is out, each on its own', async () => {
			vi.useFakeTimers();
			// these ignore their deadline, so only the one-at-a-time rule holds them back
			const ping = deferred<Response>();
			const healthReply = deferred<captureApi.CaptureHealthResponse>();
			const storageReply = deferred<systemApi.StorageStatus>();
			const f = stubFetch(() => ping.promise);
			vi.mocked(captureApi.getCaptureHealth).mockReturnValue(healthReply.promise);
			vi.mocked(systemApi.getStorageStatus).mockReturnValue(storageReply.promise);
			renderLayout();
			await vi.advanceTimersByTimeAsync(90_000);
			expect(shellCalls(f)).toEqual([1, 1, 1]);

			healthReply.resolve(health('normal'));
			await vi.advanceTimersByTimeAsync(30_000);
			expect(shellCalls(f)).toEqual([1, 2, 1]); // health is asked again; the ping and storage are still out

			ping.resolve(new Response(JSON.stringify({ status: 'ok' })));
			storageReply.resolve({ disk_usage_percent: 10 } as systemApi.StorageStatus);
			await vi.advanceTimersByTimeAsync(30_000);
			expect(shellCalls(f)).toEqual([2, 3, 2]);
		});

		it("gives up on each after 15 s, says it can't reach NetTap, and asks again on the next tick", async () => {
			vi.useFakeTimers();
			const timeouts = timeoutsOnFakeClock();
			const f = stubFetch(untilAborted);
			vi.mocked(captureApi.getCaptureHealth).mockImplementation((signal) => untilAborted({ signal }) as never);
			vi.mocked(systemApi.getStorageStatus).mockImplementation((signal) => untilAborted({ signal }) as never);
			renderLayout();
			await vi.advanceTimersByTimeAsync(14_999);
			expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
			expect(screen.queryByText('Capture status unknown')).not.toBeInTheDocument();

			await vi.advanceTimersByTimeAsync(1);
			expect(screen.getByText("Can't reach NetTap")).toBeInTheDocument();
			expect(screen.getByText('Capture status unknown')).toBeInTheDocument();
			expect(timeouts).toHaveBeenCalledWith(15_000);

			await vi.advanceTimersByTimeAsync(15_000); // the 30 s tick
			expect(shellCalls(f)).toEqual([2, 2, 2]);
		});

		it("doesn't let an older run's storage deadline clear the new run's disk-full warning", async () => {
			vi.useFakeTimers();
			timeoutsOnFakeClock();
			let calls = 0;
			vi.mocked(systemApi.getStorageStatus).mockImplementation((signal) =>
				++calls === 1
					? (untilAborted({ signal }) as never)
					: Promise.resolve({ disk_usage_percent: 99, capture_paused_disk_full: true } as systemApi.StorageStatus),
			);
			renderLayout();
			await vi.advanceTimersByTimeAsync(0);
			pageStore.set({ url: new URL('http://localhost/login?next=%2Fsystem') }); // the sign-in page has no shell
			await vi.advanceTimersByTimeAsync(0);
			pageStore.set({ url: new URL('http://localhost/system') }); // signed in: a new run
			await vi.advanceTimersByTimeAsync(0);
			expect(screen.getByText('Packet capture paused: disk full')).toBeInTheDocument();

			await vi.advanceTimersByTimeAsync(15_000); // the first run's request reaches its deadline
			expect(screen.getByText('Packet capture paused: disk full')).toBeInTheDocument();
		});

		it("starts no second alert count while the shell's last refresh is out, and refreshes once it answers", async () => {
			vi.useFakeTimers();
			const pending = deferred<ReturnType<typeof counts>>();
			let n = 0;
			const fetcher = vi.fn(() => (++n === 2 ? pending.promise : Promise.resolve(counts(n))));
			_configure({ fetcher: fetcher as never });
			renderLayout();
			await vi.advanceTimersByTimeAsync(30_000);
			expect(fetcher).toHaveBeenCalledTimes(2); // the badge's first load and the first tick's refresh

			await vi.advanceTimersByTimeAsync(60_000);
			expect(fetcher).toHaveBeenCalledTimes(2);

			pending.resolve(counts(5));
			await vi.advanceTimersByTimeAsync(30_000);
			expect(fetcher).toHaveBeenCalledTimes(3);
		});
	});
});

// NET-198: a lapsed session sends the user to sign in instead of saying "Can't reach NetTap"
describe('layout session expiry', () => {
	const signInFirst = () => new Response(JSON.stringify({ error: SIGN_IN_FIRST }), { status: 401 });

	beforeEach(() => {
		vi.mocked(goto).mockReset();
	});

	it('opens the sign-in page, coming back to this page, when the session ran out', async () => {
		pageStore.set({ url: new URL('http://localhost/devices?range=7d') });
		stubFetch(signInFirst);
		renderLayout();
		await vi.waitFor(() => expect(goto).toHaveBeenCalledWith('/login?next=%2Fdevices%3Frange%3D7d'));
		await tick();
		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
	});

	// NET-259: Go Live opens before the first admin exists (setup cookie, no session), so no session ran out
	it('stays on the page, and says nothing is offline, before the first admin exists', async () => {
		pageStore.set({ url: new URL('http://localhost/go-live') });
		const res = signInFirst();
		const read = vi.spyOn(res, 'json');
		stubFetch(() => res);
		renderLayout(null);
		await vi.waitFor(() => expect(read).toHaveBeenCalled());
		await read.mock.results[0].value;
		await tick();
		expect(goto).not.toHaveBeenCalled();
		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
	});

	it("does not take the daemon's own 401 for a lapsed session", async () => {
		stubFetch(() => new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401 }));
		renderLayout();
		expect(await screen.findByText("Can't reach NetTap")).toBeInTheDocument();
		expect(goto).not.toHaveBeenCalled();
	});

	it('stays offline for a 401 that is not JSON', async () => {
		stubFetch(() => new Response('Unauthorized', { status: 401 }));
		renderLayout();
		expect(await screen.findByText("Can't reach NetTap")).toBeInTheDocument();
		expect(goto).not.toHaveBeenCalled();
	});

	it('still says it cannot reach NetTap when the network fails', async () => {
		stubFetch(() => Promise.reject(new TypeError('Failed to fetch')));
		renderLayout();
		expect(await screen.findByText("Can't reach NetTap")).toBeInTheDocument();
		expect(goto).not.toHaveBeenCalled();
	});

	it('starts no new poll while the sign-in page is opening', async () => {
		vi.useFakeTimers();
		vi.mocked(goto).mockReturnValueOnce(never());
		const f = stubFetch(signInFirst);
		renderLayout();
		await vi.advanceTimersByTimeAsync(0);
		expect(goto).toHaveBeenCalledTimes(1);

		await vi.advanceTimersByTimeAsync(120_000);

		expect(goto).toHaveBeenCalledTimes(1);
		expect(pingCalls(f)).toBe(1);
		expect(captureApi.getCaptureHealth).toHaveBeenCalledTimes(1);
		expect(systemApi.getStorageStatus).toHaveBeenCalledTimes(1);
		expect(initCaptureMode).toHaveBeenCalledTimes(1);
	});

	it('polls again when the navigation to sign in ends with the shell still open', async () => {
		vi.useFakeTimers();
		const f = stubFetch(signInFirst);
		renderLayout();
		await vi.advanceTimersByTimeAsync(0);
		expect(goto).toHaveBeenCalledTimes(1);

		await vi.advanceTimersByTimeAsync(30_000);

		expect(pingCalls(f)).toBe(2);
		expect(goto).toHaveBeenCalledTimes(2);
	});

	it('polls again when the navigation to sign in fails', async () => {
		vi.useFakeTimers();
		const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
		try {
			vi.mocked(goto).mockRejectedValueOnce(new Error('navigation failed'));
			const f = stubFetch(signInFirst);
			renderLayout();
			await vi.advanceTimersByTimeAsync(0);
			expect(logged).toHaveBeenCalledWith('Could not open the sign-in page:', expect.any(Error));

			await vi.advanceTimersByTimeAsync(30_000);

			expect(pingCalls(f)).toBe(2);
		} finally {
			logged.mockRestore();
		}
	});

	it('ignores a ping that was already on its way when the user signed in again', async () => {
		vi.useFakeTimers();
		let answerOld!: (r: Response) => void;
		const old = new Promise<Response>((resolve) => (answerOld = resolve));
		let calls = 0;
		stubFetch(() => (++calls === 1 ? old : new Response(JSON.stringify({ status: 'ok' }))));
		renderLayout();
		await vi.advanceTimersByTimeAsync(0);
		expect(calls).toBe(1);

		pageStore.set({ url: new URL('http://localhost/login?next=%2Fsystem') }); // the sign-in page has no shell
		await vi.advanceTimersByTimeAsync(0);
		pageStore.set({ url: new URL('http://localhost/system') }); // signed in: the shell polls again
		await vi.advanceTimersByTimeAsync(0);
		expect(calls).toBe(2);
		answerOld(signInFirst());
		await vi.advanceTimersByTimeAsync(0);

		expect(goto).not.toHaveBeenCalled();
	});

	// NET-361: one ping at a time, so the newer ping that starts the redirect comes from a new shell run (after a
	// sign-in round trip), not from the next 30 s tick while the old one is still out
	/** Leave the shell for the sign-in page and come back: the shell polls again at once. */
	async function remountShell() {
		pageStore.set({ url: new URL('http://localhost/login?next=%2Fsystem') });
		await vi.advanceTimersByTimeAsync(0);
		pageStore.set({ url: new URL('http://localhost/system') });
		await vi.advanceTimersByTimeAsync(0);
	}

	it('does not show offline for an older ping that fails after the redirect has started', async () => {
		vi.useFakeTimers();
		let failOld!: (r: Response) => void;
		const old = new Promise<Response>((resolve) => (failOld = resolve));
		let calls = 0;
		stubFetch(() => (++calls === 1 ? old : signInFirst()));
		vi.mocked(goto).mockReturnValueOnce(never());
		renderLayout();
		// OLD CODE: await vi.advanceTimersByTimeAsync(30_000); (NET-361: the tick skips while the old ping is out)
		await vi.advanceTimersByTimeAsync(0);
		await remountShell();
		expect(goto).toHaveBeenCalledTimes(1);

		failOld(new Response('{}', { status: 502 }));
		await vi.advanceTimersByTimeAsync(0);

		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
	});

	it("does not show offline for an older ping's network failure after the redirect has started", async () => {
		vi.useFakeTimers();
		let failOld!: (e: unknown) => void;
		const old = new Promise<Response>((_, reject) => (failOld = reject));
		let calls = 0;
		stubFetch(() => (++calls === 1 ? old : signInFirst()));
		vi.mocked(goto).mockReturnValueOnce(never());
		renderLayout();
		// OLD CODE: await vi.advanceTimersByTimeAsync(30_000); (NET-361: the tick skips while the old ping is out)
		await vi.advanceTimersByTimeAsync(0);
		await remountShell();
		expect(goto).toHaveBeenCalledTimes(1);

		failOld(new TypeError('Failed to fetch'));
		await vi.advanceTimersByTimeAsync(0);

		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
	});

	it('does not show offline for an older ping that fails after the shell has restarted', async () => {
		vi.useFakeTimers();
		let failOld!: (e: unknown) => void;
		const old = new Promise<Response>((_, reject) => (failOld = reject));
		let calls = 0;
		stubFetch(() => (++calls === 1 ? old : new Response(JSON.stringify({ status: 'ok' }))));
		renderLayout();
		await vi.advanceTimersByTimeAsync(0);
		pageStore.set({ url: new URL('http://localhost/login?next=%2Fsystem') });
		await vi.advanceTimersByTimeAsync(0);
		pageStore.set({ url: new URL('http://localhost/system') });
		await vi.advanceTimersByTimeAsync(0);
		expect(calls).toBe(2);

		failOld(new TypeError('Failed to fetch'));
		await vi.advanceTimersByTimeAsync(0);

		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
	});

	// NET-358: a 401 sent with the old cookie just before a password change landed must not throw away the
	// change's result (the Account tab's message and warning); the shell asks /api/auth/me again first
	describe('when a password change overlaps', () => {
		const meAccepted = () => new Response(JSON.stringify({ authenticated: true }), { status: 200 });
		const meCalls = (f: ReturnType<typeof vi.fn>) => f.mock.calls.filter(([u]) => u === '/api/auth/me').length;
		const settle = async () => {
			for (let i = 0; i < 5; i++) await new Promise((resolve) => setTimeout(resolve, 0));
		};
		// NET-361: deferred(), timeoutsOnFakeClock() and untilAborted() moved to file scope (the shell poll tests use them)

		it('waits for a change in flight before asking again, and stays once it has succeeded', async () => {
			const change = deferred<Response>();
			const tracked = trackPasswordChange(change.promise);
			const f = stubFetch(signInFirst, meAccepted);
			renderLayout();
			await vi.waitFor(() => expect(pingCalls(f)).toBe(1));
			await settle();
			expect(meCalls(f)).toBe(0); // still waiting for the change

			change.resolve(new Response(JSON.stringify({ success: true, warning: 'not on disk yet' })));
			await tracked;
			await vi.waitFor(() => expect(meCalls(f)).toBe(1));
			await settle();

			expect(goto).not.toHaveBeenCalled();
			expect(screen.getByText('page body')).toBeInTheDocument();
		});

		it('drops a /me refusal that comes back after a change succeeded', async () => {
			const me = deferred<Response>();
			const f = stubFetch(signInFirst, () => me.promise);
			renderLayout();
			await vi.waitFor(() => expect(meCalls(f)).toBe(1)); // asked with the old cookie

			await trackPasswordChange(Promise.resolve(new Response('{}', { status: 200 })));
			me.resolve(meRefused());
			await settle();

			expect(goto).not.toHaveBeenCalled();
		});

		it('stays when /me still accepts the session after a ping 401', async () => {
			const f = stubFetch(signInFirst, meAccepted);
			renderLayout();
			await vi.waitFor(() => expect(meCalls(f)).toBe(1));
			await settle();
			expect(goto).not.toHaveBeenCalled();
			expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
		});

		it('still opens the sign-in page when /me refuses too and no change happened', async () => {
			const f = stubFetch(signInFirst);
			renderLayout();
			await vi.waitFor(() => expect(goto).toHaveBeenCalledWith('/login?next=%2Fsystem'));
			expect(meCalls(f)).toBe(1);
		});

		// Only /me's own 401 means the session is gone; an unanswered or failed check is "don't know"
		it.each([
			['is rejected', () => Promise.reject(new TypeError('Failed to fetch'))],
			['answers 502', () => new Response('<html>Bad Gateway</html>', { status: 502 })],
		])('stays when the /me recheck %s', async (_, me) => {
			const f = stubFetch(signInFirst, me);
			renderLayout();
			await vi.waitFor(() => expect(meCalls(f)).toBe(1));
			await settle();
			expect(goto).not.toHaveBeenCalled();
			expect(screen.getByText('page body')).toBeInTheDocument();
		});

		it('a change that never answers is given up after 30 s, and then the shell asks /me again', async () => {
			vi.useFakeTimers();
			timeoutsOnFakeClock();
			const firstPing = deferred<Response>();
			let pings = 0;
			const f = stubFetch(
				() => (++pings === 1 ? firstPing.promise : signInFirst()),
				meRefused,
				(url, init) => (url === '/api/account/password' ? untilAborted(init) : new Response('{}', { status: 503 })),
			);
			renderLayout();
			render(AccountTab); // the real Settings › Account form sends the change
			await fireEvent.input(screen.getByLabelText('Current password', { exact: true }), { target: { value: 'Old-Pass-1' } });
			await fireEvent.input(screen.getByLabelText('New password', { exact: true }), { target: { value: 'New-Pass-1' } });
			await fireEvent.input(screen.getByLabelText('Confirm new password', { exact: true }), { target: { value: 'New-Pass-1' } });
			await fireEvent.submit(screen.getByRole('button', { name: 'Change password' }).closest('form')!);
			firstPing.resolve(signInFirst()); // a ping sent with the old cookie comes back 401 while the change hangs
			await vi.advanceTimersByTimeAsync(29_999);
			expect(meCalls(f)).toBe(0);

			await vi.advanceTimersByTimeAsync(1);
			expect(meCalls(f)).toBe(1);
			expect(goto).toHaveBeenCalledWith('/login?next=%2Fsystem');
			expect(screen.getByText(/NetTap didn't answer, so the password may or may not have changed\./)).toBeInTheDocument();
		});

		it('gives up on a /me recheck after 10 s without leaving, so the next poll can ask again', async () => {
			vi.useFakeTimers();
			// OLD CODE: const timeouts = timeoutsOnFakeClock(); (NET-361: the ping calls AbortSignal.timeout too, so the spy can't tell them apart)
			timeoutsOnFakeClock();
			const f = stubFetch(signInFirst, untilAborted);
			renderLayout();
			await vi.advanceTimersByTimeAsync(0);
			expect(meCalls(f)).toBe(1);
			// OLD CODE: expect(timeouts).toHaveBeenCalledWith(10_000); (NET-361)
			const meSignal = (f.mock.calls.find(([u]) => u === '/api/auth/me')?.[1] as RequestInit | undefined)?.signal;
			await vi.advanceTimersByTimeAsync(9_999);
			expect(meSignal?.aborted).toBe(false);

			// OLD CODE: await vi.advanceTimersByTimeAsync(10_000); (NET-361: the first 9 999 ms ran above)
			await vi.advanceTimersByTimeAsync(1);
			expect(meSignal?.aborted).toBe(true);
			expect(goto).not.toHaveBeenCalled();
			await vi.advanceTimersByTimeAsync(20_000); // the 30 s poll isn't held up by the check that hung
			expect(meCalls(f)).toBe(2);
		});

		it('drops a /me refusal held across a fresh sign-in', async () => {
			vi.useFakeTimers();
			const me = deferred<Response>();
			let pings = 0;
			const f = stubFetch(() => (++pings === 1 ? signInFirst() : new Response(JSON.stringify({ status: 'ok' }))), () => me.promise);
			renderLayout();
			await vi.advanceTimersByTimeAsync(0);
			expect(meCalls(f)).toBe(1);

			pageStore.set({ url: new URL('http://localhost/login?next=%2Fsystem') }); // the sign-in page has no shell
			await vi.advanceTimersByTimeAsync(0);
			pageStore.set({ url: new URL('http://localhost/system') }); // signed in: the shell polls again
			await vi.advanceTimersByTimeAsync(0);
			expect(pings).toBe(2);
			me.resolve(meRefused());
			await vi.advanceTimersByTimeAsync(0);

			expect(goto).not.toHaveBeenCalled();
		});
	});

	// The stream closes for good on a 401; it must come back with the shell after sign-in
	it('opens a new notification stream when the shell mounts again after sign-in', async () => {
		stubFetch();
		let opened = 0;
		let closed = 0;
		vi.stubGlobal(
			'EventSource',
			class {
				constructor() {
					opened++;
				}
				addEventListener() {}
				close() {
					closed++;
				}
			},
		);
		renderLayout();
		await vi.waitFor(() => expect(opened).toBe(1));

		pageStore.set({ url: new URL('http://localhost/login?next=%2Fsystem') });
		await vi.waitFor(() => expect(closed).toBe(1));
		pageStore.set({ url: new URL('http://localhost/system') });

		await vi.waitFor(() => expect(opened).toBe(2));
	});
});

describe('layout sidebar', () => {
	it('marks the current page, including nested routes', async () => {
		pageStore.set({ url: new URL('http://localhost/devices/10.0.0.5') });
		renderLayout();
		const nav = screen.getByRole('navigation', { name: 'Main' });
		expect(within(nav).getByRole('link', { name: /^Devices/ })).toHaveAttribute('aria-current', 'page');
		expect(within(nav).getByRole('link', { name: /^Home/ })).not.toHaveAttribute('aria-current');
	});

	// OLD CODE START — NET-160: 17 links before Investigations and Security posture joined
	// it('keeps all 17 page links', () => { … expect(new Set(hrefs).size).toBe(17); });
	// OLD CODE END
	// OLD CODE START — NET-188: 19 links before Packet analysis joined
	// it('keeps all 19 page links', () => { … expect(new Set(hrefs).size).toBe(19); … });
	// OLD CODE END
	// OLD CODE START — NET-264: 20 links before Local services joined
	// it('keeps all 20 page links', () => { … expect(new Set(hrefs).size).toBe(20); … arrayContaining(['/investigations', '/compliance', '/packets']) … });
	// OLD CODE END
	// OLD CODE START — NET-340: 21 links before Reports joined
	// it('keeps all 21 page links', () => { … expect(new Set(hrefs).size).toBe(21); … arrayContaining(['/investigations', '/compliance', '/packets', '/local-services']) … });
	// OLD CODE END
	it('keeps all 22 page links', () => {
		renderLayout();
		const nav = screen.getByRole('navigation', { name: 'Main' });
		// the brand link also points home, so 23 links share 22 hrefs
		// OLD CODE: const hrefs = within(nav).getAllByRole('link').map((a) => a.getAttribute('href')); (NET-358: the foot's account link isn't a page link)
		const hrefs = within(nav).getAllByRole('link').filter((a) => !a.closest('.side-foot')).map((a) => a.getAttribute('href'));
		expect(new Set(hrefs).size).toBe(22);
		expect(hrefs).toEqual(expect.arrayContaining(['/investigations', '/compliance', '/packets', '/local-services', '/reports']));
	});

	it('shows the storage used and free space', async () => {
		vi.mocked(systemApi.getStorageStatus).mockResolvedValue({
			disk_usage_percent: 41.2,
			disk_total_bytes: 1e12,
			disk_used_bytes: 4.12e11,
			disk_free_bytes: 5.88e11,
			retention: { hot_days: 90 },
		} as systemApi.StorageStatus);
		renderLayout();
		expect(await screen.findByText('41% used')).toBeInTheDocument();
		// OLD CODE: expect(screen.getByText(/90-day retention/)).toBeInTheDocument(); (NET-348)
		expect(screen.getByText(/90-day log and alert retention/)).toBeInTheDocument();
		expect(screen.getByRole('meter', { name: 'Disk used' })).toHaveAttribute('aria-valuenow', '41');
		// NET-348: the storage block opens the retention settings
		expect(screen.getByText('41% used').closest('a')).toHaveAttribute('href', '/settings?tab=retention');
	});

	it('hides storage when its request fails', async () => {
		vi.mocked(systemApi.getStorageStatus).mockRejectedValue(new Error('503'));
		renderLayout();
		await tick();
		await tick();
		expect(screen.queryByText(/% used/)).not.toBeInTheDocument();
	});

	it('shows the signed-in user and a sign-out button inside the logout form', () => {
		renderLayout('admin');
		expect(screen.getByText('admin')).toBeInTheDocument();
		// NET-358: the name opens the account settings, where the password is changed
		const name = within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'admin' });
		expect(name).toHaveAttribute('href', '/settings?tab=account');
		expect(name).toHaveAttribute('title', 'Account settings');
		const button = screen.getByRole('button', { name: 'Sign out' });
		const form = button.closest('form');
		expect(form).toHaveAttribute('method', 'POST');
		expect(form).toHaveAttribute('action', '/api/auth/logout');
		expect(button).toHaveAttribute('type', 'submit');
	});

	// NET-228 (audit HON-49): a failed count showed no badge, the same as zero
	it.each([
		['a failed count', () => Promise.reject(new Error('503')), '?', "Couldn't load the alert count"],
		['a count', () => Promise.resolve(counts(7)), '7', '7 alerts in the last 24 hours'],
	])('badges %s on Alerts', async (_what, fetcher, badge, spoken) => {
		_configure({ fetcher: fetcher as never });
		renderLayout();
		const alerts = within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: /^Alerts/ });
		await vi.waitFor(() => expect(within(alerts).getByText(spoken)).toBeInTheDocument());
		expect(within(alerts).getByText(badge)).toHaveClass('count');
	});

	it('shows no badge for zero alerts', async () => {
		_configure({ fetcher: (() => Promise.resolve(counts(0))) as never });
		renderLayout();
		await vi.waitFor(() => expect(get(alertSnapshots)[24]?.status).toBe('ok'));
		await tick();
		const alerts = within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: /^Alerts/ });
		expect(alerts.querySelector('.count')).toBeNull();
	});

	it('hides the user row without a username but keeps sign-out', () => {
		renderLayout(null);
		expect(screen.queryByText('admin')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
	});
});

describe('layout phone menu', () => {
	function openMenu() {
		const button = screen.getByRole('button', { name: 'Open menu' });
		return { button, done: fireEvent.click(button) };
	}

	it('opens the drawer and moves focus to the first link', async () => {
		const { container } = renderLayout();
		const { button, done } = openMenu();
		await done;
		await tick();
		expect(button).toHaveAttribute('aria-expanded', 'true');
		expect(button).toHaveAttribute('aria-controls', 'app-sidebar');
		expect(container.querySelector('.app')).toHaveClass('nav-open');
		const nav = screen.getByRole('navigation', { name: 'Main' });
		expect(nav.contains(document.activeElement)).toBe(true);
	});

	// NET-349: phones show the search field now, and ⌘K must not pull focus behind the open menu
	it('makes the page behind the open menu inert, and clears it before focus returns', async () => {
		const { container } = renderLayout();
		const { button, done } = openMenu();
		await done;
		await tick();
		// Svelte sets the inert property; browsers reflect it to the attribute, jsdom doesn't know it
		const main = container.querySelector<HTMLElement>('main#main')!;
		expect(main.inert).toBe(true);
		expect(main.contains(screen.getByRole('navigation', { name: 'Main' }))).toBe(false);
		await fireEvent.keyDown(window, { key: 'Escape' });
		await tick();
		expect(main.inert).toBe(false);
		expect(document.activeElement).toBe(button);
	});

	it('closes on Escape and returns focus to the menu button', async () => {
		const { container } = renderLayout();
		const { button, done } = openMenu();
		await done;
		await tick();
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(container.querySelector('.app')).not.toHaveClass('nav-open');
		expect(button).toHaveAttribute('aria-expanded', 'false');
		expect(document.activeElement).toBe(button);
	});

	it('closes when the scrim is clicked', async () => {
		const { container } = renderLayout();
		await openMenu().done;
		await fireEvent.click(screen.getByRole('button', { name: 'Close menu' }));
		expect(container.querySelector('.app')).not.toHaveClass('nav-open');
	});

	it('closes when a link is chosen', async () => {
		const { container } = renderLayout();
		await openMenu().done;
		const nav = screen.getByRole('navigation', { name: 'Main' });
		const link = within(nav).getByRole('link', { name: /^Alerts/ });
		link.addEventListener('click', (e) => e.preventDefault()); // jsdom can't navigate
		await fireEvent.click(link);
		expect(container.querySelector('.app')).not.toHaveClass('nav-open');
	});

	it('keeps Tab inside the open drawer', async () => {
		renderLayout();
		await openMenu().done;
		await tick();
		const nav = screen.getByRole('navigation', { name: 'Main' });
		const items = [...nav.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')];
		items[items.length - 1].focus();
		await fireEvent.keyDown(window, { key: 'Tab' });
		expect(document.activeElement).toBe(items[0]);
		await fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
		expect(document.activeElement).toBe(items[items.length - 1]);
	});
});

describe('layout without the shell', () => {
	it.each(['/login', '/setup'])('renders %s bare', (path) => {
		pageStore.set({ url: new URL(`http://localhost${path}`) });
		renderLayout(null);
		expect(screen.getByText('page body')).toBeInTheDocument();
		expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
		expect(captureApi.getCaptureHealth).not.toHaveBeenCalled();
	});
});
