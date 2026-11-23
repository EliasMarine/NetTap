/**
 * Settings › Account (NET-358): the change-password form. It checks only "all filled" and "new ones
 * match" before sending, shows the server's sentence on a refusal, clears Current alone on a 401, sends
 * one change at a time, holds the hub (`busy`) only while one is sent, and registers it with
 * password-change.ts so a late 401 can't send this browser to sign in.
 */
import { describe, it, expect, vi, beforeEach, afterEach, onTestFinished } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { trackPasswordChange } from '$lib/password-change';
import AccountTab from './AccountTab.svelte';

vi.mock('$app/state', () => ({ page: { data: { username: 'admin' } } }));
vi.mock('$lib/password-change', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/password-change')>();
	return { ...actual, trackPasswordChange: vi.fn(actual.trackPasswordChange) };
});

type Reply = { status: number; body: unknown };

/** A reply the test lets through when it chooses. */
function deferred() {
	let resolve: (reply: Reply) => void = () => {};
	const promise = new Promise<Reply>((r) => (resolve = r));
	return { promise, resolve };
}

function stubFetch(reply: Reply | Promise<Reply>) {
	const fn = vi.fn(async () => {
		const { status, body } = await reply;
		return { ok: status < 400, status, json: async () => body } as Response;
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const field = (label: string) => screen.getByLabelText(label, { exact: true }) as HTMLInputElement;
const button = () => screen.getByRole('button', { name: /^(Change password|Changing…)$/ });
const form = () => button().closest('form') as HTMLFormElement;

async function fill(current: string, password: string, confirm: string) {
	await fireEvent.input(field('Current password'), { target: { value: current } });
	await fireEvent.input(field('New password'), { target: { value: password } });
	await fireEvent.input(field('Confirm new password'), { target: { value: confirm } });
}

/** Render with a bound `busy`, recording every value the tab gives it. */
function renderTab() {
	const busy: boolean[] = [];
	let value = false;
	render(AccountTab, {
		props: {
			get busy() {
				return value;
			},
			set busy(v: boolean) {
				value = v;
				busy.push(v);
			},
		},
	});
	return { busy: () => value, seen: busy };
}

const SUCCESS = 'Password changed. Any other browser signed in to NetTap has to sign in again.';
const NO_ANSWER = "NetTap didn't answer, so the password may or may not have changed. If you're signed out, sign in with the new password.";

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

// Braces: a function returned from beforeEach is run as a cleanup hook, and mockClear returns the mock
beforeEach(() => {
	vi.mocked(trackPasswordChange).mockClear();
});
afterEach(() => {
	vi.unstubAllGlobals();
});

describe('AccountTab', () => {
	it('names the signed-in user, with the username read-only for password managers', () => {
		renderTab();
		expect(screen.getByRole('heading', { name: 'Password' })).toBeInTheDocument();
		expect(screen.getByText('Signed in as admin')).toBeInTheDocument();
		expect(field('Username')).toHaveValue('admin');
		expect(field('Username')).toHaveAttribute('readonly');
		expect(field('Username')).toHaveAttribute('autocomplete', 'username');
		expect(field('Current password')).toHaveAttribute('autocomplete', 'current-password');
		expect(field('New password')).toHaveAttribute('autocomplete', 'new-password');
		expect(field('Confirm new password')).toHaveAttribute('autocomplete', 'new-password');
		expect(field('New password')).toHaveAccessibleDescription('At least 8 characters, with an upper-case letter, a lower-case letter and a number.');
	});

	it('sends nothing while a field is empty', async () => {
		const fetchFn = stubFetch({ status: 200, body: { success: true } });
		renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', '');
		await fireEvent.submit(form());
		expect(screen.getByRole('alert')).toHaveTextContent('Enter your current password, then the new one twice.');
		expect(fetchFn).not.toHaveBeenCalled();
	});

	it("sends nothing when the new passwords don't match", async () => {
		const fetchFn = stubFetch({ status: 200, body: { success: true } });
		renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', 'New-Pass-2');
		await fireEvent.submit(form());
		expect(screen.getByRole('alert')).toHaveTextContent("The new passwords don't match.");
		expect(fetchFn).not.toHaveBeenCalled();
	});

	it('sends the current and new password, then clears the fields and says what changed', async () => {
		const fetchFn = stubFetch({ status: 200, body: { success: true } });
		renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', 'New-Pass-1');
		await fireEvent.submit(form());
		await flush();

		expect(fetchFn).toHaveBeenCalledWith('/api/account/password', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ current: 'Old-Pass-1', password: 'New-Pass-1' }),
			signal: expect.any(AbortSignal),
		});
		expect(screen.getByRole('status')).toHaveTextContent(SUCCESS);
		expect(screen.getByRole('status')).toHaveTextContent('Close NetTap tabs on other devices that still show Dashboards or Grafana.');
		expect([field('Current password').value, field('New password').value, field('Confirm new password').value]).toEqual(['', '', '']);
		expect(field('Username')).toHaveValue('admin');
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
	});

	it("shows the server's warning on its own line when the change isn't confirmed on disk", async () => {
		const warning = "Your new password is active. NetTap couldn't confirm it reached the disk: if the box loses power soon, the old password may work again.";
		stubFetch({ status: 200, body: { success: true, warning } });
		renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', 'New-Pass-1');
		await fireEvent.submit(form());
		await flush();

		const [ok, warn] = screen.getAllByRole('status');
		expect(ok).toHaveTextContent(SUCCESS);
		expect(ok).not.toHaveTextContent(warning);
		expect(warn).toHaveTextContent(warning);
		expect(warn).toHaveClass('notice', 'is-warn');
	});

	it("shows the server's sentence on a refusal and keeps what was typed", async () => {
		stubFetch({ status: 400, body: { error: 'Password must contain at least one number.' } });
		renderTab();
		await fill('Old-Pass-1', 'New-Password', 'New-Password');
		await fireEvent.submit(form());
		await flush();

		expect(screen.getByRole('alert')).toHaveTextContent('Password must contain at least one number.');
		expect([field('Current password').value, field('New password').value, field('Confirm new password').value]).toEqual([
			'Old-Pass-1',
			'New-Password',
			'New-Password',
		]);
		expect(screen.queryByText(SUCCESS)).not.toBeInTheDocument();
	});

	it('a wrong current password clears only Current password', async () => {
		stubFetch({ status: 401, body: { error: "Your current password isn't right." } });
		renderTab();
		await fill('Wrong-Pass-1', 'New-Pass-1', 'New-Pass-1');
		await fireEvent.submit(form());
		await flush();

		expect(screen.getByRole('alert')).toHaveTextContent("Your current password isn't right.");
		expect([field('Current password').value, field('New password').value, field('Confirm new password').value]).toEqual(['', 'New-Pass-1', 'New-Pass-1']);
	});

	it('says so when a refusal has no sentence, or NetTap does not answer', async () => {
		stubFetch({ status: 502, body: null });
		renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', 'New-Pass-1');
		await fireEvent.submit(form());
		await flush();
		expect(screen.getByRole('alert')).toHaveTextContent("Couldn't change the password: NetTap answered 502.");

		vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
		await fireEvent.submit(form());
		await flush();
		// the answer was lost, not the change: it may have gone through
		expect(screen.getByRole('alert')).toHaveTextContent(NO_ANSWER);
	});

	it('gives up on a request that never answers after 30 s, says the change may have gone through, and lets go of the hub', async () => {
		vi.useFakeTimers();
		onTestFinished(() => {
			vi.useRealTimers();
		});
		const timeouts = timeoutsOnFakeClock();
		// a request that never answers: it ends only when its signal aborts
		vi.stubGlobal(
			'fetch',
			vi.fn((_url: string, init: RequestInit) => new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(init.signal?.reason)))),
		);
		const tab = renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', 'New-Pass-1');
		await fireEvent.submit(form());
		await vi.advanceTimersByTimeAsync(29_999);
		expect(tab.busy()).toBe(true);
		expect(timeouts).toHaveBeenCalledWith(30_000);

		await vi.advanceTimersByTimeAsync(1);
		expect(screen.getByRole('alert')).toHaveTextContent(NO_ANSWER);
		expect(tab.busy()).toBe(false);
		expect(button()).toHaveTextContent('Change password');
	});

	it('holds the hub while the change is sent, with the button reading Changing…, and lets go once it lands', async () => {
		const reply = deferred();
		stubFetch(reply.promise);
		const tab = renderTab();
		expect(tab.busy()).toBe(false);
		await fill('Old-Pass-1', 'New-Pass-1', 'New-Pass-1');
		await fireEvent.submit(form());
		await flush();

		expect(tab.busy()).toBe(true);
		expect(button()).toHaveTextContent('Changing…');
		expect(button()).toBeDisabled();
		expect(field('Current password')).toHaveAttribute('readonly');

		reply.resolve({ status: 200, body: { success: true } });
		await flush();
		expect(tab.busy()).toBe(false);
		// false once on mount, then true while sent and false when it lands
		expect(tab.seen).toEqual([false, true, false]);
		expect(button()).toHaveTextContent('Change password');
		expect(button()).toBeEnabled();
		expect(field('Current password')).not.toHaveAttribute('readonly');
	});

	it('lets go of the hub after a refusal too', async () => {
		stubFetch({ status: 429, body: { error: 'Too many attempts. Try again in 60 seconds.' } });
		const tab = renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', 'New-Pass-1');
		await fireEvent.submit(form());
		await flush();
		expect(screen.getByRole('alert')).toHaveTextContent('Too many attempts. Try again in 60 seconds.');
		expect(tab.busy()).toBe(false);
	});

	it('a typed, unsent password does not hold the hub', async () => {
		const tab = renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', '');
		await flush();
		expect(tab.busy()).toBe(false);
		expect(tab.seen).not.toContain(true);
	});

	it('two rapid submissions send one request and show one result', async () => {
		const reply = deferred();
		const fetchFn = stubFetch(reply.promise);
		renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', 'New-Pass-1');
		await fireEvent.submit(form());
		await fireEvent.submit(form());
		reply.resolve({ status: 200, body: { success: true } });
		await flush();

		expect(fetchFn).toHaveBeenCalledTimes(1);
		expect(screen.getAllByRole('status')).toHaveLength(1);
		expect(screen.getByRole('status')).toHaveTextContent(SUCCESS);
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
	});

	it('registers the request with password-change.ts', async () => {
		stubFetch({ status: 200, body: { success: true } });
		renderTab();
		await fill('Old-Pass-1', 'New-Pass-1', 'New-Pass-1');
		await fireEvent.submit(form());
		await flush();

		expect(trackPasswordChange).toHaveBeenCalledTimes(1);
		const call = vi.mocked(trackPasswordChange).mock.calls[0];
		expect(call).toHaveLength(1);
		expect(call[0]).toBeInstanceOf(Promise);
	});
});
