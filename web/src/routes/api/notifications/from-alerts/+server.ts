import { json } from '@sveltejs/kit';
import { getNotifications, MAX_STORED_NOTIFICATIONS, sendNotification } from '$lib/server/notifications.js';
import { daemonFetch } from '$lib/server/daemon.js';
import { fmt } from '$lib/utils/drilldown';

const DAY_MS = 24 * 60 * 60 * 1000;
const batchKey = (category?: string, signature?: string) => JSON.stringify([category, signature]);

export const GET = async () => {
    // Fetch smart alerts (critical + high only)
    const res = await daemonFetch('/api/alerts/smart?limit=50');
    // OLD CODE START — NET-224 P2: a daemon error read as "no alerts" (200, 0 created)
    // const data = await res.json().catch(() => ({ alerts: [] }));
    // OLD CODE END
    const data = await res.json().catch(() => null);
    if (!res.ok || !data) {
        const reason = data?.error || `HTTP ${res.status}`;
        // OLD CODE START — every failure answered 502, so the daemon's own 503 read as a web-server fault
        // return json({ error: `Couldn't read the alerts: ${reason}` }, { status: 502 });
        // OLD CODE END
        // the daemon's error status passes on, as the catch-all proxy does; 502 only for an unreadable OK
        return json({ error: `Couldn't read the alerts: ${reason}` }, { status: res.ok ? 502 : res.status });
    }
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

    // The bell calls this on every page load over the daemon's default 24 h window, and the
    // store now keeps what it holds (NET-224 P2): a category's top signature notifies once a day
    const since = Date.now() - DAY_MS;
    const notified = new Set(
        getNotifications(MAX_STORED_NOTIFICATIONS)
            .filter((n) => n.type === 'alert' && Date.parse(n.timestamp) > since)
            .map((n) => batchKey(n.source?.category, n.source?.signature)),
    );

    // Send notifications for critical/high batches only
    let created = 0;
    for (const [category, batch] of Object.entries(batches)) {
        if (batch.maxSev > 2) continue; // Skip medium/low
        if (notified.has(batchKey(category, batch.topSig))) continue;

        const severity = batch.maxSev <= 1 ? 'critical' : 'high';

        try {
            await sendNotification({
                type: 'alert',
                severity: severity as 'critical' | 'high',
                title: `${batch.count} ${category} alert${batch.count > 1 ? 's' : ''}`,
                message: `${batch.devices.size} device(s) affected \u00b7 ${fmt(batch.events)} events \u00b7 Top: ${batch.topSig}`,
                // OLD CODE: source: { signature: batch.topSig }, (NET-224 P2: the category keys the once-a-day check)
                source: { signature: batch.topSig, category },
            });
            created++;
        } catch {
            // Notification dispatch failed — continue with others
        }
    }

    return json({ notifications_created: created, categories: Object.keys(batches).length });
};
