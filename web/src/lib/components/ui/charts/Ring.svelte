<!--
  Ring: a single accent arc over a surface-3 track, the score in the centre (trust score).
  Values are clamped to 0–100; at 0 no arc is drawn (a round cap would leave a dot).
-->
<script lang="ts">
	let { value, label = 'of 100', ariaLabel }: { value: number; label?: string; ariaLabel: string } = $props();

	const SIZE = 128;
	const STROKE = 11;
	const c = SIZE / 2;
	const r = c - STROKE / 2 - 1;
	const C = 2 * Math.PI * r;

	const score = $derived(Number.isFinite(value) ? Math.round(Math.max(0, Math.min(100, value))) : 0);
</script>

<svg viewBox="0 0 {SIZE} {SIZE}" width={SIZE} height={SIZE} role="img" aria-label={ariaLabel}>
	<circle class="track" cx={c} cy={c} r={r.toFixed(2)} stroke-width={STROKE} />
	{#if score > 0}
		<circle
			class="prog"
			cx={c}
			cy={c}
			r={r.toFixed(2)}
			stroke-width={STROKE}
			stroke-dasharray="{((C * score) / 100).toFixed(2)} {C.toFixed(2)}"
			transform="rotate(-90 {c} {c})"
		/>
	{/if}
	<text class="d-num" x={c} y={c + 6} text-anchor="middle">{score}</text>
	<text class="d-lbl" x={c} y={c + 25} text-anchor="middle">{label}</text>
</svg>

<style>
	/* In .trust-top (a flex row) the svg shrank to 58 px beside long text; it keeps its size */
	svg {
		flex: none;
	}
</style>
