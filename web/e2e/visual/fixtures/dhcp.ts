/** Fixtures for /api/dhcp/timeline (daemon/api/dhcp_timeline.py, NET-263), shaped like the G11's U6-LR records. */
import type { DhcpTimeline, DhcpTransaction } from '../../../src/lib/api/dhcp-timeline.ts';
import { DAY, HOUR, NOW, iso, type FixtureRoute } from './types.ts';

export const DHCP_MAC = '02:00:5e:00:53:38';

const tx = (msAgo: number, fields: Partial<DhcpTransaction>): DhcpTransaction => ({
	ts: iso(msAgo),
	duration: 0.0005,
	messages: { ACK: 1, REQUEST: 1 },
	requested_ip: null,
	assigned_ip: null,
	client_ip: null,
	lease_time: null,
	host_name: 'U6-LR',
	zeek_server: null,
	server_endpoints: ['192.168.1.1'],
	endpoints_complete: true,
	server_message: null,
	outcome: 'ack',
	...fields,
});

export const DHCP_TIMELINE = {
	mac: DHCP_MAC,
	from: iso(DAY),
	to: new Date(NOW).toISOString(),
	truncated: false,
	transactions: [
		tx(10 * 60_000, {
			messages: { ACK: 1, DISCOVER: 1, OFFER: 1, REQUEST: 1 },
			requested_ip: '192.168.1.138',
			assigned_ip: '192.168.1.138',
			client_ip: '192.168.1.138',
			lease_time: 86400,
			zeek_server: '192.168.1.1',
		}),
		tx(12 * 60_000, { assigned_ip: '192.168.40.140', client_ip: '192.168.40.140', lease_time: 86400, zeek_server: '192.168.40.1', server_endpoints: ['192.168.40.1'] }),
		tx(2 * HOUR, { messages: { NAK: 1, REQUEST: 1 }, client_ip: '192.168.1.139', server_message: 'lease not found', outcome: 'nak' }),
		// two servers answered: no sender named, a link to the packets
		tx(5 * HOUR, {
			messages: { DISCOVER: 1, NAK: 1, OFFER: 1, REQUEST: 1 },
			assigned_ip: '192.168.1.50',
			server_endpoints: ['192.168.1.1', '192.168.1.5'],
			outcome: 'nak',
		}),
		tx(9 * HOUR, { messages: { DISCOVER: 3 }, server_endpoints: [], outcome: 'discover_no_offer' }),
		tx(20 * HOUR, { messages: { REQUEST: 1 }, requested_ip: '192.168.1.50', server_endpoints: [], endpoints_complete: false, outcome: 'request_no_reply' }),
	],
} satisfies DhcpTimeline;

export const DHCP_TIMELINE_EMPTY = { ...DHCP_TIMELINE, transactions: [] } satisfies DhcpTimeline;

export const DHCP_ROUTES: FixtureRoute[] = [{ path: '/api/dhcp/timeline', empty: DHCP_TIMELINE_EMPTY, populated: DHCP_TIMELINE }];
