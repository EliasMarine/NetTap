/**
 * Settings › Capture › Live bandwidth (NET-205): the switch shows only the daemon's answer, works
 * in every capture mode, and the card follows the counters' clean-up after a turn-off.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import LiveBandwidthCard from './LiveBandwidthCard.svelte';
import { getLiveBandwidthSetting, setLiveBandwidthSetting, LiveBandwidthError, type LiveBandwidthSetting } from '$lib/api/live-bandwidth';

vi.mock('$lib/api/live-bandwidth', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/live-bandwidth')>()),
	getLiveBandwidthSetting: vi.fn(),
	setLiveBandwidthSetting: vi.fn(),
}));

const get = vi.mocked(getLiveBandwidthSetting);
const set = vi.mocked(setLiveBandwidthSetting);

function setting(over: Partial<LiveBandwidthSetting> = {}, cleanup: Partial<LiveBandwidthSetting['cleanup']> = {}): LiveBandwidthSetting {
	return { enabled: false, supported: true, reason: null, mode: 'mirror', ...over, cleanup: { state: 'idle', failed: {}, ...cleanup } };
}

/** Lets the mocked promises settle and the card render (no timer moves). */
async function flush() {
	for (let i = 0; i < 6; i++) await Promise.resolve();
	await tick();
}

async function wait(ms: number) {
	await vi.advanceTimersByTimeAsync(ms);
	await flush();
}

const toggle = () => screen.getByRole('switch', { name: 'Live bandwidth on device pages' }) as HTMLInputElement;
const stateLine = () => document.querySelector('.state-line')?.textContent;

beforeEach(() => {
	vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
	get.mockReset().mockResolvedValue(setting());
	set.mockReset();
});

afterEach(() => vi.useRealTimers());

