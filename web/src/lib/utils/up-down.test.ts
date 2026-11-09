import { describe, expect, it } from 'vitest';
import { upDownLocal } from './up-down';

const fmt = (n: number) => `${n} B`;

describe('upDownLocal (NET-226)', () => {
	it('names download, upload and local', () => {
		expect(upDownLocal({ download_bytes: 5, upload_bytes: 3, local_bytes: 2 }, fmt)).toBe('↓ 5 B down · ↑ 3 B up · 2 B local');
	});
	it('leaves local out when nothing stayed on the network, and the words out for a tooltip', () => {
		expect(upDownLocal({ download_bytes: 5, upload_bytes: 3, local_bytes: 0 }, fmt, false)).toBe('↓ 5 B · ↑ 3 B');
	});
});
