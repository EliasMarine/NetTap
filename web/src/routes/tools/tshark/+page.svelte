<script lang="ts">
	import AnalysisPanel from '$lib/components/tshark/AnalysisPanel.svelte';
</script>

<svelte:head>
	<title>TShark Packet Analysis | NetTap</title>
</svelte:head>

<div class="tshark-page">
	<div class="back-nav">
		<a href="/tools" class="back-link">
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
			</svg>
			Back to Tools
		</a>
	</div>

	<AnalysisPanel />
</div>

<style>
	.tshark-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.back-nav {
		display: flex;
	}

	.back-link {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 6px 14px;
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		color: var(--text-secondary);
		font-size: var(--text-sm);
		font-weight: 500;
		text-decoration: none;
		transition: all var(--transition-fast);
	}

	.back-link:hover {
		background: var(--bg-tertiary);
		color: var(--text-primary);
		border-color: var(--border-default);
		text-decoration: none;
	}
</style>
