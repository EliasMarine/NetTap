import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import * as searchApi from '$api/search';
import { searchTarget, updatedText } from './topbar';
import { registerPageRefresh, type PageRefreshHandle } from '$lib/stores/pageRefresh';
import TopBar from './TopBar.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/search', () => ({ getSearchSuggestions: vi.fn() }));
// The bell has its own tests; here it only has to render.
vi.mock('$components/NotificationBell.svelte', async () => ({
	default: (await import('./BrandMark.svelte')).default,
}));

const suggest = vi.mocked(searchApi.getSearchSuggestions);

async function type(text: string) {
	const box = screen.getByRole('combobox');
	await fireEvent.input(box, { target: { value: text } });
	await vi.advanceTimersByTimeAsync(250);
	return box;
}

let handle: PageRefreshHandle | undefined;

beforeEach(() => {
	vi.useFakeTimers();
	suggest.mockResolvedValue({ suggestions: [{ text: '192.168.1.10' }, { text: '192.168.1.20' }] });
});

afterEach(() => {
	handle?.unregister();
	handle = undefined;
	vi.useRealTimers();
	vi.clearAllMocks();
});

describe('searchTarget', () => {
	it.each([
		['192.168.1.42', '/logs?ip=192.168.1.42'],
		[' 10.0.0.1 ', '/logs?ip=10.0.0.1'],
		['fe80::1', '/logs?ip=fe80%3A%3A1'],
		['github.com', '/logs?query=github.com'],
		['Kitchen iPad', '/logs?query=Kitchen%20iPad'],
	])('%s → %s', (q, target) => {
		expect(searchTarget(q)).toBe(target);
	});

	it('does nothing for empty input', () => {
		expect(searchTarget('   ')).toBeNull();
	});
});

describe('updatedText', () => {
	const t0 = new Date(2026, 10, 3, 21, 5, 0).getTime();

	it.each([
		[null, 'Not updated yet'],
		[t0, 'Updated just now'],
		[t0 - 12_000, 'Updated 12 s ago'],
		[t0 - 5 * 60_000, 'Updated 5 min ago'],
		[t0 - 2 * 3_600_000, 'Updated at 19:05'],
	])('%s', (at, text) => {
		expect(updatedText(at, t0)).toBe(text);
	});
});

describe('TopBar search', () => {
	it('lists suggestions and announces how many', async () => {
		render(TopBar, { props: { offline: false } });
		const box = await type('192.168');
		expect(box).toHaveAttribute('aria-expanded', 'true');
		expect(box).toHaveAttribute('aria-controls', 'global-search-list');
		expect(screen.getAllByRole('option')).toHaveLength(2);
		expect(screen.getByRole('status')).toHaveTextContent('2 suggestions.');
	});

	it('moves through results with the arrow keys and opens the chosen one', async () => {
		render(TopBar, { props: { offline: false } });
		const box = await type('192.168');
		await fireEvent.keyDown(box, { key: 'ArrowDown' });
		await fireEvent.keyDown(box, { key: 'ArrowDown' });
		expect(box).toHaveAttribute('aria-activedescendant', 'global-search-list-1');
		expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true');
		await fireEvent.keyDown(box, { key: 'ArrowUp' });
		await fireEvent.keyDown(box, { key: 'Enter' });
		expect(goto).toHaveBeenCalledWith('/logs?ip=192.168.1.10');
	});

	it('searches the typed text when nothing is highlighted', async () => {
		render(TopBar, { props: { offline: false } });
		const box = await type('github.com');
		await fireEvent.keyDown(box, { key: 'Enter' });
		expect(goto).toHaveBeenCalledWith('/logs?query=github.com');
	});

	it('says when nothing matches', async () => {
		suggest.mockResolvedValue({ suggestions: [] });
		render(TopBar, { props: { offline: false } });
		const box = await type('zzzz');
		expect(screen.getByRole('status')).toHaveTextContent('No matches for "zzzz".');
		expect(box).toHaveAttribute('aria-expanded', 'false');
		expect(screen.queryAllByRole('option')).toHaveLength(0);
	});

	it('says when suggestions could not load', async () => {
		suggest.mockRejectedValue(new Error('network'));
		render(TopBar, { props: { offline: false } });
		await type('router');
		expect(screen.getByRole('status')).toHaveTextContent("Couldn't load suggestions.");
	});

	it('closes the list on Escape, then clears the field on a second Escape', async () => {
		render(TopBar, { props: { offline: false } });
		const box = (await type('192.168')) as HTMLInputElement;
		await fireEvent.keyDown(box, { key: 'Escape' });
		expect(box).toHaveAttribute('aria-expanded', 'false');
		expect(box.value).toBe('192.168');
		await fireEvent.keyDown(box, { key: 'Escape' });
		expect(box.value).toBe('');
	});

	it('only shows the newest keystroke\'s suggestions', async () => {
		let resolveSlow: (v: { suggestions: { text: string }[] }) => void = () => {};
		suggest
			.mockReturnValueOnce(new Promise((r) => (resolveSlow = r)))
			.mockResolvedValueOnce({ suggestions: [{ text: 'new.example' }] });
		render(TopBar, { props: { offline: false } });
		await type('ol');
		await type('new');
		resolveSlow({ suggestions: [{ text: 'old.example' }] });
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.getByRole('option')).toHaveTextContent('new.example');
	});

	it('focuses search on Ctrl-K', async () => {
		render(TopBar, { props: { offline: false } });
		await fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
		expect(document.activeElement).toBe(screen.getByRole('combobox'));
	});
});

describe('TopBar refresh and status', () => {
	it('hides Refresh and the timestamp on pages without a loader', () => {
		render(TopBar, { props: { offline: false } });
		expect(screen.queryByRole('button', { name: 'Refresh this page' })).not.toBeInTheDocument();
		expect(screen.queryByText(/Updated|Not updated/)).not.toBeInTheDocument();
	});

	it('runs the page loader and shows when it last fully succeeded', async () => {
		const loader = vi.fn(async () => 'ok' as const);
		handle = registerPageRefresh(loader);
		render(TopBar, { props: { offline: false } });
		expect(screen.getByText('Not updated yet')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh this page' }));
		await vi.advanceTimersByTimeAsync(1000);
		expect(loader).toHaveBeenCalledTimes(1);
		expect(screen.getByText('Updated just now')).toBeInTheDocument();
	});

	it('says some data failed after a partial refresh', async () => {
		handle = registerPageRefresh(async () => 'partial');
		render(TopBar, { props: { offline: false } });
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh this page' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.getByText('Some data failed to refresh')).toBeInTheDocument();
		expect(screen.getByText('Not updated yet')).toBeInTheDocument();
	});

	it("warns when NetTap can't be reached", () => {
		render(TopBar, { props: { offline: true } });
		expect(screen.getByText("Can't reach NetTap")).toBeInTheDocument();
	});
});
