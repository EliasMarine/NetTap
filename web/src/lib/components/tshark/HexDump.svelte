<script lang="ts">
	interface Props {
		rawHex?: string | null;
		highlightStart?: number;
		highlightEnd?: number;
	}

	let { rawHex = null, highlightStart = -1, highlightEnd = -1 }: Props = $props();

	interface HexRow {
		offset: string;
		hexPairs: string[];
		ascii: string;
	}

	let rows = $derived<HexRow[]>(parseHex(rawHex));

	function parseHex(hex: string | null | undefined): HexRow[] {
		if (!hex) return [];

		const clean = hex.replace(/\s/g, '');
		const bytes: number[] = [];
		for (let i = 0; i < clean.length; i += 2) {
			bytes.push(parseInt(clean.substring(i, i + 2), 16));
		}

		const result: HexRow[] = [];
		for (let i = 0; i < bytes.length; i += 16) {
			const chunk = bytes.slice(i, i + 16);
			const offset = i.toString(16).padStart(4, '0');
			const hexPairs = chunk.map((b) => b.toString(16).padStart(2, '0'));
			const ascii = chunk
				.map((b) => (b >= 0x20 && b <= 0x7e ? String.fromCharCode(b) : '.'))
				.join('');
			result.push({ offset, hexPairs, ascii });
		}
		return result;
	}
</script>

<div class="hex-dump">
	{#if rows.length === 0}
		<div class="empty-state">
			<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
				<rect x="2" y="3" width="20" height="18" rx="2" />
				<line x1="8" y1="7" x2="16" y2="7" />
				<line x1="8" y1="11" x2="16" y2="11" />
				<line x1="8" y1="15" x2="12" y2="15" />
			</svg>
			<span>Select a packet to view hex dump</span>
		</div>
	{:else}
		<div class="hex-content">
			{#each rows as row, rowIdx}
				<div class="hex-row">
					<span class="hex-offset">{row.offset}</span>
					<span class="hex-bytes">
						{#each row.hexPairs as pair, pairIdx}
							{@const byteOffset = rowIdx * 16 + pairIdx}
							<span
								class="hex-byte"
								class:highlighted={byteOffset >= highlightStart && byteOffset < highlightEnd}
							>{pair}</span>
							{#if pairIdx === 7}<span class="hex-gap"></span>{/if}
						{/each}
					</span>
					<span class="hex-ascii">{row.ascii}</span>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.hex-dump {
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		background: var(--surface-1);
		height: 100%;
		overflow-y: auto;
		font-family: var(--font-mono);
		font-size: 12px;
		line-height: 1.6;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-8) var(--sp-6);
		color: var(--text-3);
		font-size: var(--text-sm);
		font-family: var(--font-body, sans-serif);
		text-align: center;
	}

	.empty-state svg {
		opacity: 0.5;
	}

	.hex-content {
		padding: var(--sp-2) var(--sp-4);
	}

	.hex-row {
		display: flex;
		gap: var(--sp-4);
		white-space: pre;
	}

	.hex-offset {
		color: var(--text-3);
		flex-shrink: 0;
		width: 4ch;
	}

	.hex-bytes {
		flex-shrink: 0;
		display: flex;
		gap: 4px;
	}

	.hex-gap {
		width: 4px;
	}

	.hex-byte {
		color: var(--text-1);
	}

	.hex-byte.highlighted {
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
		border-radius: 2px;
	}

	.hex-ascii {
		color: var(--text-2);
		flex-shrink: 0;
	}
</style>
