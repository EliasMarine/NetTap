import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonJSON } from '$lib/server/daemon.js';

export interface NetworkInterface {
	name: string;
	mac: string;
	state: 'up' | 'down' | 'unknown';
	speed: string;
	driver: string;
	ipv4?: string;
	type: 'ethernet' | 'wireless' | 'virtual' | 'loopback';
}

export interface NicsResponse {
	interfaces: NetworkInterface[];
	source: 'daemon' | 'mock';
}

/**
 * Mock NIC data for development / when the daemon is unreachable.
 * Provides a realistic set of interfaces matching the target hardware
 * (Intel N100 with dual i226-V 2.5GbE NICs).
 */
function getMockInterfaces(): NetworkInterface[] {
	return [
		{
			name: 'eth0',
			mac: 'a8:a1:59:c2:0e:01',
			state: 'up',
			speed: '2500Mb/s',
			driver: 'igc',
			type: 'ethernet',
		},
		{
			name: 'eth1',
			mac: 'a8:a1:59:c2:0e:02',
			state: 'up',
			speed: '2500Mb/s',
			driver: 'igc',
			type: 'ethernet',
		},
		{
			name: 'wlan0',
			mac: 'b4:6b:fc:d3:12:ab',
			state: 'up',
			speed: '867Mb/s',
			driver: 'iwlwifi',
			ipv4: '192.168.1.50',
			type: 'wireless',
		},
		{
			name: 'lo',
			mac: '00:00:00:00:00:00',
			state: 'up',
			speed: '',
			driver: '',
			ipv4: '127.0.0.1',
			type: 'loopback',
		},
	];
}

export const GET: RequestHandler = async () => {
	// Try the daemon first
	const { data, error } = await daemonJSON<NicsResponse>('/api/setup/nics');

	if (data && !error) {
		return json(data);
	}

	// Daemon unavailable or returned an error — fall back to mock data
	const response: NicsResponse = {
		interfaces: getMockInterfaces(),
		source: 'mock',
	};

	return json(response);
};
