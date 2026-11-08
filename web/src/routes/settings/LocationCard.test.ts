/**
 * Settings › Network › Network location: load, the WAN suggestion (fills, never saves), save with
 * the daemon's rules checked first, clear, and every failure said in words.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import LocationCard from './LocationCard.svelte';
import { getHomeLocation, saveHomeLocation, clearHomeLocation, lookupWanLocation } from '$lib/api/home-location';

vi.mock('$lib/api/home-location', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/home-location')>()),
	getHomeLocation: vi.fn(),
	saveHomeLocation: vi.fn(),
	clearHomeLocation: vi.fn(),
	lookupWanLocation: vi.fn(),
}));

const LONDON = { lat: 51.5074, lon: -0.1278, label: 'London' };

async function flush() {
	for (let i = 0; i < 4; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const values = () => [field('Name').value, field('Latitude').value, field('Longitude').value];

beforeEach(() => {
	vi.mocked(getHomeLocation).mockReset().mockResolvedValue(null);
	vi.mocked(saveHomeLocation).mockReset().mockImplementation(async (h) => h);
	vi.mocked(clearHomeLocation).mockReset().mockResolvedValue();
	vi.mocked(lookupWanLocation).mockReset().mockResolvedValue({ lat: 51.51, lon: -0.09, label: 'London, England, GB' });
});

describe('LocationCard', () => {
	it('loads the saved location into the form', async () => {
		vi.mocked(getHomeLocation).mockResolvedValue(LONDON);
		render(LocationCard);
		expect(screen.getByRole('status')).toHaveTextContent('Loading the network location');
		await flush();
		expect(values()).toEqual(['London', '51.5074', '-0.1278']);
		expect(screen.getByRole('button', { name: 'Clear' })).toBeInTheDocument();
	});

	it("can't be changed when the saved location couldn't be read", async () => {
		vi.mocked(getHomeLocation).mockRejectedValue(new Error('HTTP 503'));
		render(LocationCard);
		await flush();
		expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load the network location, so changes are off.");
		expect(screen.queryByRole('button', { name: 'Save location' })).toBeNull();
	});

	it('the WAN lookup fills the fields and saves nothing', async () => {
		render(LocationCard);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Use my WAN location' }));
		await flush();
		expect(values()).toEqual(['London, England, GB', '51.51', '-0.09']);
		expect(screen.getByRole('status')).toHaveTextContent('Found London, England, GB from your internet address. Save to keep it.');
		expect(saveHomeLocation).not.toHaveBeenCalled();
	});

	it("says when the WAN lookup failed, in the daemon's words", async () => {
		vi.mocked(lookupWanLocation).mockRejectedValue(new Error("Couldn't look up your WAN location. Enter the coordinates by hand."));
		render(LocationCard);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Use my WAN location' }));
		await flush();
		expect(screen.getByRole('alert')).toHaveTextContent('Enter the coordinates by hand.');
	});

	it('checks the coordinates before sending, then saves', async () => {
		render(LocationCard);
		await flush();
		await fireEvent.input(field('Latitude'), { target: { value: '95' } });
		await fireEvent.input(field('Longitude'), { target: { value: '0' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save location' }));
		expect(screen.getByRole('alert')).toHaveTextContent('Latitude must be a number from -90 to 90.');
		expect(saveHomeLocation).not.toHaveBeenCalled();

		await fireEvent.input(field('Name'), { target: { value: ' Home ' } });
		await fireEvent.input(field('Latitude'), { target: { value: '51.5' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save location' }));
		await flush();
		expect(saveHomeLocation).toHaveBeenCalledWith({ lat: 51.5, lon: 0, label: 'Home' });
		expect(screen.getByRole('status')).toHaveTextContent('Location saved.');
	});

	it("shows the daemon's reason when a save is refused", async () => {
		vi.mocked(saveHomeLocation).mockRejectedValue(new Error("'label' must not contain control characters"));
		render(LocationCard);
		await flush();
		await fireEvent.input(field('Latitude'), { target: { value: '1' } });
		await fireEvent.input(field('Longitude'), { target: { value: '1' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save location' }));
		await flush();
		expect(screen.getByRole('alert')).toHaveTextContent("'label' must not contain control characters");
	});

	it('clears the location and empties the form', async () => {
		vi.mocked(getHomeLocation).mockResolvedValue(LONDON);
		render(LocationCard);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
		await flush();
		expect(clearHomeLocation).toHaveBeenCalled();
		expect(values()).toEqual(['', '', '']);
		expect(screen.getByRole('status')).toHaveTextContent('Location cleared.');
		expect(screen.queryByRole('button', { name: 'Clear' })).toBeNull();
	});
});
