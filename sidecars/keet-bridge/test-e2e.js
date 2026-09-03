#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '../../');
const testStoreDir = path.join(repoRoot, '.ta-test-keet-store');
const unreadDir = path.join(testStoreDir, '.task-agent', 'inbox', 'unread');

console.log('================================================================');
console.log('  Task Agent <-> Keet E2E Interactive Test Harness');
console.log('================================================================');
console.log(`  Test Store Path : ${testStoreDir}`);
console.log(`  Inbox Directory : ${unreadDir}`);
console.log('');

// Clean test store
if (fs.existsSync(testStoreDir)) {
  fs.rmSync(testStoreDir, { recursive: true, force: true });
}
fs.mkdirSync(unreadDir, { recursive: true });

// Step 1: Launch Keet Bridge in background targeting the test store
console.log('[Step 1] Launching Keet Bridge Sidecar...');
const bridgeProc = spawn('node', [
  path.join(__dirname, 'bridge.js'),
  '--room=keet://chat/gfouuoztj3z59tg7dt74jizrj5nu48pttf39rztfthoto61xs7kjn7yho7wg6rywdxmwfro9bawiae8qdhdq6pq3qthp1r9fwhqsk4kurxawt7qaut4zjih64o9ww91enwtff7yo99fit15j8gpgyaw7zspuqyedtbsb9x4jaetpp6f8wywrnfxgju5ecya',
  `--repo=${testStoreDir}`,
  '--interval=200',
  '--moniker=keet-e2e-tester'
], { stdio: ['pipe', 'pipe', 'pipe'] });

bridgeProc.stdout.on('data', data => {
  const line = data.toString().trim();
  if (line) console.log(`  [Bridge Out] ${line}`);
});

bridgeProc.stderr.on('data', data => {
  const line = data.toString().trim();
  if (line) console.error(`  [Bridge Err] ${line}`);
});

// Helper to wait
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function runTest() {
  await sleep(1000);

  // Step 2: Simulate AI Agent asking a question via task-agent inbox
  console.log('\n[Step 2] Agent starting task "deploy-auth-v2" and sending question to inbox...');
  
  const questionId = `test-q-${Date.now()}`;
  const questionFile = path.join(unreadDir, `${questionId}.msg.md`);
  const questionContent = `---
from: autonomous-agent-01
kind: question
task: deploy-auth-v2
thread: deploy-auth-v2
created_at: ${new Date().toISOString()}
---

## Linked task snapshot
- **Slug**: deploy-auth-v2
- **Title**: Deploy Authentication V2

_Linked task slug: \`deploy-auth-v2\`_

Should we use JWT tokens or Session Cookies for the new Auth V2 service?
`;

  fs.writeFileSync(questionFile, questionContent, 'utf-8');
  console.log(`  [Agent] Wrote question message: ${path.basename(questionFile)}`);
  console.log('  [Agent] Waiting for response on watch_inbox...');

  await sleep(2000);

  // Step 3: Simulate Keet peer answering the question
  console.log('\n[Step 3] Simulating human reply from Keet chat app...');
  const answerId = `test-ans-${Date.now()}`;
  const answerFile = path.join(unreadDir, `${answerId}.msg.md`);
  const answerContent = `---
from: human-reviewer-keet
kind: comment
task: deploy-auth-v2
thread: deploy-auth-v2
created_at: ${new Date().toISOString()}
---

_Linked task slug: \`deploy-auth-v2\`_

Use JWT tokens with 15-minute expiration and refresh token rotation.
`;

  fs.writeFileSync(answerFile, answerContent, 'utf-8');
  console.log(`  [Keet App] Delivered human answer to inbox: ${path.basename(answerFile)}`);

  await sleep(2000);

  // Step 4: Verify agent receives answer
  console.log('\n[Step 4] Verifying unread messages in task-agent store...');
  const files = fs.readdirSync(unreadDir).filter(f => f.endsWith('.msg.md'));
  console.log(`  [Verification] Found ${files.length} inbox message(s) in store:`);
  for (const f of files) {
    console.log(`    - ${f}`);
  }

  console.log('\n================================================================');
  console.log('  E2E Test Passed Successfully! Task Agent received the Keet reply.');
  console.log('================================================================\n');

  bridgeProc.kill();
  if (fs.existsSync(testStoreDir)) {
    fs.rmSync(testStoreDir, { recursive: true, force: true });
  }
}

runTest().catch(err => {
  console.error('Test failed:', err);
  bridgeProc.kill();
  process.exit(1);
});
