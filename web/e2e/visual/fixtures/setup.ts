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

export const SETUP_ROUTES: FixtureRoute[] = [{ path: '/api/setup/nics', empty: NICS }];
