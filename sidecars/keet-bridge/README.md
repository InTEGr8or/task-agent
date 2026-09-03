# Task Agent <-> Keet Bridge Sidecar

This sidecar daemon bridges **Task Agent (`ta`)** store inbox messages (`.task-agent/inbox/unread/`) with **Keet** P2P chat rooms using the **Hyperswarm** DHT protocol.

## Architecture

- **Outbound (Agent → Keet)**: Monitors `.task-agent/inbox/unread/` in real time. When an agent posts a question (`kind="question"` or `kind="ack-request"`), the bridge formats and broadcasts the payload to connected peers in the Keet room.
- **Inbound (Keet → Agent)**: Listens for incoming P2P chat responses from Keet room participants, writing them as `.msg.md` files into `.task-agent/inbox/unread/`. This immediately unblocks agents waiting on `watch_inbox_mcp` or `watch_inbox`.

## Installation

```bash
cd sidecars/keet-bridge
npm install
```

## Usage

Run the bridge daemon by pointing it to your Keet room invite URI and task-agent store root:

```bash
node bridge.js --room "keet://chat/<your-room-secret-key>" --repo /path/to/repo
```

### Options

| Flag | Environment Variable | Default | Description |
|------|----------------------|---------|-------------|
| `--room` | `KEET_ROOM_URI` | *(required)* | Keet room URI (`keet://chat/...`) or topic key |
| `--repo` | `TA_STORE_PATH` | Current Directory (`.`) | Path to target task-agent store root |
| `--interval` | - | `1000` | Polling frequency in milliseconds for inbox changes |
| `--moniker` | `TA_STORE_MONIKER` | `keet-bridge` | Moniker identifier for this sidecar node |

## Testing

You can test the flow by running the bridge in one terminal window and using the `ta` CLI in another:

1. **Start the bridge**:
   ```bash
   node sidecars/keet-bridge/bridge.js --room "keet://chat/gfouuoztj3z59..." --repo .
   ```

2. **Send a test question from an agent**:
   ```bash
   ta inbox send --repo . --kind question --thread my-task --body "Should we proceed with Option A or B?"
   ```

3. **Verify unread messages or response delivery**:
   ```bash
   ta inbox list
   ```
