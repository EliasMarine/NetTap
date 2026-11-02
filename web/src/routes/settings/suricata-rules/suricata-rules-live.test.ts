import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Page from './+page.svelte';

/** The page shows what Suricata really runs, and controls that are not wired up are off (#58). */

const LIVE = {
	available: true,
	enabled_rules: 64307,
	disabled_rules: 15954,
	last_updated: '2026-11-02T00:00:36+00:00',
	sources: [
		'https://rules.emergingthreats.net/open/suricata-%(__version__)s/emerging.rules.tar.gz',
		'https://sslbl.abuse.ch/blacklist/sslblacklist.rules',
	],
	schedule: '0 0 * * *',
	error: null,
};

function stubFetch(live: { status: number; body: unknown }) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			if (url === '/api/suricata/rules/live') {
				return { ok: live.status < 400, status: live.status, json: async () => live.body };
			}
			if (url === '/api/suricata/rules/sources') {
				return { ok: true, status: 200, json: async () => ({ sources: [], last_update: null }) };
			}
			return { ok: false, status: 500, json: async () => ({}) };
		}),
	);
}

describe('Suricata rules page — live status', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the real rule count, sources and schedule', async () => {
		stubFetch({ status: 200, body: LIVE });
		render(Page);

		expect(await screen.findByText('64,307')).toBeInTheDocument();
		expect(screen.getByText('Emerging Threats Open')).toBeInTheDocument();
		expect(screen.getByText('abuse.ch SSL Blacklist')).toBeInTheDocument();
		expect(screen.getByText('Rules refresh automatically every day at 00:00 UTC.')).toBeInTheDocument();
		expect(screen.queryByText('Active Sources')).not.toBeInTheDocument();
	});

	it('says it could not read Suricata instead of showing 0 rules', async () => {
		stubFetch({ status: 502, body: { available: false, error: 'Could not reach the Suricata container.' } });
		render(Page);

		expect(await screen.findByText(/Could not read Suricata's rules: Could not reach the Suricata container\./)).toBeInTheDocument();
		expect(screen.queryByText('Never')).not.toBeInTheDocument();
		expect(screen.getAllByText('--').length).toBe(3);
	});

	it('turns off the controls that do not reach Suricata', async () => {
		stubFetch({ status: 200, body: LIVE });
		render(Page);
		await screen.findByText('64,307');

		expect(screen.getByRole('button', { name: 'Save Custom Rules' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Add Commercial License' })).toBeDisabled();
		expect(screen.queryByRole('combobox', { name: /Auto-update interval/ })).not.toBeInTheDocument();
	});

	// #96: a failure showed an empty editor and "no license", as if nothing were saved
	it('says the custom rules and license status could not be loaded', async () => {
		stubFetch({ status: 200, body: LIVE });
		render(Page);
		await screen.findByText('64,307');

		expect(screen.getByText("Couldn't load the saved custom rules: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the commercial license status: the request failed.")).toBeInTheDocument();
	});

	it('shows the saved custom rules and license without a failure note when they load', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const replies: Record<string, unknown> = {
					'/api/suricata/rules/live': LIVE,
					'/api/suricata/rules/custom': { content: 'alert tcp any any -> any any (sid:9999001;)' },
					'/api/suricata/rules/commercial': { configured: false },
				};
				const body = replies[url];
				return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 500, json: async () => ({}) };
			}),
		);
		render(Page);
		await screen.findByText('64,307');

		expect(screen.getByDisplayValue('alert tcp any any -> any any (sid:9999001;)')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load/)).not.toBeInTheDocument();
	});
});
