/**
 * LiveGlobeCard: the destinations list and filter, the notices (no home, home unreadable, no 3D),
 * the flat map (chosen or fallen back to) with its home ring and pause, and the expanded view as a
 * real modal: the rest of the page inert, focus moved in, kept in and given back.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import LiveGlobeCard, { destinationsOf, inertOthers } from './LiveGlobeCard.svelte';
import { mountGlobe } from '$lib/components/ui/charts/globe/engine.js';
import { loadLandMask } from '$lib/components/ui/charts/globe/land.js';
import { DISPLAY_SETTINGS_KEY } from '$lib/utils/drilldown';
import type { GeoArc } from '$lib/api/live';

vi.mock('$lib/components/ui/charts/globe/engine.js', () => ({ mountGlobe: vi.fn() }));
vi.mock('$lib/components/ui/charts/globe/land.js', () => ({ loadLandMask: vi.fn() }));

const ARCS: GeoArc[] = [
	{ city: 'Amsterdam', country: 'Netherlands', country_code: 'NL', lat: 52.37, lon: 4.9, count: 4, bytes: 9000 },
	{ city: 'Seattle', country: 'United States', country_code: 'US', lat: 47.61, lon: -122.33, count: 9, bytes: 30_000 },
	{ city: 'Rotterdam', country: 'Netherlands', country_code: 'NL', lat: 51.92, lon: 4.48, count: 6, bytes: 1000 },
];
const HOME = { lat: 51.5, lon: -0.13, label: 'London' };

type Status = { ready?: boolean; failed?: boolean; backend?: string; error?: string };
let onStatus: (s: Status) => void;
const engine = {
	ingest: vi.fn(), setSelected: vi.fn(), setHome: vi.fn(), setPaused: vi.fn(), setReduced: vi.fn(), setExpanded: vi.fn(), highlight: vi.fn(), destroy: vi.fn(),
};

beforeEach(() => {
	vi.mocked(mountGlobe).mockReset().mockImplementation((_c: unknown, o: { onStatus: (s: Status) => void }) => {
		onStatus = o.onStatus;
		return engine;
	});
	vi.mocked(loadLandMask).mockReset().mockResolvedValue({ W: 1, H: 1 });
	vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q }));
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	// DotMap's outlines: missing, so it draws hotspots on a blank background
	vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })));
	vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
	localStorage.clear();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	document.documentElement.style.overflow = '';
});

function props(extra = {}) {
	return {
		arcs: ARCS,
		fresh: [],
		rows: [],
		stats: [{ key: 'rate', label: 'Connections per second', value: '1.5' }],
		home: HOME,
		loaded: true,
		onselect: vi.fn(),
		onretry: vi.fn(),
		...extra,
	};
}

const mounted = () => vi.waitFor(() => expect(mountGlobe).toHaveBeenCalled());
const destButton = (name: string) => screen.getByRole('button', { name: new RegExp(`^Filter by ${name}:`) });

describe('destinationsOf', () => {
	it('merges cities per country, busiest first', () => {
		expect(destinationsOf(ARCS)).toEqual([
			{ code: 'NL', name: 'Netherlands', count: 10, bytes: 10_000, cities: ['Amsterdam', 'Rotterdam'] },
			{ code: 'US', name: 'United States', count: 9, bytes: 30_000, cities: ['Seattle'] },
		]);
	});
});

describe('LiveGlobeCard', () => {
	it('lists the destinations as filter buttons and marks the selected one', async () => {
		const p = props({ selected: 'US' });
		render(LiveGlobeCard, p);
		await mounted();
		expect(screen.getAllByRole('button', { name: /^Filter by/ }).map((b) => b.getAttribute('aria-label'))).toEqual([
			'Filter by Netherlands: 10 connections, 10.0 KB',
			'Filter by United States: 9 connections, 30.0 KB',
		]);
		expect(destButton('United States')).toHaveAttribute('aria-pressed', 'true');
		await fireEvent.click(destButton('Netherlands'));
		expect(p.onselect).toHaveBeenCalledWith('NL');
		// hovering the list lights the country on the globe
		await fireEvent.mouseEnter(destButton('Netherlands'));
		await vi.waitFor(() => expect(engine.highlight).toHaveBeenLastCalledWith('NL'));
	});

	it('shows the backend that drew the globe once it is ready', async () => {
		const { container } = render(LiveGlobeCard, props());
		await mounted();
		onStatus({ ready: true, backend: 'WebGPU' });
		await tick();
		expect(container.querySelector('.globe-card')).toHaveAttribute('data-backend', 'WebGPU');
		expect(screen.getByText('Drawn with WebGPU')).toBeInTheDocument();
	});

	it('says where to set the location when none is saved, and draws no home', async () => {
		render(LiveGlobeCard, props({ home: null }));
		expect(screen.getByRole('link', { name: 'Settings › Network' })).toHaveAttribute('href', '/settings?tab=network');
		expect(screen.getByText(/isn't set, so the globe shows destinations only/)).toBeInTheDocument();
	});

	it("says when the saved location couldn't be read", () => {
		render(LiveGlobeCard, props({ home: null, homeFailed: true }));
		expect(screen.getByText(/Couldn't load your network's location/).closest('[role="status"]')).not.toBeNull();
		expect(screen.queryByRole('link', { name: 'Settings › Network' })).toBeNull();
	});

	it('falls back to the flat map, with its home ring, when the renderer fails', async () => {
		const { container } = render(LiveGlobeCard, props());
		await mounted();
		onStatus({ failed: true, error: 'no WebGL 2' });
		await tick();
		expect(screen.getByText("This browser can't draw the 3D globe, so the flat map is shown.")).toBeInTheDocument();
		expect(container.querySelector('.globe-card')).toHaveAttribute('data-backend', 'flat');
		expect(container.querySelector('svg .home-ring')).not.toBeNull();
		expect(container.querySelectorAll('svg .arc').length).toBeGreaterThan(0);
	});

	it('draws the flat map this browser picked, with no fallback note, and pauses its arcs with the page', async () => {
		localStorage.setItem(DISPLAY_SETTINGS_KEY, JSON.stringify({ liveMap: 'flat' }));
		const { container, rerender } = render(LiveGlobeCard, props());
		await tick();
		expect(mountGlobe).not.toHaveBeenCalled();
		expect(container.querySelector('svg .home-ring')).not.toBeNull();
		expect(screen.queryByText(/can't draw the 3D globe/)).toBeNull();
		expect(screen.getByText('Flat map')).toBeInTheDocument();
		expect(container.querySelector('.globe-stage')).not.toHaveClass('is-paused');
		await rerender(props({ paused: true }));
		expect(container.querySelector('.globe-stage')).toHaveClass('is-paused');
	});

	it('states: loading, then the error with Try again', async () => {
		const { rerender } = render(LiveGlobeCard, props({ loaded: false }));
		expect(screen.getByRole('status')).toHaveTextContent('Loading the globe');
		expect(screen.getByRole('button', { name: 'Expand' })).toBeDisabled();
		const p = props({ loaded: false, error: "Couldn't load live data: the request failed." });
		await rerender(p);
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(p.onretry).toHaveBeenCalled();
	});
});

describe('LiveGlobeCard expanded', () => {
	/** body > .shell > [nav, main > [header, target]], plus an element that was inert already. */
	function layout() {
		document.body.innerHTML =
			'<div class="shell"><nav id="sidebar"><a href="/">Home</a></nav><main id="main"><header id="topbar"><button id="refresh">Refresh</button></header><div id="target"></div></main></div><aside id="already" inert></aside>';
		return document.getElementById('target')!;
	}

	it('makes everything outside the card inert, and undoes only that', () => {
		const target = layout();
		const card = document.createElement('article');
		target.append(card);
		const undo = inertOthers(card);
		for (const id of ['sidebar', 'topbar', 'already']) expect(document.getElementById(id)).toHaveAttribute('inert');
		expect(document.getElementById('main')).not.toHaveAttribute('inert');
		undo();
		expect(document.getElementById('sidebar')).not.toHaveAttribute('inert');
		expect(document.getElementById('topbar')).not.toHaveAttribute('inert');
		expect(document.getElementById('already')).toHaveAttribute('inert');
	});

	it('opens as a modal dialog with focus on Close, even when the click left focus elsewhere', async () => {
		const target = layout();
		render(LiveGlobeCard, { target, props: props() });
		document.getElementById('refresh')!.focus();
		await fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
		await tick();
		const dialog = screen.getByRole('dialog', { name: 'Where your traffic goes' });
		expect(dialog).toHaveAttribute('aria-modal', 'true');
		expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }));
		expect(document.getElementById('sidebar')).toHaveAttribute('inert');
		expect(document.getElementById('topbar')).toHaveAttribute('inert');
		expect(document.documentElement.style.overflow).toBe('hidden');
		expect(screen.getByRole('group', { name: 'Right now' })).toHaveTextContent('Connections per second1.5');
	});

	it('Esc from a destination button closes it and gives focus back to Expand', async () => {
		const target = layout();
		render(LiveGlobeCard, { target, props: props() });
		await fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
		await tick();
		destButton('Netherlands').focus();
		await fireEvent.keyDown(destButton('Netherlands'), { key: 'Escape' });
		await tick();
		expect(screen.queryByRole('dialog')).toBeNull();
		expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Expand' }));
		expect(document.getElementById('sidebar')).not.toHaveAttribute('inert');
		expect(document.documentElement.style.overflow).toBe('');
	});

	it('keeps Tab and Shift+Tab inside the dialog', async () => {
		const target = layout();
		render(LiveGlobeCard, { target, props: props() });
		await fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
		await tick();
		const close = screen.getByRole('button', { name: 'Close' });
		const last = destButton('United States');
		last.focus();
		await fireEvent.keyDown(last, { key: 'Tab' });
		expect(document.activeElement).toBe(close);
		await fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
		expect(document.activeElement).toBe(last);
	});
});
