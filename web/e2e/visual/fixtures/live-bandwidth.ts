/**
 * Live bandwidth on both device pages (/api/live-bandwidth, NET-205). Empty is a watch that has
 * only just started (every slot unmeasured, so the card says Measuring…); populated is five
 * minutes of a download with one missed tick, which the chart draws as a gap. The opt-in switch
 * (/api/settings/live-bandwidth) is off in empty mode, its default, and on in populated mode;
 * LIVE_BANDWIDTH_OFF is the device card's reply while it is off (live-bandwidth.visual.ts).
 */
import type {
	LiveBandwidthSample,
	LiveBandwidthSetting,
	LiveBandwidthSupported,
	LiveBandwidthUnsupported,
} from '../../../src/lib/api/live-bandwidth.ts';
import { NOW, type FixtureRoute } from './types.ts';

const SLOTS = 150;
const STEP_MS = 2_000;

function slot(i: number, rate: [number, number] | null): LiveBandwidthSample {
	return {
		tick: 10_000 + i,
		t: NOW - (SLOTS - 1 - i) * STEP_MS,
		mono: 50_000 + i * 2,
		bracket_ms: rate ? 3.1 : null,
		down_bps: rate ? rate[0] : null,
		up_bps: rate ? rate[1] : null,
		reason: rate ? null : 'missed',
	};
}

// a download ramping to ~45 Mbit/s with a little upload, and one missed tick at slot 100
const POPULATED = Array.from({ length: SLOTS }, (_, i) =>
	slot(i, i === 100 ? null : [Math.round(4_000_000 + 41_000_000 * Math.sin((i / SLOTS) * Math.PI) ** 2), Math.round(600_000 + 200_000 * Math.cos(i / 9))]),
);
const EMPTY = Array.from({ length: SLOTS }, (_, i) => ({ ...slot(i, null), t: null, mono: null }));

const base = {
	supported: true,
	reason: null,
	mode: 'mirror',
	interface: 'enp4s0',
	key: { kind: 'mac', value: '02:00:5e:10:00:20' },
	layer: 'ethernet-payload',
	offloads: { gro: false, lro: false },
	interval_s: 2,
	measuring_since: NOW - SLOTS * STEP_MS,
} as const;

export const LIVE_BANDWIDTH_OFF = {
	supported: false,
	off: true,
	reason: 'Live bandwidth is off. Turn it on in Settings › Capture.',
	mode: 'mirror',
	interface: 'enp4s0',
	key: base.key,
} satisfies LiveBandwidthUnsupported;

const SETTING_OFF = {
	enabled: false,
	supported: true,
	reason: null,
	mode: 'mirror',
	cleanup: { state: 'idle', failed: {} },
} satisfies LiveBandwidthSetting;

export const LIVE_BANDWIDTH_ROUTES: FixtureRoute[] = [
	{ path: '/api/settings/live-bandwidth', method: 'GET', empty: SETTING_OFF, populated: { ...SETTING_OFF, enabled: true } satisfies LiveBandwidthSetting },
	{
		path: '/api/live-bandwidth',
		empty: {
			...base,
			measuring_since: NOW,
			latest: null,
			latest_age_s: null,
			last_valid_age_s: null,
			samples: EMPTY,
		} satisfies LiveBandwidthSupported,
		populated: {
			...base,
			latest: POPULATED[SLOTS - 1],
			latest_age_s: 0.4,
			last_valid_age_s: 0.4,
			samples: POPULATED,
		} satisfies LiveBandwidthSupported,
	},
];
