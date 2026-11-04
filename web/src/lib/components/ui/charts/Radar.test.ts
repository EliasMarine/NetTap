import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import Radar from './Radar.svelte';

const AXES = [
	{ key: 'privacy', label: 'Privacy', value: 48 },
	{ key: 'security', label: 'Security', value: 71 },
	{ key: 'updates', label: 'Updates', value: 90 },
	{ key: 'exposure', label: 'Exposure', value: 35 },
	{ key: 'behaviour', label: 'Behaviour', value: 80 },
];
const draw = (axes: typeof AXES) => render(Radar, { props: { axes, ariaLabel: 'Trust score factors: Privacy 48, Security 71' } });

describe('Radar', () => {
	it('draws grid rings, a spoke, point and label per axis, and the score area', () => {
		const { container, getByRole } = draw(AXES);
		expect(getByRole('img').getAttribute('aria-label')).toBe('Trust score factors: Privacy 48, Security 71');
		expect(container.querySelectorAll('polygon.radar-grid')).toHaveLength(4);
		expect(container.querySelectorAll('line.radar-spoke')).toHaveLength(5);
		expect(container.querySelectorAll('circle.radar-pt')).toHaveLength(5);
		expect(container.querySelector('polygon.radar-area')?.getAttribute('points')?.split(' ')).toHaveLength(5);
		const labels = [...container.querySelectorAll('text.radar-lbl')];
		expect(labels[0].textContent).toBe('Privacy 48');
		expect(labels[0].getAttribute('text-anchor')).toBe('middle');
		expect(labels[0].querySelector('tspan.radar-v')?.textContent).toBe('48');
		expect(container.innerHTML).not.toMatch(/NaN/);
	});

	it('puts a 100 on the outer ring and a 0 at the centre', () => {
		const { container } = draw([
			{ key: 'a', label: 'A', value: 100 },
			{ key: 'b', label: 'B', value: 0 },
			{ key: 'c', label: 'C', value: 50 },
		]);
		const outer = container.querySelectorAll('polygon.radar-grid')[3].getAttribute('points')!.split(' ');
		const area = container.querySelector('polygon.radar-area')!.getAttribute('points')!.split(' ');
		expect(area[0]).toBe(outer[0]);
		const spoke = container.querySelector('line.radar-spoke')!;
		expect(area[1]).toBe(`${Number(spoke.getAttribute('x1')).toFixed(1)},${Number(spoke.getAttribute('y1')).toFixed(1)}`);
	});

	it('clamps scores and renders nothing below three axes', () => {
		const { container } = draw([
			{ key: 'a', label: 'A', value: 140 },
			{ key: 'b', label: 'B', value: -5 },
			{ key: 'c', label: 'C', value: Number.NaN },
		]);
		expect([...container.querySelectorAll('tspan.radar-v')].map((t) => t.textContent)).toEqual(['100', '0', '0']);
		expect(container.innerHTML).not.toMatch(/NaN/);
		expect(draw(AXES.slice(0, 2)).container.querySelector('svg')).toBeNull();
	});
});
