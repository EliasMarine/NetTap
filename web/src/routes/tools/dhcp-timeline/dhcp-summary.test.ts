import { describe, it, expect } from 'vitest';
import type { DhcpTransaction } from '$lib/api/dhcp-timeline';
import type { RegistryDevice } from '$lib/api/devices-registry';
import { readUrlState } from '$lib/utils/packet-query';
import { deviceName, leaseWords, messagesText, OUTCOME, packetsHref, pickedMac, soleServer, summary } from './dhcp-summary';

const A = '192.168.1.1';
const B = '192.168.1.5';
const MAC = '78:45:58:ed:b2:e9';

const tx = (fields: Partial<DhcpTransaction>): DhcpTransaction => ({
	ts: '2026-11-13T20:37:46.191000064Z',
	duration: 0.025,
	messages: { ACK: 1, REQUEST: 1 },
	requested_ip: null,
	assigned_ip: null,
	client_ip: null,
	lease_time: null,
	host_name: null,
	zeek_server: null,
	server_endpoints: [A],
	endpoints_complete: true,
	server_message: null,
	outcome: 'ack',
	...fields,
});

describe('summary', () => {
	it('names the one server endpoint as the sender, and an OFFER it also saw', () => {
		expect(summary(tx({ assigned_ip: '192.168.1.138' }))).toBe('ACK observed from 192.168.1.1 for 192.168.1.138.');
		expect(summary(tx({ assigned_ip: '192.168.1.138', messages: { ACK: 1, DISCOVER: 1, OFFER: 1, REQUEST: 1 } }))).toBe(
			'ACK observed from 192.168.1.1 for 192.168.1.138. OFFER also observed.',
		);
	});

	it('names no sender when the connections show two server endpoints', () => {
		expect(summary(tx({ assigned_ip: '192.168.1.138', server_endpoints: [A, B] }))).toBe(
			'ACK observed for 192.168.1.138. Server endpoints in this transaction: 192.168.1.1 and 192.168.1.5.',
		);
	});

	it('an OFFER from one server and a NAK from another: the NAK is named, its sender is not', () => {
		const t = tx({ messages: { DISCOVER: 1, NAK: 1, OFFER: 1, REQUEST: 1 }, assigned_ip: '192.168.1.50', server_endpoints: [A, B], outcome: 'nak' });
		expect(summary(t)).toBe('NAK observed. Server endpoints in this transaction: 192.168.1.1 and 192.168.1.5.');
		expect(soleServer(t)).toBeNull();
	});

	it('a NAK for the address the client renewed, with the server message', () => {
		const t = tx({ messages: { NAK: 1, REQUEST: 1 }, client_ip: '192.168.1.139', server_message: 'lease not found', outcome: 'nak' });
		expect(summary(t)).toBe('NAK observed from 192.168.1.1 for 192.168.1.139. Server message: “lease not found”.');
		expect(summary({ ...t, requested_ip: '192.168.1.20' })).toBe('NAK observed from 192.168.1.1 for 192.168.1.20. Server message: “lease not found”.');
	});

	it('mixed ACK and NAK lists the endpoints, even just one', () => {
		const t = tx({ messages: { ACK: 1, NAK: 1, REQUEST: 2 }, outcome: 'mixed' });
		expect(summary(t)).toBe('Both an ACK and a NAK were observed in this transaction. Server endpoint in this transaction: 192.168.1.1.');
		expect(summary({ ...t, server_endpoints: [A, B, '10.0.0.1'] })).toBe(
			'Both an ACK and a NAK were observed in this transaction. Server endpoints in this transaction: 192.168.1.1, 192.168.1.5 and 10.0.0.1.',
		);
	});

	it('an OFFER with no ACK or NAK, with one server and with several', () => {
		const t = tx({ messages: { DISCOVER: 1, OFFER: 1 }, assigned_ip: '192.168.1.50', outcome: 'offer_no_reply' });
		expect(summary(t)).toBe('OFFER of 192.168.1.50 observed from 192.168.1.1. No ACK or NAK observed.');
		expect(summary({ ...t, server_endpoints: [A, B] })).toBe(
			'OFFER of 192.168.1.50 observed. No ACK or NAK observed. Server endpoints in this transaction: 192.168.1.1 and 192.168.1.5.',
		);
	});

	it.each<[Partial<DhcpTransaction>, string]>([
		[{ messages: { DISCOVER: 3 }, server_endpoints: [], outcome: 'discover_no_offer' }, 'DISCOVER observed. No OFFER observed.'],
		[{ messages: { DECLINE: 1, DISCOVER: 1 }, server_endpoints: [], outcome: 'discover_no_offer' }, 'DISCOVER observed. No OFFER observed.'],
		[{ messages: { REQUEST: 1 }, requested_ip: '192.168.1.50', server_endpoints: [], outcome: 'request_no_reply' }, 'REQUEST for 192.168.1.50 observed. No reply observed.'],
		[{ messages: { RELEASE: 1 }, client_ip: '192.168.1.20', outcome: 'release' }, 'RELEASE observed for 192.168.1.20. Server endpoint in this transaction: 192.168.1.1.'],
		[{ messages: { DECLINE: 1 }, requested_ip: '192.168.1.60', server_endpoints: [], outcome: 'decline' }, 'DECLINE observed for 192.168.1.60.'],
		[{ messages: { INFORM: 1 }, client_ip: '192.168.1.30', server_endpoints: [], outcome: 'inform' }, 'INFORM observed from 192.168.1.30.'],
		[{ messages: { ACK: 1, INFORM: 1 }, client_ip: '192.168.1.30' }, 'ACK observed from 192.168.1.1.'],
		[{ messages: { LEASEQUERY: 2 }, server_endpoints: [], outcome: 'other' }, 'Messages observed: LEASEQUERY ×2.'],
		[{ messages: {}, server_endpoints: [], outcome: 'other' }, 'No message types were recorded.'],
	])('one observed-facts line per outcome (%o)', (fields, line) => {
		expect(summary(tx(fields))).toBe(line);
	});

	it('leaves out missing addresses and servers instead of writing "undefined"', () => {
		const lines = (['ack', 'nak', 'offer_no_reply', 'request_no_reply', 'release', 'decline', 'inform'] as const).map((outcome) =>
			summary(tx({ outcome, server_endpoints: [] })),
		);
		expect(lines).toEqual([
			'ACK observed.',
			'NAK observed.',
			'OFFER observed. No ACK or NAK observed.',
			'REQUEST observed. No reply observed.',
			'RELEASE observed.',
			'DECLINE observed.',
			'INFORM observed.',
		]);
		expect(lines.join(' ')).not.toMatch(/undefined|null/);
	});

	it('names no sender while a connection has no record, and says so', () => {
		expect(summary(tx({ assigned_ip: '192.168.1.138', endpoints_complete: false }))).toBe(
			'ACK observed for 192.168.1.138. Server endpoint in this transaction: 192.168.1.1. Not every connection in this transaction has been recorded yet.',
		);
	});
});

