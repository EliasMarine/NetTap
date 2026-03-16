import { json } from '@sveltejs/kit';
import { sendNotification } from '$lib/server/notifications.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET = async () => {
    // Fetch smart alerts (critical + high only)
    const res = await daemonFetch('/api/alerts/smart?limit=50');
    const data = await res.json().catch(() => ({ alerts: [] }));
    const alerts = data.alerts || [];

    if (alerts.length === 0) {
        return json({ notifications_created: 0 });
    }

    // Batch by category
    const batches: Record<string, { count: number; devices: Set<string>; topSig: string; maxSev: number; events: number }> = {};

    for (const alert of alerts) {
        const cat = alert.category_label || 'Unknown';
        if (!batches[cat]) {
            batches[cat] = { count: 0, devices: new Set(), topSig: alert.signature, maxSev: alert.severity, events: 0 };
        }
        batches[cat].count++;
        batches[cat].events += alert.count || 1;
        if (alert.source_ip) batches[cat].devices.add(alert.source_ip);
        if (alert.destination_ip) batches[cat].devices.add(alert.destination_ip);
        if (alert.severity < batches[cat].maxSev) {
            batches[cat].maxSev = alert.severity;
            batches[cat].topSig = alert.signature;
        }
    }

    // Send notifications for critical/high batches only
    let created = 0;
    for (const [category, batch] of Object.entries(batches)) {
        if (batch.maxSev > 2) continue; // Skip medium/low

        const severity = batch.maxSev <= 1 ? 'critical' : 'high';

        try {
            await sendNotification({
                type: 'alert',
                severity: severity as 'critical' | 'high',
                title: `${batch.count} ${category} alert${batch.count > 1 ? 's' : ''}`,
                message: `${batch.devices.size} device(s) affected \u00b7 ${batch.events.toLocaleString()} events \u00b7 Top: ${batch.topSig}`,
                source: { signature: batch.topSig },
            });
            created++;
        } catch {
            // Notification dispatch failed — continue with others
        }
    }

    return json({ notifications_created: created, categories: Object.keys(batches).length });
};
