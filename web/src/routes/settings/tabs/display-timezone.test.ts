import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import DisplayTab from './DisplayTab.svelte';

// F4 (NET-329): Settings › Display's "Your time zone", saved on NetTap (/api/settings/timezone)

const WARNING = /^Changing the time zone starts a new count in that zone\. NetTap recounts every day it still has the raw data for/;

/** GET answers `owner` (or `get` status); PUT answers `put` */
function stubZone(owner: unknown, put: { status: number; body: unknown } = { status: 200, body: {} }, get = 200) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string, init?: RequestInit) => {
			if (url !== '/api/settings/timezone') return { ok: false, status: 404, json: async () => ({}) };
			if (init?.method === 'PUT') return { ok: put.status === 200, status: put.status, json: async () => put.body };
			return { ok: get === 200, status: get, json: async () => owner };
		}),
	);
}

const select = () => screen.getByLabelText('Your time zone') as HTMLSelectElement;

afterEach(() => vi.unstubAllGlobals());

describe('Settings › Display — your time zone', () => {
	it('shows the zone NetTap counts in, among every zone this browser knows and UTC', async () => {
		stubZone({ tz: 'Europe/London', set: true });
		render(DisplayTab);
		await vi.waitFor(() => expect(select().value).toBe('Europe/London'));
		const zones = [...select().options].map((o) => o.value);
		expect(zones).toEqual(expect.arrayContaining(['UTC', 'America/Los_Angeles', 'Europe/London']));
		expect(zones).toEqual([...zones].sort());
		expect(screen.queryByText(WARNING)).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Save time zone' })).toBeDisabled();
	});

	it('warns what a change does as soon as one is picked, and saves it with a PUT', async () => {
		stubZone({ tz: 'UTC', set: false }, { status: 200, body: { tz: 'America/Los_Angeles', set: true } });
		render(DisplayTab);
		await vi.waitFor(() => expect(select().value).toBe('UTC'));
		await fireEvent.change(select(), { target: { value: 'America/Los_Angeles' } });
		expect(screen.getByText(WARNING)).toBeInTheDocument();
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Save time zone' }));
		expect(await screen.findByText('NetTap counts days in America/Los_Angeles from now on.')).toBeInTheDocument();
		const put = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'PUT');
		expect(JSON.parse(String(put?.[1]?.body))).toEqual({ tz: 'America/Los_Angeles' });
		// saved: no warning and nothing unsaved
		expect(screen.queryByText(WARNING)).not.toBeInTheDocument();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it("gives the daemon's reason when it refuses, and keeps the pick unsaved", async () => {
		stubZone({ tz: 'UTC', set: false }, { status: 400, body: { error: "That isn't a time zone NetTap knows" } });
		render(DisplayTab);
		await vi.waitFor(() => expect(select().value).toBe('UTC'));
		await fireEvent.change(select(), { target: { value: 'Asia/Tokyo' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save time zone' }));
		expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't save the time zone: That isn't a time zone NetTap knows");
		expect(screen.getByText(WARNING)).toBeInTheDocument();
	});

	it('keeps a saved zone this browser does not list, so the select still shows it', async () => {
		stubZone({ tz: 'Etc/GMT+12', set: true });
		render(DisplayTab);
		await vi.waitFor(() => expect(select().value).toBe('Etc/GMT+12'));
	});

	it('says when the zone could not be loaded, with Try again', async () => {
		stubZone({}, undefined, 503);
		render(DisplayTab);
		expect(await screen.findByText("Couldn't load your time zone: the request failed.")).toBeInTheDocument();
		stubZone({ tz: 'UTC', set: false });
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await vi.waitFor(() => expect(select().value).toBe('UTC'));
	});
});
