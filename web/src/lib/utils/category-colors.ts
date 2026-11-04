/**
 * Traffic category → colour, shared by Home, device detail and the category page.
 * Categories are decorative, so they use data tokens. The design system has six
 * (data-1..6), so the six main categories get one each and the rest use text-3 beside
 * their label (PLAN.md §5.1). Charts that colour by series use topSeries() instead.
 * Only "suspicious" carries meaning, so it uses a severity token. Keys match
 * CATEGORIES in daemon/services/traffic_classifier.py.
 */
export const CATEGORY_COLORS: Record<string, string> = {
	streaming: 'var(--data-1)',
	gaming: 'var(--data-2)',
	social: 'var(--data-3)',
	communication: 'var(--data-4)',
	work: 'var(--data-5)',
	iot: 'var(--data-6)',
	cloud: 'var(--text-3)',
	file_transfer: 'var(--text-3)',
	web: 'var(--text-3)',
	email: 'var(--text-3)',
	security: 'var(--text-3)',
	shopping: 'var(--text-3)',
	news: 'var(--text-3)',
	updates: 'var(--text-3)',
	dns: 'var(--text-3)',
	ads: 'var(--text-3)',
	other: 'var(--text-3)',
	suspicious: 'var(--sev-high)',
};
