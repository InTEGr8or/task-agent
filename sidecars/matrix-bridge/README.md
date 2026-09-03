# Task Agent <-> Matrix Bridge Sidecar

This sidecar daemon bridges **Task Agent (`ta`)** store inbox messages (`.task-agent/inbox/unread/`) with **Matrix rooms** (usable on mobile with Element, Element X, SchildiChat, FluffyChat, or desktop/web).

Supports both **hosted homeservers** (`matrix.org`, `element.io`) and **self-hosted homeservers** (Conduit, Synapse, Dendrite, Ergo).

---

## Features

- **Mobile Notifications**: Real-time push notifications on iOS & Android via standard Matrix mobile apps.
- **Hosted or Self-Hosted**: Works with public servers (`matrix.org`) or private self-hosted servers (Conduit on Raspberry Pi).
- **Per-Store Room Binding**: Configure unique Matrix room IDs for each repo store (`ta store matrix set`).
- **Zero External Dependencies**: Built with Python's standard library (`urllib.request` / `json`).

---

## Setup & Configuration

### 1. Create a Matrix Bot Account & Access Token

1. Register a bot user account on your Matrix homeserver (e.g. `@task-agent-bot:matrix.org` or on your self-hosted server).
2. Obtain the access token for the bot account (Element Web: *Settings → Help & About → Access Token*).
3. Export the token:
   ```bash
   export MATRIX_ACCESS_TOKEN="syt_..."
   export MATRIX_HOMESERVER="https://matrix.org"  # or https://your-raspberry-pi:8448
   ```

### 2. Create a Room for Your Repository Store

1. In Element (on mobile or desktop), create a private chat room for your repository (e.g. `#task-agent` or `!abc123xyz:matrix.org`).
2. Invite your bot user (`@task-agent-bot:...`) to the room.
3. Copy the Room ID from Room Settings (*Advanced → Room ID*, e.g., `!qwertyuiop:matrix.org`).

### 3. Bind the Room ID to the Task Agent Store

Set the Matrix room binding for the store:

```bash
ta store matrix set "!qwertyuiop:matrix.org"
```

View configured room binding:
```bash
ta store matrix show
```

---

## Running the Bridge

Launch the Matrix bridge sidecar:

```bash
python3 sidecars/matrix-bridge/matrix_bridge.py
```

### Options

| Flag | Environment Variable | Default | Description |
|------|----------------------|---------|-------------|
| `--homeserver` | `MATRIX_HOMESERVER` | `https://matrix.org` | Matrix homeserver URL |
| `--token` | `MATRIX_ACCESS_TOKEN` | *(required)* | Matrix Bot Access Token |
| `--room` | `MATRIX_ROOM_ID` | Store metadata | Matrix Room ID (`!roomid:domain`) |
| `--repo` | `TA_STORE_PATH` | Current Directory (`.`) | Path to target task-agent store root |
| `--interval` | - | `1.0` | Polling frequency in seconds for inbox changes |
