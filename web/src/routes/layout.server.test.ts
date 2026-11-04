// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { load } from './+layout.server';

describe('root layout load', () => {
	type Event = Parameters<typeof load>[0];
	const run = (locals: App.Locals) => load({ locals } as Event);

	// toEqual fails on any extra key, so this also proves the role never reaches the page
	it('returns only the username for a signed-in user', () => {
		expect(run({ user: { username: 'admin', role: 'admin' } })).toEqual({ username: 'admin' });
	});

	it('returns null for an anonymous visitor (login, public tools, first run)', () => {
		expect(run({})).toEqual({ username: null });
	});
});
