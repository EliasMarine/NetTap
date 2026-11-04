import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import StatStrip from './StatStrip.svelte';

describe('StatStrip', () => {
	it('renders each label over its value, in order', () => {
		const { container } = render(StatStrip, {
			stats: [
				{ key: 'sessions', label: 'Sessions', value: '182,406' },
				{ key: 'data', label: 'Data', value: '39.2 GB' },
			],
		});
		const stats = container.querySelectorAll('.stats > .stat');
		expect(stats).toHaveLength(2);
		expect(stats[0].querySelector('.stat-k')).toHaveTextContent('Sessions');
		expect(stats[0].querySelector('.stat-v')).toHaveTextContent('182,406');
		expect(stats[1].querySelector('.stat-k')).toHaveTextContent('Data');
		expect(stats[1].querySelector('.stat-v')).toHaveTextContent('39.2 GB');
	});
});
