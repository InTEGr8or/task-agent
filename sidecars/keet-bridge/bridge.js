#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';
import z32 from 'z32';
import b4a from 'b4a';

// Parse command line arguments
function parseArgs() {
  const args = process.argv.slice(2);
  const config = {
    room: process.env.KEET_ROOM_URI || '',
    repo: process.env.TA_STORE_PATH || process.cwd(),
    pollInterval: 1000,
    moniker: process.env.TA_STORE_MONIKER || 'keet-bridge'
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith('--room=')) {
      config.room = arg.slice(7);
    } else if (arg === '--room' && args[i + 1]) {
      config.room = args[++i];
    } else if (arg.startsWith('--repo=')) {
      config.repo = path.resolve(arg.slice(7));
    } else if (arg === '--repo' && args[i + 1]) {
      config.repo = path.resolve(args[++i]);
    } else if (arg.startsWith('--interval=')) {
      config.pollInterval = parseInt(arg.slice(11), 10) || 1000;
    } else if (arg === '--interval' && args[i + 1]) {
      config.pollInterval = parseInt(args[++i], 10) || 1000;
    } else if (arg.startsWith('--moniker=')) {
      config.moniker = arg.slice(10);
    } else if (arg === '--moniker' && args[i + 1]) {
      config.moniker = args[++i];
    } else if (arg.startsWith('keet://')) {
      config.room = arg;
    } else if (arg === '--help' || arg === '-h') {
      console.log(`
Task Agent Keet Bridge Sidecar

Usage:
  node bridge.js [--room] <keet://chat/...> [--repo <path>] [--interval <ms>] [--moniker <name>]

Options:
  --room      Keet chat URI or topic key (keet://chat/...)
  --repo      Path to task-agent store root (default: current directory)
  --interval  Inbox polling interval in ms (default: 1000)
  --moniker   Moniker name identifying this bridge (default: keet-bridge)
      `);
      process.exit(0);
    }
  }

  // Automatically resolve docs/tasks store root if running in a task-agent repo
  const docsTasks = path.join(config.repo, 'docs', 'tasks');
  if (fs.existsSync(docsTasks) && fs.lstatSync(docsTasks).isDirectory()) {
    config.repo = docsTasks;
  }

  // If room is omitted, check for configured keet_room_uri in store.json
  if (!config.room) {
    const storeJsonCandidates = [
      path.join(config.repo, '.task-agent', 'store.json'),
      path.join(config.repo, 'store.json'),
      path.join(path.dirname(config.repo), '.task-agent', 'store.json')
    ];
    for (const cand of storeJsonCandidates) {
      if (fs.existsSync(cand)) {
        try {
          const meta = JSON.parse(fs.readFileSync(cand, 'utf-8'));
          if (meta && meta.keet_room_uri) {
            config.room = meta.keet_room_uri;
            console.log(`[Config] Loaded secret Keet room URI from ${cand}`);
            break;
          }
        } catch (e) {}
      }
    }
  }

  if (!config.room) {
    console.error('Error: --room argument, KEET_ROOM_URI env var, or "ta store keet set <uri>" is required.');
    process.exit(1);
  }

  return config;
}

// Derive Hyperswarm topic buffer and discoveryKey from a keet:// link or room string
function deriveTopicBuffer(roomUri) {
  let cleanKey = roomUri.trim();
  if (cleanKey.startsWith('keet://chat/')) {
    cleanKey = cleanKey.slice('keet://chat/'.length);
  } else if (cleanKey.startsWith('keet://')) {
    cleanKey = cleanKey.slice('keet://'.length);
  }

  let discoveryKey = null;
  try {
    const buf = z32.decode(cleanKey);
    if (buf && buf.length >= 64) {
      discoveryKey = buf.subarray(32, 64);
    }
  } catch (e) {}

  const topicHash = crypto.createHash('sha256').update(cleanKey).digest();
  return { topicHash, discoveryKey: discoveryKey || topicHash };
}

// Parse frontmatter and body from task-agent inbox message markdown (.msg.md)
function parseMessageFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');
  const match = content.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  
  const meta = {};
  let body = content;

  if (match) {
    const yamlLines = match[1].split('\n');
    for (const line of yamlLines) {
      const idx = line.indexOf(':');
      if (idx !== -1) {
        const key = line.slice(0, idx).trim();
        const val = line.slice(idx + 1).trim();
        meta[key] = val;
      }
    }
    body = match[2].trim();
  }

  const filename = path.basename(filePath);
  const id = filename.endsWith('.msg.md') ? filename.slice(0, -7) : filename;

  return {
    id,
    filePath,
    from: meta.from || 'unknown',
    kind: meta.kind || 'info',
    created_at: meta.created_at || new Date().toISOString(),
    task: meta.task || null,
    thread: meta.thread || null,
    body,
    rawMeta: meta
  };
}

