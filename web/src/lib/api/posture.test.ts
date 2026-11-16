import { describe, it, expect, vi, afterEach } from 'vitest';
import { getIsolation, getPostureDetail, isIsolation, isPostureDetail } from './posture';
import { POSTURE_ALERT_RESPONSE, POSTURE_ALERT_RESPONSE_EMPTY, POSTURE_DNS, POSTURE_DNS_EMPTY, POSTURE_ENCRYPTION, POSTURE_PATCH } from '../../../e2e/visual/fixtures/traffic';

const WIN = { from: '2026-11-15T06:00:00.000Z', to: '2026-11-16T06:00:00.000Z' };

function stubFetch(status: number, body: unknown) {
	const fetchMock = vi.fn(async () => ({ ok: status >= 200 && status < 300, status, json: async () => body }));
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

describe('getPostureDetail', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('asks for the slug over exactly the window and returns the typed reply', async () => {
		const fetchMock = stubFetch(200, POSTURE_ENCRYPTION);
		const detail = await getPostureDetail('encryption', WIN);
		expect(fetchMock).toHaveBeenCalledWith('/api/posture/encryption?from=2026-11-15T06%3A00%3A00.000Z&to=2026-11-16T06%3A00%3A00.000Z');
		expect(detail.unencrypted.risky.telnet.count).toBe(10);
	});

	it('accepts each category\'s reply, including an empty one', async () => {
		stubFetch(200, POSTURE_DNS);
		expect((await getPostureDetail('dns-security', WIN)).plain_scope.public).toBe(1200);
		stubFetch(200, POSTURE_DNS_EMPTY);
		expect((await getPostureDetail('dns-security', WIN)).resolvers.plain).toEqual([]);
		stubFetch(200, POSTURE_PATCH);
		expect((await getPostureDetail('patch-currency', WIN)).protocols.map((p) => p.name)).toEqual(['http', 'telnet']);
	});

	it('throws the daemon\'s own reason on a failure', async () => {
		stubFetch(502, { error: 'The posture search was incomplete' });
		await expect(getPostureDetail('encryption', WIN)).rejects.toThrow('The posture search was incomplete');
	});

	it('throws on a malformed reply instead of reading it as zeros', async () => {
		stubFetch(200, { ...POSTURE_ENCRYPTION, eligible: '1000' });
		await expect(getPostureDetail('encryption', WIN)).rejects.toThrow('The posture reply was malformed');
		// another category's reply for this slug
		stubFetch(200, POSTURE_DNS);
		await expect(getPostureDetail('encryption', WIN)).rejects.toThrow('The posture reply was malformed');
	});
});

describe('isPostureDetail', () => {
	it('rejects a bad scope, a negative count and a half-filled upstream', () => {
		const resolver = POSTURE_DNS.resolvers.plain[0];
		const withResolver = (r: unknown) => ({ ...POSTURE_DNS, resolvers: { ...POSTURE_DNS.resolvers, plain: [r] } });
		expect(isPostureDetail('dns-security', withResolver(resolver))).toBe(true);
		expect(isPostureDetail('dns-security', withResolver({ ...resolver, scope: 'lan' }))).toBe(false);
		expect(isPostureDetail('dns-security', withResolver({ ...resolver, count: -1 }))).toBe(false);
		expect(isPostureDetail('dns-security', withResolver({ ...resolver, upstream: { dot: 1 } }))).toBe(false);
		expect(isPostureDetail('dns-security', withResolver({ ...resolver, upstream: undefined }))).toBe(true);
		expect(isPostureDetail('patch-currency', { ...POSTURE_PATCH, protocols: [{ name: 'http', count: 1 }] })).toBe(false);
	});
});

