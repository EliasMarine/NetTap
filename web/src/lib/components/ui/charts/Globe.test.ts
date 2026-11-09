/**
 * Globe: the lifecycle around the three.js engine (mocked here; jsdom has no WebGPU or WebGL 2).
 * It must never leave a renderer running after unmount, and must hand over to the flat map once
 * when the renderer or the land outlines fail.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import Globe from './Globe.svelte';
import { mountGlobe } from './globe/engine.js';
import { loadLandMask } from './globe/land.js';
import type { GeoArc } from '$lib/api/live';

vi.mock('./globe/engine.js', () => ({ mountGlobe: vi.fn() }));
vi.mock('./globe/land.js', () => ({ loadLandMask: vi.fn() }));

type Opts = {
	onStatus: (s: { ready?: boolean; failed?: boolean; backend?: string; error?: string }) => void;
	onHover: (h: unknown) => void;
	onSelect: (code: string) => void;
};

function fakeEngine() {
	return {
		ingest: vi.fn(),
		setSelected: vi.fn(),
		setHome: vi.fn(),
		setPaused: vi.fn(),
		setReduced: vi.fn(),
		setExpanded: vi.fn(),
		highlight: vi.fn(),
		destroy: vi.fn(),
	};
}

const ARCS: GeoArc[] = [{ city: 'Amsterdam', country: 'Netherlands', country_code: 'NL', lat: 52.37, lon: 4.9, count: 4, bytes: 9000 }];
const HOME = { lat: 51.5, lon: -0.13, label: 'London' };

async function settle() {
	// the dynamic import of the engine resolves on a later task
	for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
	await tick();
}

/** Until the (mocked) engine has been made. */
const mounted = () => vi.waitFor(() => expect(mountGlobe).toHaveBeenCalled());

let engine: ReturnType<typeof fakeEngine>;
let opts: Opts;

beforeEach(() => {
	engine = fakeEngine();
	vi.mocked(mountGlobe).mockReset().mockImplementation((_canvas: unknown, o: Opts) => {
		opts = o;
		return engine;
	});
	vi.mocked(loadLandMask).mockReset().mockResolvedValue({ W: 1, H: 1 });
	vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => vi.restoreAllMocks());

const props = (extra = {}) => ({ arcs: ARCS, fresh: [], home: HOME, ariaLabel: 'Connections to 1 country', ...extra });

describe('Globe', () => {
	it('unmounted while the outlines load: no renderer is ever made', async () => {
		let release!: (v: unknown) => void;
		vi.mocked(loadLandMask).mockReturnValue(new Promise((r) => (release = r)));
		const view = render(Globe, props());
		view.unmount();
		release({ W: 1, H: 1 });
		await settle();
		expect(mountGlobe).not.toHaveBeenCalled();
	});

	it('primes the first snapshot, forwards prop changes, and destroys the engine once on unmount', async () => {
		const onready = vi.fn();
		const view = render(Globe, props({ onready }));
		await mounted();
		await tick();
		expect(mountGlobe).toHaveBeenCalledTimes(1);
		expect(engine.ingest).toHaveBeenCalledWith({ geo_arcs: ARCS, fresh: [] }, { prime: true });
		expect(screen.getByRole('status')).toHaveTextContent('Loading the globe…');

		opts.onStatus({ ready: true, backend: 'WebGL 2' });
		await tick();
		expect(onready).toHaveBeenCalledWith('WebGL 2');
		expect(screen.queryByRole('status')).toBeNull();

		const fresh = [{ dest_lat: 1, dest_lon: 2, direction: 'out', bytes: 10, has_alert: false }];
		await view.rerender(props({ fresh, selected: 'NL', paused: true, expanded: true }));
		expect(engine.ingest).toHaveBeenLastCalledWith({ geo_arcs: ARCS, fresh }, { prime: false });
		expect(engine.setSelected).toHaveBeenLastCalledWith('NL', { fly: true });
		expect(engine.setPaused).toHaveBeenLastCalledWith(true);
		expect(engine.setExpanded).toHaveBeenLastCalledWith(true);

		view.unmount();
		expect(engine.destroy).toHaveBeenCalledTimes(1);
	});

	it("a country picked on the canvas is selected without flying the camera to it", async () => {
		const onselect = vi.fn();
		const view = render(Globe, props({ onselect }));
		await mounted();
		await tick();
		opts.onSelect('NL');
		expect(onselect).toHaveBeenCalledWith('NL');
		await view.rerender(props({ onselect, selected: 'NL' }));
		expect(engine.setSelected).toHaveBeenLastCalledWith('NL', { fly: false });
	});

	it('a renderer that fails to start is torn down before the flat map takes over', async () => {
		const onfail = vi.fn();
		render(Globe, props({ onfail }));
		await mounted();
		await tick();
		opts.onStatus({ failed: true, error: 'WebGL 2 unavailable' });
		expect(engine.destroy).toHaveBeenCalledTimes(1);
		expect(onfail).toHaveBeenCalledWith('WebGL 2 unavailable');
	});

	it('outlines that fail to load hand over to the flat map without making a renderer', async () => {
		const onfail = vi.fn();
		vi.mocked(loadLandMask).mockRejectedValue(new Error('Country outlines: HTTP 404'));
		render(Globe, props({ onfail }));
		await settle();
		expect(mountGlobe).not.toHaveBeenCalled();
		expect(onfail).toHaveBeenCalledWith('Country outlines: HTTP 404');
	});

	it('hover shows the place, its connections and bytes; the list highlight shows none', async () => {
		const { container } = render(Globe, props());
		await mounted();
		await tick();
		opts.onHover({ kind: 'city', key: 'NL/Amsterdam', code: 'NL', city: 'Amsterdam', country: 'Netherlands', count: 4, bytes: 9000 });
		await tick();
		// OLD CODE: toHaveTextContent('Amsterdam, Netherlands4 connections · 9.0 KB') (NET-237, GEO-5: the count is the country's)
		expect(container.querySelector('.globe-tip')).toHaveTextContent('Netherlands · busiest city Amsterdam4 connections · 9.0 KB');
		opts.onHover({ kind: 'city', key: 'JP/', code: 'JP', city: '', country: 'Japan', count: 2, bytes: 200 });
		await tick();
		expect(container.querySelector('.globe-tip')).toHaveTextContent(/^Japan2 connections/);
		opts.onHover({ kind: 'list', key: 'list/NL', code: 'NL', city: '', country: '', count: 0, bytes: 0 });
		await tick();
		expect(container.querySelector('.globe-tip')).toHaveAttribute('hidden');
	});

	it('names the home on its label and labels the map for screen readers', async () => {
		const { container } = render(Globe, props());
		expect(container.querySelector('.globe-home')).toHaveTextContent('Your networkLondon');
		expect(screen.getByRole('img', { name: 'Connections to 1 country' })).toBeInTheDocument();
	});
});
