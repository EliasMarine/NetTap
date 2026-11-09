<!--
  HexDump.svelte: a packet's captured bytes, 8 to a row, with offset, hex and ASCII
  (NET-188, Main.dc "Raw bytes"). Only the chosen field's bytes are marked, and only when the
  daemon proved them against the bytes (`mark`). Everything renders as text.
-->
<script lang="ts">
	interface Props {
		/** The captured frame as hex digits */
		hex: string;
		/** [pos, size] in bytes */
		mark: [number, number] | null;
		/** What the mark is, for the screen-reader label */
		markLabel?: string;
	}

	let { hex, mark, markLabel = '' }: Props = $props();

	// OLD CODE START: 16 to a row needs ~380 px of mono text, but the desktop drawer (c-4) is ~320 px inside,
	// so every row was cut off and its ASCII hidden behind a sideways scroll. 8 fit on a desktop and a phone.
	// const PER_ROW = 16;
	// const FIRST_ROWS = 16;
	// OLD CODE END
	const PER_ROW = 8;
	// still the first 256 bytes
	const FIRST_ROWS = 32;

	let showAll = $state(false);

	const bytes = $derived((hex.replace(/[^0-9a-f]/gi, '').match(/.{2}/g) ?? []).map((b) => b.toLowerCase()));
	const rowCount = $derived(Math.ceil(bytes.length / PER_ROW));
	// A mark past the first rows opens them all, so the marked bytes are always on screen
	const visibleRows = $derived(showAll || (mark && mark[0] + mark[1] > FIRST_ROWS * PER_ROW) ? rowCount : Math.min(rowCount, FIRST_ROWS));

	const ascii = (b: string) => {
		const n = parseInt(b, 16);
		return n >= 0x20 && n < 0x7f ? String.fromCharCode(n) : '.';
	};

	/** One row as three runs: before, inside and after the mark. */
	function runs(row: number): { hex: string; text: string; marked: boolean }[] {
		const start = row * PER_ROW;
		const slice = bytes.slice(start, start + PER_ROW);
		const a = mark ? Math.max(0, mark[0] - start) : PER_ROW;
		const b = mark ? Math.min(slice.length, mark[0] + mark[1] - start) : PER_ROW;
		const parts = [
			{ from: 0, to: Math.min(a, slice.length), marked: false },
			{ from: Math.max(0, a), to: Math.max(0, b), marked: true },
			{ from: Math.max(0, b), to: slice.length, marked: false },
		];
		return parts
			.filter((p) => p.to > p.from)
			.map((p) => {
				const part = slice.slice(p.from, p.to);
				return { hex: part.join(' '), text: part.map(ascii).join(''), marked: p.marked };
			});
	}

	const label = $derived(
		`Raw bytes, ${bytes.length.toLocaleString('en-GB')} in all${mark ? `, with ${markLabel || 'the chosen field'} marked at bytes ${mark[0]} to ${mark[0] + mark[1] - 1}` : ''}`,
	);
</script>

<div class="hex" role="img" aria-label={label}>
	{#each Array.from({ length: visibleRows }, (_, i) => i) as row (row)}
		{@const parts = runs(row)}
		<span class="off">{(row * PER_ROW).toString(16).padStart(4, '0')}</span>
		<span class="hexrun">{#each parts as p, i (i)}{#if i > 0}{' '}{/if}{#if p.marked}<mark>{p.hex}</mark>{:else}{p.hex}{/if}{/each}</span>
		<span class="ascii">{#each parts as p, i (i)}{#if p.marked}<mark>{p.text}</mark>{:else}{p.text}{/if}{/each}</span>
	{/each}
</div>
{#if rowCount > visibleRows}
	<button class="btn more" type="button" onclick={() => (showAll = true)}>Show all {bytes.length.toLocaleString('en-GB')} bytes</button>
{/if}

<style>
	/* Layout glue: three mono columns; they fit the drawer at 8 to a row, and scroll sideways if a drawer is ever narrower */
	.hex {
		display: grid; grid-template-columns: auto auto auto; gap: 2px var(--sp-3); justify-content: start;
		font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-2);
		overflow-x: auto; padding: var(--sp-2); background: var(--surface-2); border-radius: var(--r-md);
	}
	.off { color: var(--text-3); }
	/* Not .bytes: system.css owns that name (a right-aligned flex column for byte cells) */
	.hexrun, .ascii { white-space: pre; }
	mark { background: color-mix(in srgb, var(--accent) 28%, transparent); color: var(--text-1); border-radius: var(--r-xs); }
	.more { margin-top: var(--sp-2); }
</style>
