import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import LiveBandwidthCard from './LiveBandwidthCard.svelte';
import type { LiveBandwidthKey, LiveBandwidthSample, LiveBandwidthSupported } from '$api/live-bandwidth';

// ---------------------------------------------------------------------------
// A fetch whose replies the test hands out one by one
// ---------------------------------------------------------------------------

interface Call {
	url: string;
	signal: AbortSignal;
	reply: (body: unknown, status?: number) => void;
}

let calls: Call[] = [];

function stubFetch() {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(
			(url: string, init: RequestInit) =>
				new Promise((resolve) => {
					calls = [
						...calls,
						{ url, signal: init.signal!, reply: (body, status = 200) => resolve({ ok: status < 400, status, json: async () => body }) },
					];
				}),
		),
	);
}

/** Lets the reply's promise chain and the render run (no timer moves). */
async function flush() {
	for (let i = 0; i < 10; i++) await Promise.resolve();
	await tick();
}

async function answer(body: unknown, status = 200) {
	calls.at(-1)!.reply(body, status);
	await flush();
}

async function wait(ms: number) {
	await vi.advanceTimersByTimeAsync(ms);
	await flush();
}

const NOW_MS = 1_762_560_000_000;

function samples(values: Array<[number, number] | null>): LiveBandwidthSample[] {
	const padded = [...Array(150 - values.length).fill(null), ...values];
	return padded.map((v, i) => ({
		tick: 1000 + i,
		t: v ? NOW_MS - (149 - i) * 2000 : null,
		mono: v ? 500 + i * 2 : null,
		bracket_ms: v ? 3 : null,
		down_bps: v ? v[0] : null,
		up_bps: v ? v[1] : null,
		reason: v ? null : 'missed',
	}));
}

function supported(over: Partial<LiveBandwidthSupported> = {}, latest: Partial<LiveBandwidthSupported['latest']> = {}): LiveBandwidthSupported {
	return {
		supported: true,
		reason: null,
		mode: 'mirror',
		interface: 'enp4s0',
		key: { kind: 'mac', value: 'aa:bb:cc:dd:ee:ff' },
		layer: 'ethernet-payload',
		offloads: { gro: false, lro: false },
		interval_s: 2,
		latest: { tick: 1149, t: NOW_MS, mono: 5000, bracket_ms: 0.4, down_bps: 12_345_678, up_bps: 789, reason: null, ...latest },
		latest_age_s: 0.5,
		last_valid_age_s: 0.5,
		measuring_since: NOW_MS - 20_000,
		samples: samples([[1_000_000, 500], [2_000_000, 600], [12_345_678, 789]]),
		...over,
	};
}

const MAC: LiveBandwidthKey = { mac: 'aa:bb:cc:dd:ee:ff' };
const IP: LiveBandwidthKey = { ip: '192.168.1.5' };
const figures = () => [...document.querySelectorAll('.stat-v')].map((n) => n.textContent);

let hidden = false;

beforeEach(() => {
	vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
	hidden = false;
	Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
	stubFetch();
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	// the prototype's getter comes back
	delete (document as { hidden?: boolean }).hidden;
});

