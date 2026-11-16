import { describe, it, expect, vi, afterEach } from 'vitest';
import { getPostureDetail, isPostureDetail } from './posture';
import { POSTURE_DNS, POSTURE_DNS_EMPTY, POSTURE_ENCRYPTION, POSTURE_PATCH } from '../../../e2e/visual/fixtures/traffic';

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
