import type { BridgeConfigResponse } from '../../../src/routes/api/setup/bridge/+server.ts';
import type { NicsResponse } from '../../../src/routes/api/setup/nics/+server.ts';
import type { FixtureRoute } from './types.ts';

/**
 * The machine always has its cards, so `empty` is the same list: the wizard's own first step
 * (two bridgeable ports plus a management port). The web route passes the daemon body through.
 */
const NICS = {
	interfaces: [
		{ name: 'enp1s0', mac: '02:00:5e:10:00:01', state: 'up', speed: '2500Mb/s', driver: 'igc', type: 'ethernet' },
		{ name: 'enp2s0', mac: '02:00:5e:10:00:02', state: 'up', speed: '2500Mb/s', driver: 'igc', type: 'ethernet' },
		{
			name: 'enp3s0',
			mac: '02:00:5e:10:00:03',
			state: 'up',
			speed: '1000Mb/s',
			driver: 'r8169',
			ipv4: '192.168.1.50',
			type: 'ethernet',
		},
		{ name: 'lo', mac: '00:00:00:00:00:00', state: 'up', speed: '', driver: '', ipv4: '127.0.0.1', type: 'loopback' },
	],
	source: 'daemon',
} satisfies NicsResponse;

/** POST /api/setup/bridge/preview: the read-only check the wizard's Bridge step runs (NET-290 calls it before the first admin). */
const BRIDGE_PREVIEW = {
	config_preview: '# NetTap bridge preview\nBRIDGE_NAME=br0\nWAN_INTERFACE=enp1s0\nLAN_INTERFACE=enp2s0',
	wan: 'enp1s0',
	lan: 'enp2s0',
	bridge_name: 'br0',
	ready: true,
	warnings: [],
	source: 'daemon',
} satisfies BridgeConfigResponse;

// OLD CODE START — NET-290: only the card list was served; the wizard's bridge check and storage save had no fixture
// export const SETUP_ROUTES: FixtureRoute[] = [{ path: '/api/setup/nics', empty: NICS }];
// OLD CODE END
export const SETUP_ROUTES: FixtureRoute[] = [
	{ path: '/api/setup/nics', empty: NICS },
	{ path: '/api/setup/bridge/preview', method: 'POST', empty: BRIDGE_PREVIEW },
	// The daemon call behind the wizard's storage save (POST /api/setup/storage)
	{ path: '/api/storage/config', method: 'POST', empty: { saved: true, ilm_applied: true } },
];