// Write an incoming chat message into task-agent .task-agent/inbox/unread/
function writeInboxMessage(storePath, { fromMoniker, kind = 'comment', thread, task, body }) {
  const unreadDir = path.join(storePath, '.task-agent', 'inbox', 'unread');
  fs.mkdirSync(unreadDir, { recursive: true });

  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '');
  const randHex = crypto.randomBytes(3).toString('hex');
  const msgId = `${stamp}-${randHex}`;
  const filePath = path.join(unreadDir, `${msgId}.msg.md`);

  const linkedSlug = task || thread || '';
  const lines = [
    '---',
    `from: ${fromMoniker}`,
    `kind: ${kind}`,
    `created_at: ${new Date().toISOString()}`
  ];

  if (linkedSlug) {
    lines.append ? lines.push(`task: ${linkedSlug}`) : lines.push(`task: ${linkedSlug}`);
    lines.push(`thread: ${linkedSlug}`);
  }
  lines.push('---', '');
  if (linkedSlug) {
    lines.push(`_Linked task slug: \`${linkedSlug}\`_`, '');
  }
  lines.push(body.trim(), '');

  fs.writeFileSync(filePath, lines.join('\n'), 'utf-8');
  console.log(`[Inbox] Delivered Keet response to inbox: ${msgId}.msg.md`);
  return msgId;
}

async function main() {
  const config = parseArgs();
  const unreadDir = path.join(config.repo, '.task-agent', 'inbox', 'unread');
  const topicRes = deriveTopicBuffer(config.room);
  const topic = topicRes.discoveryKey || topicRes.topicHash;

  console.log('====================================================');
  console.log('  Task Agent <-> Keet Bridge Sidecar Running');
  console.log(`  Store Root : ${config.repo}`);
  console.log(`  Inbox Dir  : ${unreadDir}`);
  console.log(`  Keet Room  : ${config.room.slice(0, 32)}...`);
  console.log(`  Topic Hash : ${topic.toString('hex')}`);
  console.log('====================================================');

  fs.mkdirSync(unreadDir, { recursive: true });

  const seenMessages = new Set();
  
  // Track existing messages so we only broadcast NEW unread messages
  if (fs.existsSync(unreadDir)) {
    const existing = fs.readdirSync(unreadDir).filter(f => f.endsWith('.msg.md'));
    for (const f of existing) {
      seenMessages.add(f);
    }
  }

  // Attempt to load Hyperswarm dynamically if installed
  let swarm = null;
  try {
    const HyperswarmModule = await import('hyperswarm');
    const Hyperswarm = HyperswarmModule.default || HyperswarmModule;
    swarm = new Hyperswarm();

    const peers = new Set();

    swarm.on('connection', (conn, info) => {
      const peerId = info.publicKey ? info.publicKey.toString('hex').slice(0, 8) : 'peer';
      console.log(`[P2P] Peer connected: ${peerId}`);
      peers.add(conn);

      conn.on('data', data => {
        try {
          const payload = JSON.parse(data.toString('utf-8'));
          console.log(`[P2P] Received from Keet (${payload.from || peerId}): ${payload.body || ''}`);

          // Prevent loopback if message originated from this bridge
          if (payload.fromMoniker !== config.moniker) {
            writeInboxMessage(config.repo, {
              fromMoniker: payload.from || `keet-${peerId}`,
              kind: payload.kind || 'comment',
              thread: payload.thread || payload.task,
              task: payload.task,
              body: payload.body || ''
            });
          }
        } catch (e) {
          console.log(`[P2P] Raw message: ${data.toString('utf-8')}`);
        }
      });

      conn.on('close', () => {
        console.log(`[P2P] Peer disconnected: ${peerId}`);
        peers.delete(conn);
      });

      conn.on('error', err => {
        peers.delete(conn);
      });
    });

    const discovery = swarm.join(topic, { client: true, server: true });
    await discovery.flushed();
    console.log('[P2P] Joined Hyperswarm topic; searching for peers...');
  } catch (err) {
    console.warn(`[P2P Warning] Hyperswarm not loaded (${err.message}). Running in local inbox monitoring mode.`);
  }

  // Poll inbox for outbound messages
  setInterval(() => {
    if (!fs.existsSync(unreadDir)) return;

    try {
      const files = fs.readdirSync(unreadDir).filter(f => f.endsWith('.msg.md'));
      for (const file of files) {
        if (!seenMessages.has(file)) {
          seenMessages.add(file);
          const fullPath = path.join(unreadDir, file);
          
          try {
            const msg = parseMessageFile(fullPath);
            console.log(`[Outbound] New inbox message detected: [${msg.id}] ${msg.kind} from ${msg.from}`);
            console.log(`  Body preview: ${msg.body.slice(0, 80)}...`);

            // Format payload for Keet chat room
            const payload = JSON.stringify({
              type: 'task-agent-msg',
              id: msg.id,
              fromMoniker: config.moniker,
              from: msg.from,
              kind: msg.kind,
              task: msg.task,
              thread: msg.thread,
              body: msg.body,
              created_at: msg.created_at
            });

            // Broadcast to connected P2P peers
            if (swarm) {
              for (const conn of swarm.connections) {
                try {
                  conn.write(payload);
                } catch (err) {
                  // Connection write failed
                }
              }
            }
          } catch (e) {
            console.error(`Error processing ${file}:`, e.message);
          }
        }
      }
    } catch (e) {
      // Ignore transient read errors
    }
  }, config.pollInterval);
}

main().catch(err => {
  console.error('Fatal bridge error:', err);
  process.exit(1);
});
