<script lang="ts">
	const statusCards = [
		{
			title: 'Traffic',
			value: '--',
			unit: 'Mbps',
			status: 'idle',
			description: 'Current throughput',
		},
		{
			title: 'Alerts',
			value: '--',
			unit: '',
			status: 'idle',
			description: 'Active alerts (24h)',
		},
		{
			title: 'Storage',
			value: '--',
			unit: '%',
			status: 'idle',
			description: 'Disk utilization',
		},
		{
			title: 'System',
			value: '--',
			unit: '',
			status: 'idle',
			description: 'Health status',
		},
	];

	function badgeClass(status: string): string {
		switch (status) {
			case 'online':
			case 'healthy':
				return 'badge badge-success';
			case 'warning':
				return 'badge badge-warning';
			case 'critical':
			case 'offline':
				return 'badge badge-danger';
			default:
				return 'badge';
		}
	}
</script>

<svelte:head>
	<title>Dashboard | NetTap</title>
</svelte:head>

<div class="dashboard">
	<!-- Setup banner -->
	<div class="alert alert-info setup-banner">
		<strong>Setup required</strong> — Run the setup wizard to configure network interfaces and complete initial setup.
		<a href="/setup" class="btn btn-primary btn-sm" style="margin-left: var(--space-md);">Start Setup</a>
	</div>

	<!-- Welcome -->
	<div class="welcome-section">
		<h2>Welcome to NetTap</h2>
		<p class="text-muted">Network visibility at a glance. Monitor traffic, detect threats, and manage your appliance.</p>
	</div>

	<!-- Status Cards -->
	<div class="grid grid-cols-4 status-grid">
		{#each statusCards as card}
			<div class="card status-card">
				<div class="card-header">
					<span class="card-subtitle">{card.title}</span>
					<span class={badgeClass(card.status)}>
						{card.status}
					</span>
				</div>
				<div class="card-value">
					{card.value}<span class="card-unit">{card.unit}</span>
				</div>
				<p class="card-description">{card.description}</p>
			</div>
		{/each}
	</div>

	<!-- Placeholder sections -->
	<div class="grid grid-cols-2 charts-grid">
		<div class="card">
			<div class="card-header">
				<span class="card-title">Traffic Overview</span>
			</div>
			<div class="placeholder-chart">
				<p class="text-muted">Traffic chart will appear here once monitoring is active.</p>
			</div>
		</div>

		<div class="card">
			<div class="card-header">
				<span class="card-title">Recent Alerts</span>
			</div>
			<div class="placeholder-chart">
				<p class="text-muted">Alert feed will appear here once Suricata is running.</p>
			</div>
		</div>
	</div>
</div>

<style>
	.dashboard {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.setup-banner {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-sm);
	}

	.welcome-section h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.status-grid {
		margin-top: var(--space-sm);
	}

	.status-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.card-unit {
		font-size: var(--text-lg);
		font-weight: 400;
		color: var(--text-secondary);
		margin-left: var(--space-xs);
	}

	.card-description {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.charts-grid {
		margin-top: var(--space-sm);
	}

	.placeholder-chart {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 200px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		padding: var(--space-lg);
	}
</style>
