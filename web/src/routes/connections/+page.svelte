<script lang="ts">
	import AnalysisPanel from '$components/tshark/AnalysisPanel.svelte';
</script>

<svelte:head>
	<title>Connections | NetTap</title>
</svelte:head>

<div class="connections-page">
	<div class="page-intro">
		<p class="text-muted">
			Analyze captured network traffic with TShark. Select a PCAP file, apply display filters,
			and inspect individual packets and their protocol layers.
		</p>
	</div>

	<AnalysisPanel />
</div>

<style>
	.connections-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.page-intro {
		max-width: 720px;
	}

	.page-intro p {
		font-size: var(--text-sm);
		line-height: var(--leading-relaxed);
	}
</style>
