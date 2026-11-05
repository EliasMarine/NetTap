/**
 * Runs in the page (via `page.evaluate`), so it must not use imports or outer variables.
 * Lists every severity count that spills out of its `.sev-count` tile and every tile that runs
 * into the next one on the same row.
 */
export function findTileSpills(): string[] {
	return [...document.querySelectorAll('.sev-count')].flatMap((tile, i, all) => {
		const t = tile.getBoundingClientRect();
		const n = tile.querySelector('b')?.getBoundingClientRect();
		const next = all[i + 1]?.getBoundingClientRect();
		const name = tile.textContent?.trim();
		return [
			...(n && n.right > t.right + 0.5 ? [`${name}: the count spills out of its tile`] : []),
			...(next && next.top === t.top && t.right > next.left + 0.5 ? [`${name}: the tile overlaps the next one`] : []),
		];
	});
}
