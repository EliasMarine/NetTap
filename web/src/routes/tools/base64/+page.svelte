<script lang="ts">
	/** Base64 and hex converter: runs in the browser, no API calls. An input card beside an output card. */
	import Card from '$lib/components/ui/Card.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	// ---------------------------------------------------------------------------
	// Operations
	// ---------------------------------------------------------------------------

	type Operation = 'base64-encode' | 'base64-decode' | 'hex-encode' | 'hex-decode' | 'url-encode' | 'url-decode';

	const operations: { value: Operation; label: string }[] = [
		{ value: 'base64-encode', label: 'Base64 encode' },
		{ value: 'base64-decode', label: 'Base64 decode' },
		{ value: 'hex-encode', label: 'Hex encode' },
		{ value: 'hex-decode', label: 'Hex decode' },
		{ value: 'url-encode', label: 'URL encode' },
		{ value: 'url-decode', label: 'URL decode' },
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let input = $state('');
	let operation = $state<Operation>('base64-encode');
	let copyFeedback = $state(false);

	// ---------------------------------------------------------------------------
	// Conversion logic
	// ---------------------------------------------------------------------------

	function convert(text: string, op: Operation): { output: string; error: string } {
		if (!text) return { output: '', error: '' };

		try {
			switch (op) {
				case 'base64-encode':
					return { output: btoa(unescape(encodeURIComponent(text))), error: '' };
				case 'base64-decode':
					return { output: decodeURIComponent(escape(atob(text.trim()))), error: '' };
				case 'hex-encode': {
					const encoder = new TextEncoder();
					const bytes = encoder.encode(text);
					const hex = Array.from(bytes)
						.map((b) => b.toString(16).padStart(2, '0'))
						.join('');
					return { output: hex, error: '' };
				}
				case 'hex-decode': {
					const cleaned = text.replace(/\s/g, '');
					if (!/^[0-9a-fA-F]*$/.test(cleaned)) {
						return { output: '', error: 'Invalid hex input' };
					}
					if (cleaned.length % 2 !== 0) {
						return { output: '', error: 'Hex string must have even length' };
					}
					const bytes = new Uint8Array(
						cleaned.match(/.{2}/g)!.map((byte) => parseInt(byte, 16))
					);
					const decoder = new TextDecoder();
					return { output: decoder.decode(bytes), error: '' };
				}
				case 'url-encode':
					return { output: encodeURIComponent(text), error: '' };
				case 'url-decode':
					return { output: decodeURIComponent(text), error: '' };
				default:
					return { output: '', error: 'Unknown operation' };
			}
		} catch (e) {
			return { output: '', error: e instanceof Error ? e.message : 'Conversion failed' };
		}
	}

	let result = $derived(convert(input, operation));

	async function copyToClipboard() {
		if (!result.output) return;
		try {
			await navigator.clipboard.writeText(result.output);
			copyFeedback = true;
			setTimeout(() => { copyFeedback = false; }, 2000);
		} catch {
			// Clipboard API may not be available
		}
	}
</script>

<svelte:head>
	<title>Base64 and hex converter | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">Base64 and hex converter</h1>
		<p class="page-sub">Encode and decode Base64, hex and URL text. No data leaves your browser.</p>
	</div>
</div>

<div class="grid">
	<Card title="Input" sub="Text to convert · {input.length} chars" class="c-6">
		<div class="field form-group">
			<label class="label" for="b64-op">Operation</label>
			<select id="b64-op" class="select" bind:value={operation}>
				{#each operations as op}
					<option value={op.value}>{op.label}</option>
				{/each}
			</select>
		</div>
		<div class="field">
			<label class="label" for="b64-input">Text</label>
			<textarea id="b64-input" class="textarea mono" placeholder="Enter text to convert…" bind:value={input} rows="12"></textarea>
		</div>
	</Card>

	<Card title="Output" sub="Converted text · {result.output.length} chars" class="c-6">
		{#snippet actions()}
			<button class="btn" type="button" onclick={copyToClipboard} disabled={!result.output} title="Copy to clipboard">
				{#if copyFeedback}<Icon name="check" />Copied{:else}Copy{/if}
			</button>
		{/snippet}
		{#if result.error}
			<p class="notice is-error" role="alert"><Icon name="warn" />{result.error}</p>
		{:else}
			<label class="sr-only" for="b64-output">Output</label>
			<textarea id="b64-output" class="textarea mono" readonly rows="12" value={result.output}></textarea>
		{/if}
	</Card>
</div>
