/** "15 of 4,213": how many rows are shown out of the true total (#96: lists are capped, totals are not). */
export function partOfWhole(shown: number, total: number): string {
	return `${shown.toLocaleString('en-US')} of ${total.toLocaleString('en-US')}`;
}
