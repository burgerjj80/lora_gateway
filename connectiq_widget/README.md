# a2zbridge Connect IQ widget

Monkey C widget + background service for Garmin Fenix (and most Connect IQ 3+
devices) that periodically reads sensor data and POSTs it to the
`garmin_bridge` service. Lets you prove the end-to-end data pipeline on your
own watch while the Garmin Health API application is in review.

## What it collects

Every 5 minutes (background temporal event, the Connect IQ minimum):

- Last 5 minutes of heart rate samples (via `SensorHistory`)
- Current stress level
- Body Battery
- Steps today (daily rollup from `ActivityMonitor`)
- Battery level of the watch itself (for health signals / dropouts)

## Delivery path

```
Fenix ─(BLE)─▶ Garmin Connect Mobile ─(internet)─▶ garmin_bridge
          └─(WiFi direct on Fenix 7+ / 8)──────────▶
```

`Communications.makeWebRequest` is the single call that does this; the OS
chooses the best transport.

## Target devices

Set in `monkey.jungle` — defaults cover Fenix 5+ / 6 / 7 / 8 families. Adjust
`project.manifest.products` for your specific device.

## Setup

### Prerequisites

1. [Connect IQ SDK Manager](https://developer.garmin.com/connect-iq/sdk/) — pick
   the latest 7.x SDK; it supports Fenix back to 5 Plus.
2. [VS Code Monkey C extension](https://marketplace.visualstudio.com/items?itemName=garmin.monkey-c)
   (optional — easier debugging) or just the CLI tools.
3. A developer key — generate with:
   ```
   openssl genrsa -out developer_key.pem 4096
   openssl pkcs8 -topk8 -inform PEM -outform DER -in developer_key.pem \
       -out developer_key -nocrypt
   ```
   Keep `developer_key` out of git.

### Configure

Set two things in Connect IQ's **App Settings** on the watch (via Garmin
Connect Mobile → device → Activities & Apps → the widget → Settings):

| Key | Value |
|---|---|
| `ingest_url` | `https://garmin-bridge.a2zwarehouse.example/webhooks/connectiq` |
| `ingest_token` | the `CONNECTIQ_INGEST_TOKEN` value from the backend `.env` |

The widget identifies itself using the device's internal `Settings.getUniqueIdentifier()`
(opaque per-device string). The backend maps `(device_id → user_id)` on first contact.

### Build + sideload

```bash
cd connectiq_widget
monkeyc \
    -o bin/a2zbridge.prg \
    -f monkey.jungle \
    -d fenix7 \
    -y ~/.Garmin/ConnectIQ/developer_key
```

Copy `bin/a2zbridge.prg` to `/GARMIN/APPS/` on the watch over USB, or use
`monkeydo` for a simulator run first.

## Layout

```
connectiq_widget/
├── manifest.xml            app metadata + permissions
├── monkey.jungle           build config (target devices)
├── source/
│   ├── A2zApp.mc           AppBase + ServiceDelegate entrypoints
│   ├── A2zView.mc          widget glance view
│   ├── A2zDelegate.mc      input delegate
│   └── Reporter.mc         sensor read + HTTPS POST
├── resources/
│   ├── strings/strings.xml app settings keys + labels
│   ├── settings/           user-editable settings definition
│   └── drawables/          icon + layout stubs
└── README.md
```

## Minimum SDK permissions

Declared in `manifest.xml`:

- `Communications` — HTTP out
- `Sensor` — current HR
- `SensorHistory` — last-N-minutes HR
- `UserProfile` — age/gender for context (optional)
- `Background` — register temporal event

## Known limitations

- **5-minute minimum** between background wake-ups. Can't push realtime HR
  samples; good enough for stress/wellness monitoring.
- **Needs phone** (or WiFi on Fenix 7+/8) at the time of the POST. Posts queue
  on retries via `Background.exit({:retry => ...})`.
- **Opaque device ID.** First call creates a user mapping on the backend side
  — you'll want a one-time pairing flow (email token etc.) before onboarding
  real users.
