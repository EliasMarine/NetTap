<!--
  DownloadForm.svelte: "Download these packets" as a plain form post (NET-188), so the browser
  shows its own download progress. The manifest goes back exactly as the search returned it; the
  proxy aborts the response if the daemon stops part-way, so a short file is never kept.
-->
<script lang="ts">
	import type { PacketManifest } from '$lib/api/packets';
	import Icon from '$lib/components/ui/Icon.svelte';

	let { manifest }: { manifest: PacketManifest } = $props();

	const count = $derived(manifest.frames.length);
</script>

<form method="POST" action="/api/packets/download">
	<input type="hidden" name="manifest" value={JSON.stringify(manifest)} />
	<button class="btn" type="submit" disabled={count === 0}>
		<Icon name="download" />Download {count === 1 ? 'this packet' : `these ${count.toLocaleString('en-GB')} packets`}
	</button>
</form>

<style>
	form { display: contents; }
</style>
