import type { Attachment } from 'svelte/attachments';

/**
 * Reports an element's width now and on every resize, so a chart redraws to its container.
 * Where ResizeObserver doesn't exist (jsdom) it reports once and the chart keeps that width.
 */
export function observeWidth(onWidth: (width: number) => void): Attachment<HTMLElement> {
	return (el) => {
		onWidth(el.clientWidth);
		if (typeof ResizeObserver === 'undefined') return;
		const observer = new ResizeObserver(([entry]) => onWidth(entry.contentRect.width));
		observer.observe(el);
		return () => observer.disconnect();
	};
}
