<script lang="ts">
	/**
	 * One Security posture category: what drives its score (the overview's own scoring, with this
	 * load's numbers), the devices and services behind it, what to change first, good habits and where
	 * to read more. Every figure comes from one snapshot over one window, replaced whole; a failed
	 * refresh of the same category keeps the last good one.
	 */
	import { onDestroy, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { getProtocolDistribution } from '$api/traffic';
	import { getAlertCount, getAlertTopSignatures } from '$api/alerts';
	import { getDeviceCount } from '$api/devices';
	import { getRiskScores } from '$api/risk';
	// OLD CODE: import { getInvestigationStats } from '$api/investigations'; (NET-308: alert follow-up)
	// OLD CODE: import { getNetworkIsolation } from '$api/iot'; (NET-308: a score input, checked)
	import { getCaptureMode, getCaptureStats } from '$api/capture';
	import { getIsolation, getPostureDetail } from '$api/posture';
	import { getRegistryDevices } from '$lib/api/devices-registry';
	import { namesByIp } from '$lib/utils/device-names';
	import { outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { fmt, rangeWindow } from '$lib/utils/drilldown';
	import { loadFailed } from '$lib/utils/load-failed';
	import { HEALTH_CHECKING, readHealth } from '$lib/utils/read-health';
	import { EMPTY_DATA, INPUT_NAMES, scoreCategories, type Input, type PostureData, type PostureInputs, type PostureSlug } from '$lib/posture/score';
	import { buildReport, EXTRAS, SEVERITY_RANK, type ExtraKey, type Finding, type PostureExtras, type ResolverRow, type Source } from '$lib/posture/report';
	import { GUIDES } from '$lib/posture/guides';
	import IPAddress from '$components/IPAddress.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';

	type Win = { from: string; to: string };

	/** The score inputs each category reads; the others keep their stand-ins and aren't requested. */
	const NEEDS: Record<PostureSlug, readonly Input[]> = {
		encryption: ['protocols'],
		'dns-security': ['protocols'],
		'patch-currency': ['protocols'],
		// OLD CODE: 'network-segmentation': ['devices', 'risk'], (NET-308: IoT isolation is the score)
		'network-segmentation': ['isolation'],
		// OLD CODE: 'alert-response': ['alerts', 'investigations', 'risk'], (NET-308)
		'alert-response': ['alerts', 'response', 'risk'],
		'monitoring-coverage': ['devices', 'risk'],
	};
	const INPUTS: Record<Input, { field: keyof PostureData; get: (w: Win) => Promise<unknown> }> = {
		protocols: { field: 'protocols', get: (w) => getProtocolDistribution(w) },
		alerts: { field: 'alertCounts', get: (w) => getAlertCount(w) },
		devices: { field: 'deviceCount', get: (w) => getDeviceCount(w) },
		risk: { field: 'riskScores', get: (w) => getRiskScores(w) },
		// OLD CODE START — NET-308: all-time investigation stats
		// // all time: the stats endpoint takes no window
		// investigations: { field: 'investigationStats', get: () => getInvestigationStats() },
		// OLD CODE END
		isolation: { field: 'isolation', get: (w) => getIsolation(w) },
		response: { field: 'alertResponse', get: (w) => getPostureDetail('alert-response', w) },
	};
	const EXTRA_GET: Record<ExtraKey, (w: Win) => Promise<unknown>> = {
		encryption: (w) => getPostureDetail('encryption', w),
		'dns-security': (w) => getPostureDetail('dns-security', w),
		'patch-currency': (w) => getPostureDetail('patch-currency', w),
		// OLD CODE: isolation: (w) => getNetworkIsolation(w), (NET-308: a score input now, INPUTS.isolation)
		signatures: (w) => getAlertTopSignatures({ ...w, limit: 10 }),
		mode: () => getCaptureMode(),
		stats: () => getCaptureStats(),
	};
	/** Each category's name before anything loads */
	const NAMES = Object.fromEntries(scoreCategories({ ...EMPTY_DATA, failed: [], health: HEALTH_CHECKING }).map((c) => [c.slug, c.name])) as Record<PostureSlug, string>;

	/** The param matcher lets only the six slugs through */
	const slug = $derived(($page.params as Record<string, string>).category as PostureSlug);
	const guide = $derived(GUIDES[slug]);

	interface Snapshot {
		slug: PostureSlug;
		window: Win;
		inputs: PostureInputs;
		extras: PostureExtras;
		failed: ExtraKey[];
		names: ReadonlyMap<string, string>;
	}
	let loaded = $state<Snapshot | null>(null);
	/** Why the last load of this category failed, in part or whole */
	let failure = $state<string | null>(null);
	/** A same-category refresh failed and the last good snapshot is still on screen */
	let stale = $state(false);
	/** The slug of the snapshot on screen (not reactive: only the loader reads it) */
	let loadedSlug = '';

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);

	$effect(() => {
		void slug; // another category
		untrack(() => refresh.run());
	});

	const reason = (r: PromiseSettledResult<unknown>) => (r.status === 'rejected' && r.reason instanceof Error ? r.reason.message : '');

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const target = slug;
		// A refresh of the same category keeps its last good snapshot; another category must not show it
		if (target !== loadedSlug) {
			loaded = null;
			failure = null;
			stale = false;
			loadedSlug = '';
		}
		const win = rangeWindow(24);
		const needs = NEEDS[target];
		const extraKeys = EXTRAS[target];
		const [inputResults, extraResults, health, names] = await Promise.all([
			Promise.allSettled(needs.map((k) => INPUTS[k].get(win))),
			Promise.allSettled(extraKeys.map((k) => EXTRA_GET[k](win))),
			readHealth(),
			// names only: a failure drops them and isn't part of the page's outcome
			getRegistryDevices({ limit: 200 }).then((r) => namesByIp(r.devices), () => new Map<string, string>()),
		]);
		// an older request finishing late, or for a category the page has left, is dropped
		if (!guard.current(g) || target !== slug) return 'skipped';
		const results = [...inputResults, ...extraResults];
		const rejected = results.filter((r) => r.status === 'rejected');
		failure = rejected.length ? rejected.map(reason).find(Boolean) || 'Check that NetTap is running on the System page, then try again.' : null;
		// Same category, something failed: keep the whole last snapshot (score, breakdown and link window together)
		stale = !!(rejected.length && loaded && loadedSlug === target);
		if (stale) return outcome(results);

		const data = { ...EMPTY_DATA } as Record<keyof PostureData, unknown>;
		needs.forEach((k, i) => {
			const r = inputResults[i];
			if (r.status === 'fulfilled') data[INPUTS[k].field] = r.value;
		});
		const extras: Record<string, unknown> = {};
		extraKeys.forEach((k, i) => {
			const r = extraResults[i];
			if (r.status === 'fulfilled') extras[k] = r.value;
		});
		loaded = {
			slug: target,
			window: win,
			inputs: { ...(data as unknown as PostureData), failed: needs.filter((_, i) => inputResults[i].status === 'rejected'), health },
			extras: extras as PostureExtras,
			failed: extraKeys.filter((_, i) => extraResults[i].status === 'rejected'),
			names,
		};
		loadedSlug = target;
		return outcome(results);
	}

	const category = $derived(loaded ? scoreCategories(loaded.inputs).find((c) => c.slug === loaded!.slug)! : null);
	const report = $derived(loaded && category ? buildReport(loaded.slug, { ...loaded, category }) : null);
	const unmeasured = $derived(report?.sources.filter((s) => s.state !== 'measured') ?? []);
	const allFailed = $derived(!!report && report.sources.every((s) => s.state === 'failed'));

	const findingColumns: Column<Finding>[] = [
		{ key: 'severity', label: 'Severity', sortValue: (f) => SEVERITY_RANK[f.severity], cell: severityCell },
		{ key: 'title', label: 'Finding', cell: findingCell },
		{ key: 'devices', label: 'Devices', sortValue: (f) => f.devices[0]?.name ?? f.devices[0]?.ip ?? '', cell: devicesCell },
		{ key: 'count', label: 'Count', numeric: true, sortValue: (f) => f.count ?? -1, cell: countCell },
		{ key: 'fix', label: 'How to fix', class: 'wrap' },
	];
	const resolverColumns: Column<ResolverRow>[] = [
		{ key: 'ip', label: 'Resolver', cell: resolverCell },
		{ key: 'org', label: 'Network' },
		{ key: 'kind', label: 'Kind' },
		{ key: 'scope', label: 'Address' },
		{ key: 'count', label: 'Lookups', numeric: true, cell: lookupsCell },
	];

	/** A step or note link's words, by the page it opens */
	const LINK_WORDS: Record<string, string> = {
		'/logs': 'Open in Log Explorer',
		'/dns': 'Open DNS',
		'/devices': 'Open Devices',
		'/investigations': 'Open Investigations',
		'/system': 'Open System',
		'/infrastructure': 'Open Infrastructure',
	};
	const linkWords = (href: string) => LINK_WORDS[href.split('?')[0]] ?? 'Open';
