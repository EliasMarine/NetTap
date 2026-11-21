/**
 * DetailDrawer as a native modal dialog (NET-349: at phone width, Tab walked the table hidden
 * behind the open drawer). jsdom has no showModal, so setup.ts stands in for it; the browser's own
 * inert page and top layer are covered by e2e/visual/phone-shell.visual.ts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import DetailDrawer from './DetailDrawer.svelte';

const children = createRawSnippet(() => ({
	render: () => '<div><button type="button">Inside</button><a href="#last">Last link</a></div>',
}));

function props(over: Record<string, unknown> = {}) {
	return { open: false, title: 'Connection 192.0.2.7', tabs: [], activeTab: '', onclose: vi.fn(), ontabchange: vi.fn(), children, ...over };
}

let opener: HTMLButtonElement;
let elsewhere: HTMLInputElement;

beforeEach(() => {
	document.body.innerHTML = '<main id="main" tabindex="-1"><button id="opener">Open row</button><input id="elsewhere" /></main>';
	opener = document.getElementById('opener') as HTMLButtonElement;
	elsewhere = document.getElementById('elsewhere') as HTMLInputElement;
});

afterEach(() => {
	document.body.innerHTML = '';
});

/** jsdom has no PointerEvent, and fireEvent's fallback drops the coordinates. */
function press(el: Element, clientX: number, clientY: number) {
	el.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX, clientY }));
}

/** Open the way a page does: a click on the opener, then the parent flips `open`. */
async function openFrom(el: HTMLElement, over: Record<string, unknown> = {}) {
	const p = props(over);
	const view = render(DetailDrawer, { props: p, target: document.body });
	await fireEvent.click(el);
	await view.rerender({ open: true });
	await tick();
	return { ...view, p, dialog: screen.getByRole('dialog') as HTMLDialogElement };
}

describe('DetailDrawer — a modal dialog', () => {
	it('opens as a dialog named by its title, with focus on Close', async () => {
		const { dialog } = await openFrom(opener);
		expect(dialog).toHaveAttribute('open');
		expect(screen.getByRole('dialog', { name: 'Connection 192.0.2.7' })).toBe(dialog);
		expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close panel' }));
	});

	it('is closed, with nothing to reach, until opened', () => {
		render(DetailDrawer, { props: props(), target: document.body });
		const dialog = document.querySelector('dialog')!;
		expect(dialog).not.toHaveAttribute('open');
		expect(screen.queryByRole('button', { name: 'Close panel' })).not.toBeInTheDocument();
	});

	it('asks the parent to close on Escape, and stops the browser closing it itself', async () => {
		const { dialog, p } = await openFrom(opener);
		const cancel = new Event('cancel', { cancelable: true });
		dialog.dispatchEvent(cancel);
		expect(cancel.defaultPrevented).toBe(true);
		expect(p.onclose).toHaveBeenCalledTimes(1);
	});

	it('closes on a press and release outside the panel, but not on a click inside or a drag across its edge', async () => {
		const { dialog, p } = await openFrom(opener);
		const panel = dialog.querySelector('.panel') as HTMLElement;
		panel.getBoundingClientRect = () => ({ left: 400, right: 880, top: 0, bottom: 800, width: 480, height: 800, x: 400, y: 0, toJSON: () => ({}) });

		await fireEvent.click(screen.getByRole('button', { name: 'Inside' }));
		expect(p.onclose).not.toHaveBeenCalled();
		// pressed inside, released on the backdrop
		press(screen.getByRole('button', { name: 'Inside' }), 500, 100);
		await fireEvent.click(dialog, { clientX: 100, clientY: 100 });
		expect(p.onclose).not.toHaveBeenCalled();
		// pressed on the backdrop, released inside: the click's target is the dialog, its point inside
		press(dialog, 100, 100);
		await fireEvent.click(dialog, { clientX: 500, clientY: 100 });
		expect(p.onclose).not.toHaveBeenCalled();
		// both on the backdrop
		press(dialog, 100, 100);
		await fireEvent.click(dialog, { clientX: 120, clientY: 110 });
		expect(p.onclose).toHaveBeenCalledTimes(1);
	});

	it('returns focus to the clicked opener on close, even when focus was elsewhere', async () => {
		elsewhere.focus();
		// jsdom, like Safari, doesn't focus a clicked button; the drawer notes the click itself
		const { rerender } = await openFrom(opener);
		await rerender({ open: false });
		await tick();
		expect(document.querySelector('dialog')).not.toHaveAttribute('open');
		expect(document.activeElement).toBe(opener);
	});

	it('falls back to the main region when the opener is gone', async () => {
		const { rerender } = await openFrom(opener);
		opener.remove();
		await rerender({ open: false });
		await tick();
		expect(document.activeElement).toBe(document.getElementById('main'));
	});

	it('closes the dialog and restores focus when unmounted while open', async () => {
		const { unmount, dialog } = await openFrom(opener);
		unmount();
		await tick();
		expect(dialog).not.toHaveAttribute('open');
		expect(document.activeElement).toBe(opener);
	});

	it('ignores a late close event from an earlier close once it has opened again', async () => {
		const { rerender, dialog, p } = await openFrom(opener);
		await rerender({ open: false });
		await rerender({ open: true });
		await tick();
		// the close event the first close queued arrives now, after the reopen
		await new Promise((r) => setTimeout(r, 0));
		dialog.dispatchEvent(new Event('close'));
		expect(p.onclose).not.toHaveBeenCalled();
		expect(dialog).toHaveAttribute('open');
	});

	it('asks the parent to close when the browser closes it on its own', async () => {
		const { dialog, p } = await openFrom(opener);
		dialog.removeAttribute('open');
		dialog.dispatchEvent(new Event('close'));
		expect(p.onclose).toHaveBeenCalledTimes(1);
	});

	it('wraps Tab at both ends', async () => {
		const { dialog } = await openFrom(opener);
		const close = screen.getByRole('button', { name: 'Close panel' });
		const last = screen.getByRole('link', { name: 'Last link' });
		last.focus();
		await fireEvent.keyDown(dialog, { key: 'Tab' });
		expect(document.activeElement).toBe(close);
		await fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
		expect(document.activeElement).toBe(last);
	});
});
