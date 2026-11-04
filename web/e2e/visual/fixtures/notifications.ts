/** Fixtures for the notification hub (daemon/api/notifications_hub.py), reached through the web catch-all. */
import type { ChannelsResponse, DeliveryLogResponse, RulesResponse } from '../../../src/lib/api/notification-hub.ts';
import { DAY, HOUR, iso, MIN, type FixtureRoute } from './types.ts';

const CHANNELS_EMPTY = { channels: [], count: 0 } satisfies ChannelsResponse;
const CHANNELS = {
	channels: [
		{ id: 'fxchan01', type: 'discord', name: 'Home alerts', config: { name: 'Home alerts', webhook_url: 'https://hooks.example.com/discord/nettap' }, created_at: iso(14 * DAY) },
		{ id: 'fxchan02', type: 'email', name: 'Admin email', config: { name: 'Admin email', smtp_host: 'smtp.example.com', smtp_port: 587, from_address: 'nettap@example.com', recipients: 'admin@example.com' }, created_at: iso(9 * DAY) },
	],
	count: 2,
} satisfies ChannelsResponse;

const RULES_EMPTY = { rules: [], count: 0 } satisfies RulesResponse;
const RULES = {
	rules: [
		{ id: 'fxrule01', event_type: 'alert', channels: ['fxchan01', 'fxchan02'], min_severity: 2, created_at: iso(9 * DAY) },
		{ id: 'fxrule02', event_type: 'new_device', channels: ['fxchan01'], min_severity: 4, created_at: iso(9 * DAY) },
	],
	count: 2,
} satisfies RulesResponse;

const LOG_EMPTY = { log: [], count: 0 } satisfies DeliveryLogResponse;
const LOG = {
	log: [
		{ channel_id: 'fxchan01', channel_type: 'discord', title: '2 Malware & C2 alerts', severity: 1, success: true, timestamp: iso(6 * MIN) },
		{ channel_id: 'fxchan02', channel_type: 'email', title: '2 Malware & C2 alerts', severity: 1, success: false, timestamp: iso(6 * MIN) },
		{ channel_id: 'fxchan01', channel_type: 'discord', title: 'New device 192.168.1.80', severity: 4, success: true, timestamp: iso(5 * HOUR) },
	],
	count: 3,
} satisfies DeliveryLogResponse;

export const NOTIFICATION_ROUTES: FixtureRoute[] = [
	{ path: '/api/notifications/channels', method: 'GET', empty: CHANNELS_EMPTY, populated: CHANNELS },
	{ path: '/api/notifications/rules', method: 'GET', empty: RULES_EMPTY, populated: RULES },
	{ path: '/api/notifications/log', empty: LOG_EMPTY, populated: LOG },
];
