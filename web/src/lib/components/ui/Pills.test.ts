import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Pills from './Pills.svelte';

const RANGES = [
	{ value: '1h', label: '1h' },
	{ value: '24h', label: '24h' },
	{ value: '7d', label: '7d' },
	{ value: '30d', label: '30d' },
];

describe('Pills toggle mode', () => {
	it('is a labelled group of buttons with the selected one pressed', () => {
		render(Pills, { options: RANGES, value: '24h', ariaLabel: 'Time range' });
		const group = screen.getByRole('group', { name: 'Time range' });
		expect(group).toHaveClass('pills');
		expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'false');
		expect(screen.getByRole('button', { name: '1h' })).toHaveClass('pill');
	});

	it('turns every pill off when disabled, and on again after', async () => {
		const { rerender } = render(Pills, { options: RANGES, value: '24h', ariaLabel: 'Time range', disabled: true });
		for (const r of RANGES) expect(screen.getByRole('button', { name: r.label })).toBeDisabled();
		await rerender({ disabled: false });
		for (const r of RANGES) expect(screen.getByRole('button', { name: r.label })).toBeEnabled();
	});

	it('selects a pill on click and reports it once', async () => {
		const onchange = vi.fn();
		render(Pills, { options: RANGES, value: '24h', ariaLabel: 'Time range', onchange });
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		expect(onchange).toHaveBeenCalledExactlyOnceWith('7d');
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'false');
	});

	it('does not report a click on the pill that is already selected', async () => {
		const onchange = vi.fn();
		render(Pills, { options: RANGES, value: '24h', ariaLabel: 'Time range', onchange });
		await fireEvent.click(screen.getByRole('button', { name: '24h' }));
		expect(onchange).not.toHaveBeenCalled();
	});
});

describe('Pills tabs mode', () => {
	const SECTIONS = [
		{ value: 'general', label: 'General' },
		{ value: 'storage', label: 'Storage' },
		{ value: 'alerts', label: 'Alerts' },
	];

	function renderTabs(value = 'storage') {
		const onchange = vi.fn();
		render(Pills, { options: SECTIONS, value, ariaLabel: 'Settings sections', mode: 'tabs', idPrefix: 'set', onchange });
		return { onchange, tab: (name: string) => screen.getByRole('tab', { name }) };
	}

	it('renders a labelled tablist whose tabs point at their panels', () => {
		const { tab } = renderTabs();
		expect(screen.getByRole('tablist', { name: 'Settings sections' })).toHaveClass('pills');
		for (const { value, label } of SECTIONS) {
			expect(tab(label)).toHaveAttribute('id', `set-tab-${value}`);
			expect(tab(label)).toHaveAttribute('aria-controls', `set-panel-${value}`);
		}
		expect(tab('Storage')).toHaveAttribute('aria-selected', 'true');
		expect(tab('General')).toHaveAttribute('aria-selected', 'false');
	});

	it('uses a roving tabindex: only the selected tab is in the tab order', () => {
		const { tab } = renderTabs();
		expect(tab('Storage')).toHaveAttribute('tabindex', '0');
		expect(tab('General')).toHaveAttribute('tabindex', '-1');
		expect(tab('Alerts')).toHaveAttribute('tabindex', '-1');
	});

	it('puts the first tab in the tab order when none is selected', () => {
		const { tab } = renderTabs('missing');
		expect(tab('General')).toHaveAttribute('tabindex', '0');
	});

	it('ArrowRight and ArrowLeft move focus and select, wrapping at the ends', async () => {
		const { tab, onchange } = renderTabs();
		await fireEvent.keyDown(tab('Storage'), { key: 'ArrowRight' });
		expect(tab('Alerts')).toHaveFocus();
		expect(tab('Alerts')).toHaveAttribute('aria-selected', 'true');
		expect(tab('Alerts')).toHaveAttribute('tabindex', '0');
		expect(tab('Storage')).toHaveAttribute('tabindex', '-1');
		expect(onchange).toHaveBeenLastCalledWith('alerts');

		await fireEvent.keyDown(tab('Alerts'), { key: 'ArrowRight' });
		expect(tab('General')).toHaveFocus();
		expect(onchange).toHaveBeenLastCalledWith('general');

		await fireEvent.keyDown(tab('General'), { key: 'ArrowLeft' });
		expect(tab('Alerts')).toHaveFocus();
		expect(tab('Alerts')).toHaveAttribute('aria-selected', 'true');
		expect(onchange).toHaveBeenLastCalledWith('alerts');
	});

	it('Home and End jump to the first and last tab', async () => {
		const { tab, onchange } = renderTabs();
		await fireEvent.keyDown(tab('Storage'), { key: 'End' });
		expect(tab('Alerts')).toHaveFocus();
		expect(onchange).toHaveBeenLastCalledWith('alerts');
		await fireEvent.keyDown(tab('Alerts'), { key: 'Home' });
		expect(tab('General')).toHaveFocus();
		expect(tab('General')).toHaveAttribute('aria-selected', 'true');
		expect(onchange).toHaveBeenLastCalledWith('general');
	});

	it('ignores other keys', async () => {
		const { tab, onchange } = renderTabs();
		await fireEvent.keyDown(tab('Storage'), { key: 'ArrowDown' });
		await fireEvent.keyDown(tab('Storage'), { key: 'a' });
		expect(onchange).not.toHaveBeenCalled();
		expect(tab('Storage')).toHaveAttribute('aria-selected', 'true');
	});

	it('selects a tab on click', async () => {
		const { tab, onchange } = renderTabs();
		await fireEvent.click(tab('General'));
		expect(onchange).toHaveBeenCalledExactlyOnceWith('general');
		expect(tab('General')).toHaveAttribute('aria-selected', 'true');
	});

	it('generates an id prefix when none is given, the same for tab and panel', () => {
		render(Pills, { options: SECTIONS, value: 'general', ariaLabel: 'Settings sections', mode: 'tabs' });
		const general = screen.getByRole('tab', { name: 'General' });
		const prefix = general.id.replace(/-tab-general$/, '');
		expect(prefix).not.toBe('');
		expect(general).toHaveAttribute('aria-controls', `${prefix}-panel-general`);
	});
});

