# Retention Health Card — Design

## Problem

After implementing the bulletproof retention system, users have no visual confirmation that their retention settings are actually being enforced. The Settings/Retention tab lets you edit values but provides no feedback about system health — ILM policy sync, prune cycle activity, or disk pressure relative to thresholds.

## Solution

Add a **Retention Health** status card at the top of the Settings/Retention tab with an overall health badge and 3 detail rows.

## UI Design

### Location

Settings page > Retention tab > top of page, above the tier configuration cards.

### Layout

```
┌─ Retention Health ──────────────────────────┐
│                                              │
│  ● Healthy                                   │
│                                              │
│  ILM Policies    ✓ All 3 synced              │
│  Disk Usage      12.4% (threshold: 80%)      │
│  Last Prune      2 minutes ago               │
│                                              │
└──────────────────────────────────────────────┘
```

### Overall Status Logic

| Status | Color | Condition |
|--------|-------|-----------|
| Healthy | `var(--success)` | ILM synced AND disk < 70% AND prune within 10 min |
| Attention | `var(--warning)` | ILM pending retry OR disk 70-85% OR prune stale (>10 min) |
| Problem | `var(--danger)` | ILM not synced (no retry) OR disk > emergency threshold |

### Detail Rows

1. **ILM Policies**: Shows `✓ All 3 synced` (green) or `⟳ Syncing...` (yellow) or `✗ Out of sync` (red)
2. **Disk Usage**: Shows `X.X% (threshold: Y%)` with color based on proximity to threshold
3. **Last Prune**: Shows relative time ("2 minutes ago"). Yellow if >10 min, red if >30 min or never

## Backend Changes

### Add to `StorageManager.get_status()` response

```python
"last_prune_at": "2026-03-23T12:05:00Z",  # ISO timestamp, set at end of run_cycle()
"ilm_status": {
    "synced": True,
    "last_applied": "2026-03-23T12:00:00Z",
    "pending_retry": False,
    "policies": {
        "nettap-hot-policy": "unchanged",
        "nettap-warm-policy": "unchanged",
        "nettap-cold-policy": "unchanged"
    }
}
```

### Track `last_prune_at` in StorageManager

Add `self._last_prune_at: str | None = None` attribute. Set it to current ISO timestamp at the end of each `run_cycle()`.

### Pull ILM status from RetentionConfigManager

`get_status()` checks if `RetentionConfigManager` is available (via a reference stored on the manager or passed during construction) and includes its `get_ilm_status()` data.

## StorageTierPanel Fix

Replace hardcoded retention days:
```typescript
// BEFORE (hardcoded):
{ key: 'hot', label: 'Hot (Zeek Metadata)', color: 'var(--red)', days: '90d' },

// AFTER (from API):
days: storage?.hot_days ? `${storage.hot_days}d` : '90d',
```

## Files to Modify

| File | Change |
|------|--------|
| `daemon/storage/manager.py` | Add `_last_prune_at`, set in `run_cycle()`, include in `get_status()` |
| `daemon/storage/manager.py` | Add `ilm_status` to `get_status()` from config manager |
| `web/src/routes/settings/+page.svelte` | Add RetentionHealthCard section at top of Retention tab |
| `web/src/lib/components/StorageTierPanel.svelte` | Use actual retention days from API |
| `web/src/routes/api/setup/storage/+server.ts` | Pass through new fields in normalization |
