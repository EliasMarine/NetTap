import { describe, it, expect } from 'vitest';
import { outcome } from './load-outcome';

const ok: PromiseSettledResult<number> = { status: 'fulfilled', value: 1 };
const no: PromiseSettledResult<number> = { status: 'rejected', reason: new Error('HTTP 503') };

describe('outcome', () => {
	it('is ok when every request succeeded', () => expect(outcome([ok, ok])).toBe('ok'));
	it('is partial when some failed', () => expect(outcome([ok, no])).toBe('partial'));
	it('is failed when all failed', () => expect(outcome([no, no])).toBe('failed'));
});
