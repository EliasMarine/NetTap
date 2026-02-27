# Notifications

NetTap can send notifications when significant events occur, such as high-severity IDS alerts or system health issues. Three notification channels are supported.

---

## Notification Channels

### Email (SMTP)

Send alert notifications to one or more email addresses via SMTP.

**Configuration** (via dashboard at `/settings/notifications`):

| Setting | Description | Default |
|---|---|---|
| **SMTP Host** | Your SMTP server address | (empty --- disabled) |
| **SMTP Port** | SMTP port | `587` |
| **SMTP User** | SMTP authentication username | (empty) |
| **SMTP Password** | SMTP authentication password | (empty) |
| **From Address** | Sender email address | `nettap@localhost` |
| **Recipients** | Comma-separated list of email addresses | (empty) |

**Via environment variables:**

```ini title=".env"
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASS=your-app-password
ALERT_EMAIL=admin@example.com
```

!!! tip "Gmail App Passwords"
    If using Gmail, you need to generate an [App Password](https://support.google.com/accounts/answer/185833) rather than using your regular Gmail password. Enable 2-factor authentication first, then create an App Password for "Mail."

### Webhook

Send JSON payloads to a URL when alerts fire. This works with:

- **Slack** (via incoming webhook URLs)
- **Discord** (via webhook URLs)
- **Microsoft Teams** (via incoming webhook connectors)
- **PagerDuty**, **Opsgenie**, or any HTTP endpoint

**Configuration:**

| Setting | Description |
|---|---|
| **Webhook URL** | The endpoint to POST alert data to |

**Via environment variables:**

```ini title=".env"
WEBHOOK_URL=https://your-webhook-service.example.com/alerts
```

### In-App Notifications

In-app notifications appear in the dashboard notification bell. These are enabled by default and cannot be disabled. They provide a history of recent events within the dashboard UI.

---

## Severity Threshold

Control which alerts trigger notifications. The severity threshold determines the minimum severity level that generates notifications:

| Threshold | Notifies on |
|---|---|
| **1 (High only)** | Only HIGH severity alerts |
| **2 (Medium+)** | HIGH and MEDIUM alerts |
| **3 (All)** | HIGH, MEDIUM, and LOW alerts |

The default is **3** (all severities). For most home networks, setting this to **2** (Medium and above) reduces notification noise while still catching important events.

---

## Configuring Notifications

### Via the Dashboard

1. Navigate to **Settings > Notifications** (`/settings/notifications`)
2. Enable your preferred channels (Email, Webhook, or both)
3. Fill in the configuration fields
4. Click **Test** to send a test notification
5. Click **Save** to apply

### Via the API

```bash
# Get current notification config
curl http://localhost:8880/api/notifications/config

# Update notification config
curl -X POST http://localhost:8880/api/notifications/config \
  -H "Content-Type: application/json" \
  -d '{
    "email": {
      "enabled": true,
      "recipients": ["admin@example.com"],
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUser": "your-email@gmail.com",
      "smtpPass": "your-app-password",
      "smtpFrom": "nettap@yourdomain.com"
    },
    "webhook": {
      "enabled": true,
      "url": "https://your-webhook-service.example.com/alerts"
    },
    "severityThreshold": 2
  }'
```

---

## Testing Notifications

From the Notifications settings page, use the **Test** button to send a test notification through each configured channel. This verifies that:

- SMTP credentials are correct and the mail server is reachable
- Webhook URLs are valid and accept POST requests
- Email recipients receive the test message

---

## Notification Content

Alert notifications include:

- **Alert severity** (HIGH / MEDIUM / LOW)
- **Signature name** (the Suricata rule that triggered)
- **Source and destination IPs** with port numbers
- **Timestamp** of the detection
- **Link to the alert** in the NetTap dashboard
