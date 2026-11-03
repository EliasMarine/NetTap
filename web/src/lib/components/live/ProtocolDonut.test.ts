import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ProtocolDonut from './ProtocolDonut.svelte';

const PROTOCOLS = { tcp: 36.4, udp: 61.2, icmp: 2.4, other: 0 };

describe('ProtocolDonut centre', () => {
	it('shows the connections behind the percentages as the total', () => {
		render(ProtocolDonut, { protocols: PROTOCOLS, activeProtocol: null, onclick: () => {}, connections: 1690 });
		expect(screen.getByText('1,690')).toBeInTheDocument();
	});

	it('shows a dash, not the protocol count, when the total is unknown', () => {
		render(ProtocolDonut, { protocols: PROTOCOLS, activeProtocol: null, onclick: () => {} });
		expect(screen.getByText('—')).toBeInTheDocument();
		// "3 total" was the number of protocols with traffic
		expect(screen.queryByText('3')).not.toBeInTheDocument();
	});
});
