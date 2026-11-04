/**
 * Traffic category → colour, shared by Home, device detail and the category page.
 * Categories are decorative, so they use data tokens. Only "suspicious" carries
 * meaning, so it uses a severity token. Keys match CATEGORIES in
 * daemon/services/traffic_classifier.py.
 */
export const CATEGORY_COLORS: Record<string, string> = {
	streaming: 'var(--data-1)',
	gaming: 'var(--data-2)',
	social: 'var(--data-3)',
	communication: 'var(--data-4)',
	work: 'var(--data-5)',
	iot: 'var(--data-6)',
	cloud: 'var(--data-7)',
	file_transfer: 'var(--data-8)',
	web: 'var(--data-2)',
	email: 'var(--data-6)',
	security: 'var(--data-5)',
	shopping: 'var(--data-3)',
	news: 'var(--data-4)',
	updates: 'var(--data-7)',
	dns: 'var(--text-3)',
	ads: 'var(--text-3)',
	other: 'var(--text-3)',
	suspicious: 'var(--sev-high)',
};
