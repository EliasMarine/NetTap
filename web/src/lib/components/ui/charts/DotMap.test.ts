import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import DotMap, { type Hotspot } from './DotMap.svelte';

// A 20° square of "land" around 0,0 stands in for the countries file
const SQUARE = {
	type: 'FeatureCollection',
	features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[-10, -10], [10, -10], [10, 10], [-10, 10], [-10, -10]]] } }],
};

// Live's geo_arcs are per city: two US cities must become one hotspot
const HOTSPOTS: Hotspot[] = [
	{ country: 'United States', code: 'US', lat: 37.4, lng: -122.1, count: 120 },
	{ country: 'United States', code: 'US', lat: 39, lng: -77.5, count: 30 },
	{ country: 'Germany', code: 'DE', lat: 50.1, lng: 8.7, count: 40 },
	{ country: 'Japan', code: 'JP', lat: 35.7, lng: 139.7, count: 1 },
];

function draw(extra: Record<string, unknown> = {}) {
	return render(DotMap, { props: { hotspots: HOTSPOTS, home: null, ariaLabel: 'Map of 191 active connections', ...extra } });
}

beforeEach(() => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => SQUARE }));
});
afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('DotMap', () => {
	it('lays land dots from the bundled countries file once on mount', async () => {
		const { container } = draw();
		await vi.waitFor(() => expect(container.querySelectorAll('.land circle').length).toBeGreaterThan(0));
		expect(fetch).toHaveBeenCalledTimes(1);
		expect(fetch).toHaveBeenCalledWith('/geo/countries-110m.geojson');
		expect(container.querySelectorAll('.land circle').length).toBeLessThan(100);
		expect(container.innerHTML).not.toMatch(/NaN/);
	});

	it('is a single image with no buttons when nothing can be selected', () => {
		const { getByRole, queryAllByRole } = draw();
		expect(getByRole('img').getAttribute('aria-label')).toBe('Map of 191 active connections');
		expect(queryAllByRole('button')).toHaveLength(0);
	});

	it('draws one hotspot per country, sized by share, with labels for the busiest', () => {
		const { container } = draw();
		const cores = [...container.querySelectorAll('circle.hot-core')].map((c) => Number(c.getAttribute('r')));
		expect(cores).toHaveLength(3);
		expect(cores[0]).toBeGreaterThan(cores[1]);
		expect(cores[1]).toBeGreaterThan(cores[2]);
		const labels = [...container.querySelectorAll('text.map-lbl')].map((t) => t.textContent);
		expect(labels).toEqual(['United States 150', 'Germany 40', 'Japan 1']);
		const tips = [...container.querySelectorAll('g > title')].map((t) => t.textContent);
		expect(tips).toEqual(['United States, 150 connections', 'Germany, 40 connections', 'Japan, 1 connection']);
	});

	it('draws no home ring and no arcs when home is null', () => {
		const { container } = draw();
		expect(container.querySelector('.home-ring')).toBeNull();
		expect(container.querySelector('.arc')).toBeNull();
		expect(container.textContent).not.toContain('Your network');
	});

	it('draws the home ring and an arc to each top destination when home is real', () => {
		const { container } = draw({ home: { lat: 51.5, lng: -0.1 } });
		expect(container.querySelector('.home-ring')).not.toBeNull();
		expect(container.querySelectorAll('path.arc')).toHaveLength(3);
		expect(container.textContent).toContain('Your network');
	});

	describe('selection', () => {
		it('labels each hotspot button inside a labelled group', () => {
			const { getByRole } = draw({ onselect: vi.fn() });
			expect(getByRole('group').getAttribute('aria-label')).toBe('Map of 191 active connections');
			const us = getByRole('button', { name: 'United States, 150 connections' });
			expect(us.getAttribute('tabindex')).toBe('0');
			expect(us.getAttribute('aria-pressed')).toBe('false');
			expect(getByRole('button', { name: 'Japan, 1 connection' })).toBeTruthy();
		});

		it('calls onselect with the country code on click, Enter and Space', async () => {
			const onselect = vi.fn();
			const { getByRole } = draw({ onselect });
			const de = getByRole('button', { name: /Germany/ });
			await fireEvent.click(de);
			await fireEvent.keyDown(de, { key: 'Enter' });
			const space = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
			de.dispatchEvent(space);
			expect(space.defaultPrevented).toBe(true);
			await fireEvent.keyDown(de, { key: 'a' });
			expect(onselect.mock.calls).toEqual([['DE'], ['DE'], ['DE']]);
		});

		it('shows the selected country pressed with a ring, and toggles off when the parent clears it', async () => {
			let selected: string | undefined = 'US';
			const onselect = vi.fn((code: string) => {
				selected = selected === code ? undefined : code; // Live's setCountryFilter toggle
			});
			const { getByRole, container, rerender } = draw({ onselect, selected });
			expect(getByRole('button', { name: /United States/ }).getAttribute('aria-pressed')).toBe('true');
			expect(container.querySelectorAll('.hot-sel')).toHaveLength(1);

			await fireEvent.click(getByRole('button', { name: /United States/ }));
			await rerender({ selected });
			expect(getByRole('button', { name: /United States/ }).getAttribute('aria-pressed')).toBe('false');
			expect(container.querySelector('.hot-sel')).toBeNull();

			await fireEvent.click(getByRole('button', { name: /Japan/ }));
			await rerender({ selected });
			expect(getByRole('button', { name: /Japan/ }).getAttribute('aria-pressed')).toBe('true');
		});

		it('falls back to the country name when a hotspot has no code', async () => {
			const onselect = vi.fn();
			const { getByRole } = draw({ onselect, hotspots: [{ country: 'Atlantis', lat: 0, lng: 0, count: 3 }] });
			await fireEvent.click(getByRole('button', { name: /Atlantis/ }));
			expect(onselect).toHaveBeenCalledWith('Atlantis');
		});
	});

	it('still draws the hotspots on a blank map when the countries file fails', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		for (const failure of [vi.fn().mockRejectedValue(new Error('offline')), vi.fn().mockResolvedValue({ ok: false, status: 404 })]) {
			vi.stubGlobal('fetch', failure);
			const { container, unmount } = draw();
			await vi.waitFor(() => expect(warn).toHaveBeenCalled());
			expect(container.querySelectorAll('.land circle')).toHaveLength(0);
			expect(container.querySelectorAll('circle.hot-core')).toHaveLength(3);
			warn.mockClear();
			unmount();
		}
	});

	it('skips hotspots without a usable location or count', () => {
		const { container } = draw({
			hotspots: [
				{ country: 'Nowhere', lat: Number.NaN, lng: 0, count: 5 },
				{ country: 'Empty', lat: 0, lng: 0, count: 0 },
			],
		});
		expect(container.querySelectorAll('circle.hot-core')).toHaveLength(0);
		expect(container.innerHTML).not.toMatch(/NaN/);
	});
});
