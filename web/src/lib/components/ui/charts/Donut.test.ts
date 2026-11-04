import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';
import Donut from './Donut.svelte';
import { REST_KEY, type SeriesItem } from '$lib/utils/series';

const item = (key: string, value: number) => ({ key, label: key.toUpperCase(), value, source: { id: key } });
const PROTOCOLS = [item('https', 105795), item('quic', 34657), item('dns', 25537), item('http', 7296), item('other', 9121)];
const MANY = 'abcdefgh'.split('').map((k, i) => item(k, 100 - i * 10));
const fmt = (v: number) => v.toLocaleString('en-GB');

function draw(items: SeriesItem<{ id: string }>[], extra: Record<string, unknown> = {}) {
	return render(Donut<{ id: string }>, {
		props: { items, centreLabel: 'sessions', formatValue: fmt, ariaLabel: 'Protocol share: HTTPS 58%', ...extra },
	});
}

describe('Donut', () => {
	it('draws 12px segments from 12 o’clock with the total in the centre and a .kv legend', () => {
		const { container, getByRole } = draw(PROTOCOLS);
		expect(getByRole('img').getAttribute('aria-label')).toBe('Protocol share: HTTPS 58%');
		const segs = [...container.querySelectorAll('circle.seg')];
		expect(segs).toHaveLength(5);
		expect(segs[0].classList.contains('ln-1')).toBe(true);
		expect(segs.every((s) => s.getAttribute('transform')?.startsWith('rotate(-90'))).toBe(true);
		// clockwise: every later segment starts further along the ring (a more negative offset)
		const offsets = segs.map((s) => Number(s.getAttribute('stroke-dashoffset')));
		offsets.slice(1).forEach((o, i) => expect(o).toBeLessThan(offsets[i]));
		expect(container.querySelector('.d-num')?.textContent).toBe('182,406');
		expect(container.querySelector('.d-lbl')?.textContent).toBe('sessions');
		const rows = container.querySelectorAll('.donut-wrap .kv > li');
		expect(rows).toHaveLength(5);
		expect(rows[0].textContent).toContain('HTTPS');
		expect(rows[0].textContent).toContain('58%');
		expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
	});

	it('shows a given total in the centre instead of the sum', () => {
		const { container } = draw(PROTOCOLS, { total: 200000 });
		expect(container.querySelector('.d-num')?.textContent).toBe('200,000');
	});

	it('keeps the legend static and has no buttons outside "Everything else" without onselect', () => {
		const { queryAllByRole } = draw(PROTOCOLS);
		expect(queryAllByRole('button')).toHaveLength(0);
	});

	it('draws a single item as the full ring and nothing for all-zero or empty input', () => {
		const one = draw([item('https', 5), item('dns', 0)]);
		const seg = one.container.querySelector('circle.seg')!;
		expect(one.container.querySelectorAll('circle.seg')).toHaveLength(1);
		expect(seg.getAttribute('stroke-dashoffset')).toBe('0');
		one.unmount();
		expect(draw([item('a', 0), item('b', 0)]).container.querySelector('svg')).toBeNull();
		expect(draw([]).container.querySelector('svg')).toBeNull();
	});

	it('passes the original item back from a legend button', async () => {
		const onselect = vi.fn();
		const { getByRole } = draw(PROTOCOLS, { onselect });
		await fireEvent.click(getByRole('button', { name: /QUIC/ }));
		expect(onselect).toHaveBeenCalledWith(expect.objectContaining({ key: 'quic', source: { id: 'quic' } }));
	});

	it('folds past six into "Everything else", which lists its members with their own callbacks', async () => {
		const onselect = vi.fn();
		const { container, getByRole, queryByRole } = draw(MANY, { onselect });
		expect(container.querySelectorAll('circle.seg')).toHaveLength(6);
		const rest = getByRole('button', { name: /Everything else/ });
		expect(rest.getAttribute('aria-expanded')).toBe('false');
		expect(queryByRole('button', { name: /^\s*G/ })).toBeNull();

		await fireEvent.click(rest);
		expect(rest.getAttribute('aria-expanded')).toBe('true');
		const members = document.getElementById(rest.getAttribute('aria-controls')!)!;
		expect(within(members).getAllByRole('button').map((b) => b.textContent?.trim().charAt(0))).toEqual(['F', 'G', 'H']);
		await fireEvent.click(within(members).getByRole('button', { name: /^\s*G/ }));
		expect(onselect).toHaveBeenCalledWith(expect.objectContaining({ key: 'g', source: { id: 'g' } }));
		expect(onselect).not.toHaveBeenCalledWith(expect.objectContaining({ key: REST_KEY }));

		await fireEvent.click(rest);
		expect(document.getElementById(rest.getAttribute('aria-controls')!)).toBeNull();
	});

	it('lists the members as plain rows when there is no onselect', async () => {
		const { getByRole, container } = draw(MANY);
		await fireEvent.click(getByRole('button', { name: /Everything else/ }));
		const members = container.querySelectorAll('.kv-members > li');
		expect(members).toHaveLength(3);
		expect(members[0].querySelector('button')).toBeNull();
	});
});