// NET-308: Alert response's input
describe('the alert-response reply', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('is accepted with no excluded_ips (alerts never leave addresses out), and refused when malformed', async () => {
		stubFetch(200, POSTURE_ALERT_RESPONSE);
		const reply = await getPostureDetail('alert-response', WIN);
		expect([reply.needing, reply.investigated, reply.groups[3].investigated]).toEqual([4, 1, true]);
		expect(isPostureDetail('alert-response', POSTURE_ALERT_RESPONSE_EMPTY)).toBe(true);
		expect(isPostureDetail('alert-response', { ...POSTURE_ALERT_RESPONSE, needing: -1 })).toBe(false);
		expect(isPostureDetail('alert-response', { ...POSTURE_ALERT_RESPONSE, groups: [{ rule: 3, count: 1, investigated: false }] })).toBe(false);
		expect(isPostureDetail('alert-response', { ...POSTURE_ALERT_RESPONSE, groups: [{ rule: null, count: 1, investigated: 'no' }] })).toBe(false);
		expect(isPostureDetail('alert-response', { ...POSTURE_ALERT_RESPONSE, groups: [{ rule: null, count: 1, investigated: false }] })).toBe(true);
		expect(isPostureDetail('alert-response', { ...POSTURE_ALERT_RESPONSE, investigations: { open_during: 1 } })).toBe(false);
		// review M2: more investigated than needing would score 250%, "Good", with a negative bar
		expect(isPostureDetail('alert-response', { ...POSTURE_ALERT_RESPONSE, needing: 4, investigated: 4 })).toBe(true);
		expect(isPostureDetail('alert-response', { ...POSTURE_ALERT_RESPONSE, needing: 2, investigated: 5 })).toBe(false);
		// the traffic details still need excluded_ips
		const { excluded_ips: _, ...noExcluded } = POSTURE_ENCRYPTION;
		expect(isPostureDetail('encryption', noExcluded)).toBe(false);
	});
});

// NET-308 R1-6: a malformed isolation reply throws, so the score reads Couldn't compute, never 100
describe('getIsolation', () => {
	afterEach(() => vi.unstubAllGlobals());

	const PAIR = {
		iot_device: { mac: '02:00:5e:10:00:50', name: 'Camera', ip: '192.168.1.50' },
		internal_target: { ip: '192.168.1.20', hostname: null },
		risk: 'high',
		connection_count: 4,
		ports: [80, 445],
		reached: true,
		reached_ports: [80],
		description: 'Camera can reach 192.168.1.20 via HTTP',
	};
	const GOOD = { segmentation_score: 85, segmentation_grade: 'B', pairs: [PAIR], recommendation: 'Consider a VLAN.' };

	it('asks over exactly the window and accepts a null or 0–100 score', async () => {
		const fetchMock = stubFetch(200, GOOD);
		expect((await getIsolation(WIN)).segmentation_score).toBe(85);
		expect(fetchMock).toHaveBeenCalledWith('/api/iot/network-isolation?from=2026-11-15T06%3A00%3A00.000Z&to=2026-11-16T06%3A00%3A00.000Z');
		for (const score of [null, 0, 100]) expect(isIsolation({ ...GOOD, segmentation_score: score })).toBe(true);
		expect(isIsolation({ ...GOOD, segmentation_score: null, segmentation_grade: null, pairs: [] })).toBe(true);
		expect(isIsolation({ ...GOOD, pairs: [{ ...PAIR, internal_target: { ip: '192.168.1.20', hostname: 'nas' } }] })).toBe(true);
	});

	it('throws on a malformed reply', async () => {
		const { segmentation_score: _s, ...noScore } = GOOD;
		const { pairs: _p, ...noPairs } = GOOD;
		const { recommendation: _r, ...noRecommendation } = GOOD;
		const { reached: _x, ...pairWithoutReached } = PAIR;
		const bad = [
			noScore,
			{ ...GOOD, segmentation_score: '85' },
			{ ...GOOD, segmentation_score: Number.NaN },
			{ ...GOOD, segmentation_score: Number.POSITIVE_INFINITY },
			{ ...GOOD, segmentation_score: 101 },
			{ ...GOOD, segmentation_score: -1 },
			noPairs,
			noRecommendation,
			{ ...GOOD, pairs: [pairWithoutReached] },
			{ ...GOOD, pairs: [{ ...PAIR, risk: 'severe' }] },
			{ ...GOOD, pairs: [{ ...PAIR, reached_ports: ['80'] }] },
			{ ...GOOD, pairs: [{ ...PAIR, iot_device: { mac: 'x', ip: 'y' } }] },
			{ ...GOOD, pairs: [{ ...PAIR, internal_target: { ip: '192.168.1.20', hostname: 7 } }] },
			{ ...GOOD, pairs: [{ ...PAIR, internal_target: { ip: '192.168.1.20' } }] },
		];
		for (const body of bad) {
			stubFetch(200, body);
			await expect(getIsolation(WIN), JSON.stringify(body)).rejects.toThrow('The isolation reply was malformed');
		}
	});

	it('passes a failed request on as a failure', async () => {
		stubFetch(502, {});
		await expect(getIsolation(WIN)).rejects.toThrow('Failed to load network isolation: 502');
	});
});