describe('messagesText', () => {
	it('is the multiset with counts, not an order', () => {
		expect(messagesText(tx({ messages: { ACK: 1, OFFER: 2, REQUEST: 1 } }))).toBe('ACK, OFFER ×2, REQUEST');
	});
});

describe('OUTCOME', () => {
	it('has a word for every outcome, with a coloured chip only where it says something', () => {
		expect(OUTCOME.ack).toEqual({ label: 'ACK', tone: 'ok' });
		expect(OUTCOME.nak.tone).toBe('bad');
		expect(OUTCOME.release.tone).toBeNull();
		expect([OUTCOME.offer_no_reply.label, OUTCOME.discover_no_offer.label, OUTCOME.request_no_reply.label]).toEqual(['No ACK or NAK seen', 'No OFFER seen', 'No reply seen']);
	});
});

describe('leaseWords', () => {
	it('writes whole hours and minutes short, anything else in seconds', () => {
		expect([leaseWords(86400), leaseWords(3600), leaseWords(1800), leaseWords(90), leaseWords(45)]).toEqual(['24 h', '1 h', '30 min', '90 s', '45 s']);
	});
});

describe('packetsHref', () => {
	// OLD CODE: it('links the packets only when the connections can not name a sender', … (PR #263 review: every row, to check a named sender)
	it('links the packets on every row, a named sender too, but not without a time', () => {
		expect(packetsHref(tx({}), MAC)).not.toBeNull();
		expect(packetsHref(tx({ server_endpoints: [A, B] }), MAC)).not.toBeNull();
		expect(packetsHref(tx({ endpoints_complete: false }), MAC)).not.toBeNull();
		expect(packetsHref(tx({ ts: 'not a time' }), MAC)).toBeNull();
	});

	it("filters the device's DHCP packets 5 s either side, in a window the packets page reads", () => {
		const href = packetsHref(tx({ server_endpoints: [A, B] }), MAC)!;
		const state = readUrlState(new URL(href, 'http://x').searchParams);
		expect(state).toMatchObject({ filter: `dhcp && dhcp.hw.mac_addr == ${MAC}`, from: '1794602261.191', to: '1794602271.216', limit: 100, device: null, conn: null });
	});

	it('takes a negative duration as none and keeps a long one within 30 minutes', () => {
		const state = (duration: number) => readUrlState(new URL(packetsHref(tx({ server_endpoints: [A, B], duration }), MAC)!, 'http://x').searchParams)!;
		expect(state(-0.0035).to).toBe('1794602271.191');
		expect(Number(state(7200).to) - Number(state(7200).from)).toBe(1800);
	});
});

const devices = [
	{ mac: '78:45:58:ED:B2:E9', ips: ['192.168.1.138'], display_name: 'Office AP' },
	{ mac: '2A:37:F4:D9:20:F5', ips: ['192.168.1.116'], display_name: 'Mac' },
] as RegistryDevice[];

describe('pickedMac', () => {
	it("takes a device's name or IP to its MAC, and anything else as typed", () => {
		expect(pickedMac(' office ap ', devices)).toBe(MAC);
		expect(pickedMac('192.168.1.116', devices)).toBe('2a:37:f4:d9:20:f5');
		expect(pickedMac('AA-BB-CC-DD-EE-FF', devices)).toBe('AA-BB-CC-DD-EE-FF');
	});
});

describe('deviceName', () => {
	it("is the registry's name, else the newest DHCP host name, else the MAC", () => {
		expect(deviceName(MAC, devices, [])).toBe('Office AP');
		expect(deviceName('02:00:00:00:00:01', devices, [tx({}), tx({ host_name: 'U6-LR' }), tx({ host_name: 'old' })])).toBe('U6-LR');
		expect(deviceName('02:00:00:00:00:01', [], [tx({})])).toBe('02:00:00:00:00:01');
	});
});