</script>

{#snippet severityCell(f: Finding)}<SeverityPill level={f.severity} />{/snippet}
{#snippet findingCell(f: Finding)}
	<div class="finding">
		{#if f.href}<a href={f.href}>{f.title}</a>{:else}<strong>{f.title}</strong>{/if}
		<span class="dim">{f.detail}</span>
	</div>
{/snippet}
{#snippet devicesCell(f: Finding)}
	{#if f.devices.length === 0}<span class="dim">—</span>{/if}
	{#each f.devices as d (d.ip)}
		<div class="device">
			{#if d.name}<span class="who-name">{d.name}</span>{/if}
			<IPAddress ip={d.ip} />
		</div>
	{/each}
{/snippet}
{#snippet countCell(f: Finding)}{f.count === undefined ? '—' : fmt(f.count)}{/snippet}
{#snippet resolverCell(r: ResolverRow)}<IPAddress ip={r.ip} />{/snippet}
{#snippet lookupsCell(r: ResolverRow)}{fmt(r.count)}{/snippet}

{#snippet sourceLines(sources: Source[])}
	{#each sources as s (s.key)}
		<p class="notice" class:is-warn={s.state === 'failed'} role="status"><Icon name={s.state === 'failed' ? 'warn' : 'empty'} /><span><strong>{s.label}:</strong> {s.note}</span></p>
	{/each}
{/snippet}

{#snippet loadingOr(what: string)}
	{#if !loaded && !failure}
		<CardState state="loading" title="Loading {what}" />
	{:else}
		<CardState state="error" title={loadFailed(what)} message={failure ?? undefined} actionLabel="Try again" onaction={() => refresh.run()} />
	{/if}
{/snippet}

<svelte:head>
	<title>{NAMES[slug]} | Security posture | NetTap</title>
</svelte:head>

<header class="page-head">
	<div>
		<p class="eyebrow"><a href="/compliance">Security posture</a></p>
		<h1 class="page-title">{NAMES[slug]}</h1>
		<p class="page-sub">{guide.summary} · last 24 hours</p>
	</div>
</header>

<div class="grid">
	{#if stale}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" /><span>{loadFailed('this category', true)} {failure}</span></p>
	{/if}

	{#if report}
		{#each report.kpis as k (k.key)}
			<KpiCard class="c-4" label={k.label} icon={k.icon} value={k.value} unit={k.unit} sub={k.sub} />
		{/each}
	{:else}
		<KpiCard class="c-4" label="Score" icon="check" value="—" sub={failure ? "Couldn't compute" : 'Loading…'} />
	{/if}

	<Card class="c-8" hero title="What drives this score" sub="The overview's own sum, with the last 24 hours' numbers">
		{#if !report || !category || category.score === null}
			{#if category?.score === null}
				<CardState state="error" title={loadFailed(category.needs.filter((n) => loaded?.inputs.failed.includes(n)).map((n) => INPUT_NAMES[n]).join(' or '))} message={failure ?? undefined} actionLabel="Try again" onaction={() => refresh.run()} />
			{:else}
				{@render loadingOr('the score')}
			{/if}
		{:else}
			<div class="stack">
				<p class="formula num">{report.drivers.formula}</p>
				<ul class="lines">
					{#each report.drivers.counts as line (line)}<li>{line}</li>{/each}
				</ul>
				{#if report.drivers.bars.length > 0}
					<BarList items={report.drivers.bars} />
				{:else}
					{@render sourceLines(unmeasured)}
				{/if}
				{#if report.drivers.resolvers && report.drivers.resolvers.length > 0}
					<DataTable columns={resolverColumns} rows={report.drivers.resolvers} ariaLabel="DNS resolvers" rowKey={(r) => r.key} initialSort={{ key: 'count', dir: 'desc' }} />
				{/if}
				<div>
					<h3 class="eyebrow">What the score can't see</h3>
					<ul class="lines">
						{#each report.drivers.limits as line (line)}<li>{line}</li>{/each}
					</ul>
				</div>
			</div>
		{/if}
	</Card>

	<Card class="c-4" title="What this is and why it matters">
		<div class="stack">
			<p>{guide.what}</p>
			<p>{guide.why}</p>
		</div>
	</Card>

	<Card class="c-12" title="Findings" sub="What NetTap saw behind the score · last 24 hours">
		{#if !report || allFailed}
			{@render loadingOr('the findings')}
		{:else}
			<div class="stack">
				{#if report.findings.length > 0}
					<DataTable columns={findingColumns} rows={report.findings} ariaLabel="{NAMES[slug]} findings" rowKey={(f) => f.key} />
					{#each report.notes as note (note.text)}
						<p class="dim small">{note.text}{#if note.href} <a href={note.href}>{linkWords(note.href)}</a>{/if}</p>
					{/each}
				{:else if unmeasured.length === 0}
					<CardState state="empty" icon="check" title="No problems found in the last 24 hours" />
				{:else}
					<CardState state="empty" title="Nothing to report from what NetTap could measure" />
				{/if}
				{@render sourceLines(unmeasured)}
			</div>
		{/if}
	</Card>

	<Card class="c-8" title="How to improve" sub="Highest priority first, from what NetTap saw">
		{#if !report || (report.steps.length === 0 && report.sources.some((s) => s.state === 'failed'))}
			{@render loadingOr('the recommendations')}
		{:else if report.steps.length === 0}
			<CardState state="empty" icon="check" title="Nothing to change from what NetTap saw" message={unmeasured.length ? 'Some of the data couldn’t be measured or loaded; see Findings.' : undefined} />
		{:else}
			<ol class="steps">
				{#each report.steps as step, i (i)}
					<li>
						<SeverityPill level={step.priority} />
						<span>{step.text}{#if step.href} <a href={step.href}>{linkWords(step.href)}</a>{/if}</span>
					</li>
				{/each}
			</ol>
		{/if}
	</Card>

	<Card class="c-4" title="Good habits">
		<ul class="lines">
			{#each guide.practices as practice (practice)}<li>{practice}</li>{/each}
		</ul>
	</Card>

	<Card class="c-12" title="Learn more" sub="Guidance from security agencies and the projects behind the tools · opens in a new tab">
		<ul class="learn">
			{#each guide.learnMore as link (link.url)}
				<li><a href={link.url} target="_blank" rel="noopener noreferrer">{link.label}</a> <span class="dim">{link.source}</span></li>
			{/each}
		</ul>
	</Card>
</div>

<style>
	.formula {
		font-size: var(--text-md);
		color: var(--text-1);
		font-weight: 600;
	}

	.lines,
	.learn {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		margin: 0;
		padding-left: var(--sp-5);
		color: var(--text-2);
		font-size: var(--text-sm);
	}

	.steps {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		margin: 0;
		padding: 0;
		list-style: none;
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.steps li {
		display: flex;
		align-items: flex-start;
		gap: var(--sp-3);
	}

	.finding,
	.device {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		min-width: 0;
	}

	.finding {
		white-space: normal;
		min-width: 16em;
	}

	.small {
		font-size: var(--text-xs);
	}

	.grid :global(td.wrap) {
		white-space: normal;
		min-width: 14em;
	}
</style>