describe('LiveBandwidthCard (Settings)', () => {
	it('shows a loading card while the setting loads', async () => {
		get.mockReturnValue(new Promise(() => {}));
		render(LiveBandwidthCard);
		await flush();
		expect(screen.getByText('Loading the live bandwidth setting').closest('[role="status"]')).toHaveAttribute('aria-busy', 'true');
		expect(screen.queryByRole('switch')).not.toBeInTheDocument();
	});

	it('shows an error with no switch when the setting can’t be read, and Try again asks again', async () => {
		get.mockRejectedValueOnce(new LiveBandwidthError('HTTP 502', 502));
		render(LiveBandwidthCard);
		await flush();
		expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load the live bandwidth setting, so changes are off.");
		expect(screen.queryByRole('switch')).not.toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await flush();
		expect(toggle()).not.toBeChecked();
	});

	it('shows on, with the cost note', async () => {
		get.mockResolvedValue(setting({ enabled: true }));
		render(LiveBandwidthCard);
		await flush();
		expect(toggle()).toBeChecked();
		expect(stateLine()).toBe('On — measures while a device page is open');
		expect(document.getElementById('live-bandwidth-help')).toHaveTextContent(/about 7% of one CPU core.*nothing runs while no device page is open.*dropped up to about 90 packets a minute/);
		expect(toggle()).toHaveAttribute('aria-describedby', 'live-bandwidth-help');
	});

	it('shows off, and turning it on follows the answer, not the click', async () => {
		let answer!: (s: LiveBandwidthSetting) => void;
		set.mockReturnValue(new Promise((r) => (answer = r)));
		render(LiveBandwidthCard);
		await flush();
		expect(toggle()).not.toBeChecked();
		expect(stateLine()).toBe('Off');

		await fireEvent.click(toggle());
		expect(set).toHaveBeenCalledWith(true);
		expect(toggle()).not.toBeChecked();
		expect(toggle()).toBeDisabled();

		answer(setting({ enabled: true }));
		await flush();
		expect(toggle()).toBeChecked();
		expect(toggle()).toBeEnabled();
		expect(stateLine()).toBe('On — measures while a device page is open');
	});

	it('can still be turned off where it can’t measure, and says why', async () => {
		const reason = "In bridge mode NetTap sees only your router's public address, so it can't split the rate by device.";
		get.mockResolvedValue(setting({ enabled: true, supported: false, reason, mode: 'bridge' }));
		set.mockResolvedValue(setting({ enabled: false, supported: false, reason, mode: 'bridge' }));
		render(LiveBandwidthCard);
		await flush();
		expect(screen.getByText(reason, { exact: false })).toHaveTextContent(`${reason} The setting takes effect in mirror mode.`);
		expect(toggle()).toBeEnabled();

		await fireEvent.click(toggle());
		await flush();
		expect(set).toHaveBeenCalledWith(false);
		expect(toggle()).not.toBeChecked();
	});

	it('keeps the unchanged value a failed save reports, and says why', async () => {
		get.mockResolvedValue(setting({ enabled: true }));
		set.mockRejectedValue(new LiveBandwidthError("Couldn't save the setting: disk full.", 500, true));
		render(LiveBandwidthCard);
		await flush();
		await fireEvent.click(toggle());
		await flush();
		expect(toggle()).toBeChecked();
		expect(screen.getByRole('alert')).toHaveTextContent("Couldn't save the setting: disk full.");
		expect(get).toHaveBeenCalledTimes(1);
	});

	it('asks for the setting again when a save got no answer about it', async () => {
		set.mockRejectedValue(new TypeError('Failed to fetch'));
		render(LiveBandwidthCard);
		await flush();
		get.mockResolvedValue(setting({ enabled: true })); // the save did land
		await fireEvent.click(toggle());
		await flush();
		expect(get).toHaveBeenCalledTimes(2);
		expect(toggle()).toBeChecked();
		expect(screen.getByRole('alert')).toHaveTextContent("Couldn't save the setting: the request failed.");
	});

	it('follows the clean-up after a turn-off until it is done, backing off after a failed check', async () => {
		const busy = 'RTNETLINK answers: Device or resource busy';
		get.mockResolvedValue(setting({ enabled: true }));
		set.mockResolvedValue(setting({}, { state: 'running' }));
		render(LiveBandwidthCard);
		await flush();

		await fireEvent.click(toggle());
		await flush();
		expect(toggle()).not.toBeChecked();
		expect(stateLine()).toBe('Removing the counters…');

		get.mockResolvedValueOnce(setting({}, { state: 'retrying', failed: { enp4s0: busy } }));
		await wait(2000);
		expect(get).toHaveBeenCalledTimes(2);
		expect(stateLine()).toBe(`Couldn't remove the counters on enp4s0: ${busy}; retrying`);

		get.mockRejectedValueOnce(new TypeError('Failed to fetch'));
		await wait(2000);
		expect(get).toHaveBeenCalledTimes(3);
		expect(screen.getByText("Couldn't check the clean-up; retrying")).toBeInTheDocument();
		expect(stateLine()).toBe(`Couldn't remove the counters on enp4s0: ${busy}; retrying`);

		get.mockResolvedValueOnce(setting());
		await wait(9999);
		expect(get).toHaveBeenCalledTimes(3); // 10 s after a failed check
		await wait(1);
		expect(get).toHaveBeenCalledTimes(4);
		expect(stateLine()).toBe('Off');
		expect(screen.queryByText("Couldn't check the clean-up; retrying")).not.toBeInTheDocument();

		await wait(60_000);
		expect(get).toHaveBeenCalledTimes(4);
	});

	it('stops following the clean-up on unmount', async () => {
		get.mockResolvedValue(setting({}, { state: 'running' }));
		const { unmount } = render(LiveBandwidthCard);
		await flush();
		expect(stateLine()).toBe('Removing the counters…');
		await wait(2000);
		expect(get).toHaveBeenCalledTimes(2);

		unmount();
		await wait(60_000);
		expect(get).toHaveBeenCalledTimes(2);
	});

	it('drops a clean-up check that a save overtook', async () => {
		let late!: (s: LiveBandwidthSetting) => void;
		get.mockResolvedValueOnce(setting({}, { state: 'running' }));
		render(LiveBandwidthCard);
		await flush();
		get.mockReturnValueOnce(new Promise((r) => (late = r)));
		await wait(2000); // the check is on its way
		set.mockResolvedValue(setting({ enabled: true }));
		await fireEvent.click(toggle());
		await flush();
		expect(toggle()).toBeChecked();

		late(setting({}, { state: 'running' }));
		await flush();
		expect(toggle()).toBeChecked();
		expect(stateLine()).toBe('On — measures while a device page is open');
	});
});
