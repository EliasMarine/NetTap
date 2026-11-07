<!--
  NET-188: /tools/tshark redirects to /packets (+page.ts), so this page no longer renders.
  The old components in $lib/components/tshark/ stay in place, unreferenced.
-->
<!-- OLD CODE START — NET-188: the old page asked for a PCAP path and Wireshark syntax and showed
     raw JSON; Packet analysis starts from a question and explains each packet
<script lang="ts">
	/** TShark packet analysis: the restyled AnalysisPanel as it is, under the page head. */
	import AnalysisPanel from '$lib/components/tshark/AnalysisPanel.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
</script>

<svelte:head>
	<title>TShark packet analysis | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">TShark packet analysis</h1>
		<p class="page-sub">Read saved PCAP files with Wireshark display filters, field by field and layer by layer.</p>
	</div>
</div>

<AnalysisPanel />
OLD CODE END -->