describe('Pills nav mode', () => {
	it('renders labelled navigation links with aria-current on the current route', () => {
		render(Pills, {
			options: [
				{ value: 'all', label: 'All alerts', href: '/alerts' },
				{ value: 'grouped', label: 'By category', href: '/alerts?group=category' },
			],
			value: 'grouped',
			ariaLabel: 'Alert views',
			mode: 'nav',
		});
		expect(screen.getByRole('navigation', { name: 'Alert views' })).toHaveClass('pills');
		const current = screen.getByRole('link', { name: 'By category' });
		expect(current).toHaveAttribute('href', '/alerts?group=category');
		expect(current).toHaveAttribute('aria-current', 'page');
		expect(screen.getByRole('link', { name: 'All alerts' })).not.toHaveAttribute('aria-current');
	});
});

// NET-348: on a phone the pill track scrolls sideways with its scrollbar hidden (a11y.css 5)
describe('Pills: the selected pill scrolls into view inside its track', () => {
	const WIDE = [...RANGES, { value: 'custom', label: '19:02 to 20:02, 20 Nov' }, { value: 'later', label: 'Later' }];
	/** Each pill 100 px wide in a 200 px track, moved left by the track's scroll; jsdom has no layout. */
	function layOut() {
		return vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
			if (this.classList.contains('pills')) return new DOMRect(0, 0, 200, 30);
			const track = this.parentElement!;
			const i = [...track.children].indexOf(this);
			return new DOMRect(i * 100 - track.scrollLeft, 0, 100, 30);
		});
	}

	it('brings a trailing selected pill into view on mount, then a leading one, without moving focus or the page', async () => {
		const rects = layOut();
		const original = Element.prototype.scrollIntoView;
		const scrollIntoView = vi.fn();
		Element.prototype.scrollIntoView = scrollIntoView;
		try {
			const { rerender } = render(Pills, { options: WIDE, value: 'custom', ariaLabel: 'Time range' });
			const track = screen.getByRole('group', { name: 'Time range' });
			// pill 4 spans 400–500 px: the track scrolls just far enough to show its right edge
			expect(track.scrollLeft).toBe(300);
			await rerender({ value: '1h' });
			expect(track.scrollLeft).toBe(0);
			await rerender({ value: '24h' }); // already in view: no scroll
			expect(track.scrollLeft).toBe(0);
			expect(document.activeElement).toBe(document.body);
			expect(scrollIntoView).not.toHaveBeenCalled();
		} finally {
			rects.mockRestore();
			Element.prototype.scrollIntoView = original;
		}
	});

	it('scrolls the track in tabs and nav mode too', () => {
		const rects = layOut();
		try {
			render(Pills, { options: WIDE, value: 'later', ariaLabel: 'Views', mode: 'tabs' });
			expect(screen.getByRole('tablist', { name: 'Views' }).scrollLeft).toBe(400);
			render(Pills, { options: WIDE.map((o) => ({ ...o, href: `/x/${o.value}` })), value: 'later', ariaLabel: 'Sections', mode: 'nav' });
			expect(screen.getByRole('navigation', { name: 'Sections' }).scrollLeft).toBe(400);
		} finally {
			rects.mockRestore();
		}
	});
});
