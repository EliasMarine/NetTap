import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import NetworkFlow from './NetworkFlow.svelte';

const MB = 1_048_576;
const node = (id: string, value: number, label = id) => ({ id, label, value });
const link = (source: string, target: string, value: number) => ({ source, target, value });

const PROPS = {
	sources: [node('192.168.1.10', 60 * MB), node('192.168.1.20', 40 * MB)],
	protocols: [node('tcp', 70 * MB, 'TCP'), node('udp', 30 * MB, 'UDP')],
	destinations: [{ ...node('AS714 Apple Inc.', 50 * MB, 'Apple Inc.'), country: 'US' }, node('Unknown', 30 * MB)],
	links: [
		link('192.168.1.10', 'tcp', 40 * MB),
		link('192.168.1.10', 'udp', 20 * MB),
		link('192.168.1.20', 'tcp', 30 * MB),
		link('192.168.1.20', 'udp', 10 * MB),
		link('tcp', 'AS714 Apple Inc.', 40 * MB),
		link('udp', 'AS714 Apple Inc.', 10 * MB),
		link('tcp', 'Unknown', 20 * MB),
		link('udp', 'Unknown', 10 * MB),
	],
	names: new Map([['192.168.1.10', 'Kitchen iPad']]),
};

/** observeWidth reads clientWidth on attach; jsdom has no layout, so set it. */
function atWidth(width: number) {
	vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(width);
}

afterEach(() => vi.restoreAllMocks());

describe('NetworkFlow', () => {
	it('draws the chart in a wide card, with a headline for screen readers', () => {
		atWidth(1000);
		const { container, getByRole } = render(NetworkFlow, { props: PROPS });
		expect(container.querySelector('.flow-chart')).not.toBeNull();
		expect(container.querySelector('.flow-table')).toBeNull();
		expect(getByRole('group').getAttribute('aria-label')).toBe(
			'Network flow: 100.0 MB from 2 devices. TCP carries 70%. Apple Inc. is the largest destination at 50%.',
		);
		expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
	});

	it('shows the table in a narrow card, and before the card is measured', () => {
		atWidth(500);
		const narrow = render(NetworkFlow, { props: PROPS });
		expect(narrow.container.querySelector('.flow-table')).not.toBeNull();
		expect(narrow.container.querySelector('.flow-chart')).toBeNull();
		narrow.unmount();
		atWidth(0);
		expect(render(NetworkFlow, { props: PROPS }).container.querySelector('.flow-table')).not.toBeNull();
	});

	it('shows a named device by name with its IP, and an unnamed one by IP', () => {
		atWidth(1000);
		const { getByRole } = render(NetworkFlow, { props: PROPS });
		const named = getByRole('button', { name: /^Kitchen iPad \(192\.168\.1\.10\)/ });
		expect(named.textContent).toContain('Kitchen iPad');
		expect(named.textContent).toContain('192.168.1.10');
		expect(getByRole('button', { name: /^192\.168\.1\.20,/ }).textContent).not.toContain('Kitchen');
	});

	it('reports clicks with the node kind and id', async () => {
		atWidth(1000);
		const onNodeClick = vi.fn();
		const { getByRole } = render(NetworkFlow, { props: { ...PROPS, onNodeClick } });
		await fireEvent.click(getByRole('button', { name: /^TCP,/ }));
		await fireEvent.click(getByRole('button', { name: /^Kitchen iPad/ }));
		await fireEvent.click(getByRole('button', { name: /^Apple Inc\.,/ }));
		expect(onNodeClick.mock.calls).toEqual([
			['protocol', 'tcp'],
			['source', '192.168.1.10'],
			['destination', 'AS714 Apple Inc.'],
		]);
	});

	it('shows Other destinations without a button, in the chart and the table', () => {
		atWidth(1000);
		const chart = render(NetworkFlow, { props: PROPS });
		expect(chart.getByText('Other destinations')).not.toBeNull();
		expect(chart.queryByRole('button', { name: /Other destinations/ })).toBeNull();
		chart.unmount();
		atWidth(500);
		const table = render(NetworkFlow, { props: PROPS });
		return fireEvent.click(table.getByRole('tab', { name: 'Destinations' })).then(() => {
			expect(table.getByText('Other destinations')).not.toBeNull();
			expect(table.queryByRole('button', { name: /Other destinations/ })).toBeNull();
			expect(table.getByText('Everywhere outside the top 10')).not.toBeNull();
		});
	});

	it('marks the node that filters the table as pressed', () => {
		atWidth(1000);
		const { getByRole } = render(NetworkFlow, { props: { ...PROPS, selected: { type: 'protocol', id: 'udp' } } });
		expect(getByRole('button', { name: /^UDP,/ }).getAttribute('aria-pressed')).toBe('true');
		expect(getByRole('button', { name: /^TCP,/ }).getAttribute('aria-pressed')).toBe('false');
	});

	it('stays lit when the node filtering the table is no longer in the data', () => {
		atWidth(1000);
		const { container } = render(NetworkFlow, { props: { ...PROPS, selected: { type: 'destination', id: 'AS0 Gone Ltd' } } });
		expect(container.querySelectorAll('path.rib.dim')).toHaveLength(0);
		expect(container.querySelectorAll('.faded')).toHaveLength(0);
	});

	it('shows the tooltip and lights the connected ribbons on focus', async () => {
		atWidth(1000);
		const { container, getByRole } = render(NetworkFlow, { props: PROPS });
		await fireEvent.focus(getByRole('button', { name: /^Apple Inc\.,/ }));
		await tick();
		expect(container.querySelector('.tip')?.textContent).toContain('Apple Inc. · US');
		expect(container.querySelector('.tip')?.textContent).toContain('50.0 MB · 50% of the flow · TCP 80%, UDP 20%');
		expect(container.querySelectorAll('path.rib.lit')).toHaveLength(2);
		await fireEvent.blur(getByRole('button', { name: /^Apple Inc\.,/ }));
		await tick();
		expect(container.querySelector('.tip')).toBeNull();
	});

	it('falls back to the reported figures, with a note, when the two searches disagree', () => {
		atWidth(1000);
		const { container, getByText, queryByText } = render(NetworkFlow, {
			props: { ...PROPS, links: [...PROPS.links, link('tcp', 'Unknown', 20 * MB)] },
		});
		expect(container.querySelector('.flow-chart')).toBeNull();
		expect(getByText(/don't add up exactly/)).not.toBeNull();
		expect(queryByText('Other destinations')).toBeNull();
	});

	it('switches table tabs, and Tab only stops on real buttons', async () => {
		atWidth(500);
		const { getByRole, container } = render(NetworkFlow, { props: PROPS });
		const panel = getByRole('tabpanel');
		expect(within(panel).getByRole('button', { name: 'Kitchen iPad' })).not.toBeNull();
		await fireEvent.click(getByRole('tab', { name: 'Protocols' }));
		expect(within(getByRole('tabpanel')).getByRole('button', { name: 'TCP' })).not.toBeNull();
		await fireEvent.click(getByRole('tab', { name: 'Destinations' }));
		const rowButtons = container.querySelectorAll('tbody button');
		expect([...rowButtons].map((b) => b.textContent)).toEqual(['Apple Inc.', 'Unknown']);
		expect(container.querySelectorAll('tbody .row-btn')).toHaveLength(0);
	});
});