describe('LiveBandwidthCard', () => {
	it('loads, then shows the live figures, the chart and what it counts', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		expect(screen.getByText('Loading live bandwidth')).toBeInTheDocument();
		expect(calls[0].url).toBe('/api/live-bandwidth?mac=aa%3Abb%3Acc%3Add%3Aee%3Aff');

		await answer(supported());
		expect(figures()).toEqual(['12.3 Mbit/s', '789 bit/s']);
		expect(screen.getByText('Live')).toBeInTheDocument();
		expect(screen.getByRole('img').getAttribute('aria-label')).toBe(
			'Download and upload over the last 5 minutes. Now 12.3 Mbit/s down and 789 bit/s up.',
		);
		expect(screen.getByText(/by hardware address/)).toHaveTextContent(
			"Everything this device sends and the traffic addressed to it, by hardware address aa:bb:cc:dd:ee:ff. Broadcast and multicast it receives aren't included.",
		);
		expect(screen.getByText(/Measured on/)).toHaveTextContent('Measured on enp4s0.');
		expect(screen.queryByText(/GRO is on/)).not.toBeInTheDocument();
	});

	it('draws a missing tick as a gap, not a line across it', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await answer(supported({ samples: samples([[1, 1], [2, 2], null, [3, 3], [4, 4]]) }));
		const line = document.querySelector('.line.ln-1')!.getAttribute('d')!;
		expect(line.match(/M/g)).toHaveLength(2);
	});

	it('says it counts by address on the IP page, and notes GRO', async () => {
		render(LiveBandwidthCard, { props: { key: IP } });
		await flush();
		expect(calls[0].url).toBe('/api/live-bandwidth?ip=192.168.1.5');
		await answer(supported({ offloads: { gro: true, lro: false } }));
		expect(screen.getByText(/Everything this address sends/)).toHaveTextContent('(IPv4 only)');
		expect(screen.getByText(/GRO is on/)).toHaveTextContent('figures may read about 3% low');
	});

	it('shows a measured zero as 0 bit/s, and no reading as a dash with its reason', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await answer(supported({}, { down_bps: 0, up_bps: 0 }));
		expect(figures()).toEqual(['0 bit/s', '0 bit/s']);

		await wait(2000);
		await answer(supported({ last_valid_age_s: 4 }, { down_bps: null, up_bps: null, reason: 'A counter went down' }));
		expect(figures()).toEqual(['—', '—']);
		expect(screen.getByText('A counter went down · last measured 4 s ago')).toBeInTheDocument();
		expect(screen.queryByText('Live')).not.toBeInTheDocument();
	});

	it('says Measuring… until there are two readings', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await answer(supported({ samples: samples([[5, 5]]) }));
		expect(screen.getByText('Measuring…')).toBeInTheDocument();
		expect(screen.queryByRole('img')).not.toBeInTheDocument();
	});

	it('shows the reason when the mode can’t split by device, and stops asking', async () => {
		const reason = "In bridge mode NetTap sits in front of your router and sees only its public address, so it can't split the rate by device.";
		render(LiveBandwidthCard, { props: { key: IP } });
		await flush();
		await answer({ supported: false, reason, mode: 'bridge', interface: 'br0', key: { kind: 'ip', value: '192.168.1.5' } });
		expect(screen.getByText(reason)).toBeInTheDocument();
		expect(screen.queryByRole('img')).not.toBeInTheDocument();
		await wait(10_000);
		expect(calls).toHaveLength(1);
		// …until the page is back in view: an interface that was down may be up again
		window.dispatchEvent(new Event('focus'));
		await flush();
		expect(calls).toHaveLength(2);
	});

	it('stops asking while signed out, and asks again when the page is back in view', async () => {
		render(LiveBandwidthCard, { props: { key: IP } });
		await flush();
		await answer({ error: 'Sign in first' }, 401);
		await wait(10_000);
		expect(calls).toHaveLength(1);
		window.dispatchEvent(new Event('focus'));
		await flush();
		expect(calls).toHaveLength(2);
		await answer(supported());
		expect(figures()).toEqual(['12.3 Mbit/s', '789 bit/s']);
	});

	it('shows a busy reply with Try again, which asks at once', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await answer({ error: 'Too many live views are open. Close one and try again.' }, 503);
		expect(screen.getByRole('alert')).toHaveTextContent('Too many live views are open. Close one and try again.');

		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await flush();
		expect(calls).toHaveLength(2);
		await answer(supported());
		expect(figures()).toEqual(['12.3 Mbit/s', '789 bit/s']);
	});

	it('shows a bad key’s reason and does not ask again', async () => {
		render(LiveBandwidthCard, { props: { key: IP } });
		await flush();
		await answer({ error: 'That address is not on your network.' }, 400);
		expect(screen.getByRole('alert')).toHaveTextContent('That address is not on your network.');
		expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
		await wait(10_000);
		expect(calls).toHaveLength(1);
	});

	it('says a server failure failed, with the daemon’s reason', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await answer({ error: 'tc failed' }, 500);
		expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load live bandwidth: the request failed.");
		expect(screen.getByRole('alert')).toHaveTextContent('tc failed');
	});

	it('never overlaps polls: a slow request delays the next', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await answer(supported());
		await wait(1999);
		expect(calls).toHaveLength(1);
		await wait(1);
		expect(calls).toHaveLength(2); // 2 s after the first settled

		await wait(10_000); // the second hangs
		expect(calls).toHaveLength(2);
		await answer(supported());
		await wait(2000);
		expect(calls).toHaveLength(3);
	});

	it('aborts the request and stops polling on unmount', async () => {
		const { unmount } = render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		const first = calls[0];
		unmount();
		expect(first.signal.aborted).toBe(true);
		first.reply(supported());
		await wait(10_000);
		expect(calls).toHaveLength(1);
	});

	it('pauses while the tab is hidden and asks at once when it shows', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		hidden = true;
		await answer(supported());
		await wait(10_000);
		expect(calls).toHaveLength(1);

		hidden = false;
		document.dispatchEvent(new Event('visibilitychange'));
		await flush();
		expect(calls).toHaveLength(2);
	});

	it('does not ask while hidden when the tab hides after a reply, with the next poll already timed', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await answer(supported());
		hidden = true;
		await wait(10_000);
		expect(calls).toHaveLength(1);
	});

	it('drops a late reply for the previous device', async () => {
		const { rerender } = render(LiveBandwidthCard, { props: { key: IP } });
		await flush();
		const old = calls[0];
		await rerender({ key: { ip: '192.168.1.6' } });
		await flush();
		expect(old.signal.aborted).toBe(true);
		expect(calls[1].url).toBe('/api/live-bandwidth?ip=192.168.1.6');

		old.reply(supported({}, { down_bps: 111_000_000, up_bps: 222_000_000 }));
		await flush();
		expect(screen.queryByText('111 Mbit/s')).not.toBeInTheDocument();
		expect(screen.getByText('Loading live bandwidth')).toBeInTheDocument();

		await answer(supported());
		expect(figures()).toEqual(['12.3 Mbit/s', '789 bit/s']);
	});

	it("clears the previous device's figures and chart when the device changes", async () => {
		const { rerender, container } = render(LiveBandwidthCard, { props: { key: IP } });
		await flush();
		await answer(supported());
		expect(figures()).toEqual(['12.3 Mbit/s', '789 bit/s']);

		await rerender({ key: { ip: '192.168.1.6' } });
		await flush();
		expect(screen.getByText('Loading live bandwidth')).toBeInTheDocument();
		expect(screen.queryByText('12.3 Mbit/s')).not.toBeInTheDocument();
		expect(container.querySelector('svg path.line')).toBeNull();
	});

	it('does not restart polling for a new key object with the same address', async () => {
		const { rerender } = render(LiveBandwidthCard, { props: { key: IP } });
		await flush();
		await rerender({ key: { ip: '192.168.1.5' } });
		await flush();
		expect(calls).toHaveLength(1);
		expect(calls[0].signal.aborted).toBe(false);
	});

	it('shows no headline for a reply already past its 5 s on arrival (4 s old after 3 s on the way)', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await wait(3000);
		await answer(supported({ latest_age_s: 4 }));
		expect(figures()).toEqual(['—', '—']);
		expect(screen.getByText(/^Not measured just now · last measured/)).toBeInTheDocument();
	});

	it('clears a shown figure at its deadline while the next request hangs', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await answer(supported({ latest_age_s: 0.5 })); // fresh until 4.5 s from the send
		expect(figures()).toEqual(['12.3 Mbit/s', '789 bit/s']);
		await wait(2000);
		expect(calls).toHaveLength(2); // and it never answers
		await wait(2499);
		expect(figures()).toEqual(['12.3 Mbit/s', '789 bit/s']);
		await wait(1);
		expect(figures()).toEqual(['—', '—']);
		expect(screen.getByText('Not measured just now · last measured 5 s ago')).toBeInTheDocument();
	});

	it('keeps the chart and says so when a later poll fails', async () => {
		render(LiveBandwidthCard, { props: { key: MAC } });
		await flush();
		await answer(supported());
		await wait(2000);
		await answer({ error: 'Live bandwidth is busy. Try again in a moment.' }, 503);
		expect(screen.getByText('Live bandwidth is busy. Try again in a moment.')).toBeInTheDocument();
		expect(screen.getByRole('img')).toBeInTheDocument();
		// it keeps asking: a busy daemon is usually free a moment later
		await wait(2000);
		expect(calls).toHaveLength(3);
	});

	describe('while live bandwidth is off in Settings', () => {
		const OFF = {
			supported: false,
			off: true,
			reason: 'Live bandwidth is off. Turn it on in Settings › Capture.',
			mode: 'mirror',
			interface: 'enp4s0',
			key: { kind: 'mac', value: 'aa:bb:cc:dd:ee:ff' },
		};
		const focus = async () => {
			window.dispatchEvent(new Event('focus'));
			await flush();
		};

		it('says so with a link to the switch, asks once and stops', async () => {
			render(LiveBandwidthCard, { props: { key: MAC } });
			await flush();
			await answer(OFF);
			expect(screen.getByRole('heading', { name: 'Live bandwidth is off' })).toBeInTheDocument();
			expect(screen.getByRole('link', { name: 'Open Settings › Capture' })).toHaveAttribute('href', '/settings?tab=capture');
			await wait(60_000);
			expect(calls).toHaveLength(1);
		});

		it('asks once more when the window gets focus or the page shows again, and stays stopped while still off', async () => {
			render(LiveBandwidthCard, { props: { key: MAC } });
			await flush();
			await answer(OFF);

			await focus();
			expect(calls).toHaveLength(2);
			await focus(); // a second event while that one is out asks nothing more
			expect(calls).toHaveLength(2);
			await answer(OFF);
			await wait(60_000);
			expect(calls).toHaveLength(2);

			document.dispatchEvent(new Event('visibilitychange'));
			await flush();
			expect(calls).toHaveLength(3);
			await answer(OFF);
			await wait(60_000);
			expect(calls).toHaveLength(3);
			expect(screen.getByText('Live bandwidth is off')).toBeInTheDocument();
		});

		it('polls again once it was turned on elsewhere', async () => {
			render(LiveBandwidthCard, { props: { key: MAC } });
			await flush();
			await answer(OFF);
			await focus();
			await answer(supported());
			expect(figures()).toEqual(['12.3 Mbit/s', '789 bit/s']);
			expect(screen.queryByText('Live bandwidth is off')).not.toBeInTheDocument();
			await wait(2000);
			expect(calls).toHaveLength(3);
		});

		it('keeps polling through a busy reply after the turn-on, and shows the rates when they come', async () => {
			render(LiveBandwidthCard, { props: { key: MAC } });
			await flush();
			await answer(OFF);
			await focus();
			await answer({ error: 'Removing earlier counters; trying again in a moment.' }, 503);
			expect(screen.getByRole('alert')).toHaveTextContent('Removing earlier counters; trying again in a moment.');

			await wait(2000); // no focus change needed
			expect(calls).toHaveLength(3);
			await answer(supported());
			expect(figures()).toEqual(['12.3 Mbit/s', '789 bit/s']);
		});

		it('stops listening for focus on unmount', async () => {
			const add = vi.spyOn(window, 'addEventListener');
			const remove = vi.spyOn(window, 'removeEventListener');
			const { unmount } = render(LiveBandwidthCard, { props: { key: MAC } });
			await flush();
			await answer(OFF);
			const listener = add.mock.calls.find(([type]) => type === 'focus')?.[1];
			expect(listener).toBeTypeOf('function');
			unmount();
			expect(remove).toHaveBeenCalledWith('focus', listener);
			add.mockRestore();
			remove.mockRestore();
		});
	});
});
