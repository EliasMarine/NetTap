import type { Attachment } from 'svelte/attachments';

/**
 * Reports an element's width (and height, for a chart that fills its card) now and on every
 * resize, so a chart redraws to its container. Where ResizeObserver doesn't exist (jsdom) it
 * reports once and the chart keeps that size.
 */
export function observeWidth(onWidth: (width: number, height: number) => void): Attachment<HTMLElement> {
	return (el) => {
		onWidth(el.clientWidth, el.clientHeight);
		if (typeof ResizeObserver === 'undefined') return;
		const observer = new ResizeObserver(([entry]) => onWidth(entry.contentRect.width, entry.contentRect.height));
		observer.observe(el);
		return () => observer.disconnect();
	};
}
