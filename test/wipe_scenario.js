#!/usr/bin/env node
// Render free tier scenario: the server's disk is wiped when it sleeps, restarts or redeploys.
// With DRAGON_SECRET set, logins and room locks must come back from the browsers' sealed copies.
// Starts its own servers on ports 8801-8802. Run: node test/wipe_scenario.js
'use strict';
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const WebSocket = require('ws');

const ROOT = path.join(__dirname, '..');
const SECRET = 'test-secret-' + Math.random().toString(36).slice(2) + '-long-enough';
let failures = 0, passes = 0;
function check(name, cond, detail) {
  if (cond) { passes++; console.log('PASS ' + name); }
  else { failures++; console.log('FAIL ' + name + (detail !== undefined ? '  -> ' + JSON.stringify(detail) : '')); }
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

let proc = null;
async function startServer(port, dataDir, secret) {
  proc = spawn(process.execPath, ['server.js'], { cwd: ROOT, env: Object.assign({}, process.env, { PORT: String(port), DATA_DIR: dataDir, DRAGON_SECRET: secret || '' }), stdio: ['ignore', 'pipe', 'pipe'] });
  proc.stdout.on('data', d => { if (process.env.VERBOSE) process.stdout.write('  [server] ' + d); });
  proc.stderr.on('data', d => process.stdout.write('  [server err] ' + d));
  for (let i = 0; i < 50; i++) {
    try { const r = await fetch(`http://localhost:${port}/api/ping`); if (r.ok) return; } catch (e) {}
    await sleep(100);
  }
  throw new Error('server did not start');
}
async function stopServer() {
  if (!proc) return;
  const p = proc; proc = null;
  await new Promise(r => { p.on('exit', r); p.kill('SIGTERM'); });
}
const wipe = dir => fs.rmSync(dir, { recursive: true, force: true });

async function api(port, p, { method = 'GET', token, body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(`http://localhost:${port}${p}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let data = null; try { data = await r.json(); } catch (e) {}
  return { status: r.status, data };
}
async function signup(port, name, email) {
  return api(port, '/api/signup', { method: 'POST', body: { name, email, password: 'correct-horse-battery' } });
}

// A minimal room client: connects, says hello, collects messages.
function join(port, room, { auth, password, seal, client } = {}) {
  return new Promise(resolve => {
    const ws = new WebSocket(`ws://localhost:${port}/ws`);
    const c = { ws, msgs: [], closed: false, closeCode: 0 };
    ws.on('open', () => ws.send(JSON.stringify({ t: 'hello', room, client: client || 'c' + Math.random().toString(36).slice(2, 8), sv: {}, state: { name: 'x', color: '#f97316' }, auth, password, seal })));
    ws.on('message', raw => { const m = JSON.parse(raw); c.msgs.push(m); if (m.t === 'welcome' || m.t === 'denied') resolve(c); });
    ws.on('close', code => { c.closed = true; c.closeCode = code; resolve(c); });
  });
}
const first = (c, t) => c.msgs.find(m => m.t === t);
async function waitFor(fn, ms = 3000) { const end = Date.now() + ms; while (Date.now() < end) { if (fn()) return true; await sleep(50); } return fn(); }

(async () => {
  const port = 8801;
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dragon-wipe-'));
  const room = 'p-wipe' + Math.random().toString(36).slice(2, 7);
  try {
    // ---------------------------------------------------------------- 1. logins survive a wipe
    console.log('\n== 1. A wiped disk does not log anyone out');
    await startServer(port, dataDir, SECRET);
    const ping = await api(port, '/api/ping');
    check('server says it keeps logins across a wipe', ping.data && ping.data.keepsLogins === true, ping.data);
    const asha = await signup(port, 'Asha', 'asha@example.com');
    check('Asha signs up', asha.status === 201 && asha.data.token, asha);
    const bilal = await signup(port, 'Bilal', 'bilal@example.com');
    const renamed = await api(port, '/api/me', { method: 'PATCH', token: bilal.data.token, body: { name: 'Bilal K', color: '#22c55e' } });
    check('a profile change hands back a fresh sealed login', renamed.status === 200 && typeof renamed.data.token === 'string' && renamed.data.token !== bilal.data.token, renamed.data);
    const bilalToken = renamed.data.token;

    // Asha locks a project room with a password; she keeps the sealed lock.
    const a1 = await join(port, room, { auth: asha.data.token, client: 'asha1' });
    check('Asha joins her room', !!first(a1, 'welcome'), a1.msgs);
    a1.ws.send(JSON.stringify({ t: 'ops', ops: [{ k: 'ins', c: 'asha1', s: 1, lam: 1, f: 'index.html', o: '~root', x: 'hello' }] }));
    await waitFor(() => a1.msgs.some(m => m.t === 'ack'));
    a1.ws.send(JSON.stringify({ t: 'lock', password: 'room-pass' }));
    await waitFor(() => a1.msgs.some(m => m.t === 'locked'));
    const lockMsg = a1.msgs.find(m => m.t === 'locked');
    check('locking the room gives members a sealed copy of the lock', lockMsg && lockMsg.locked && typeof lockMsg.seal === 'string' && lockMsg.seal.startsWith('v1.'), lockMsg);
    const roomSeal = lockMsg && lockMsg.seal;
    a1.ws.close();

    await stopServer(); wipe(dataDir);
    console.log('   (server stopped, data folder deleted, server started again)');
    await startServer(port, dataDir, SECRET);

    const me = await api(port, '/api/me', { token: asha.data.token });
    check('Asha is still logged in after the wipe', me.status === 200 && me.data.user.email === 'asha@example.com', me);
    check('her account came back with the same id', me.data && me.data.user.id === asha.data.user.id);
    const meB = await api(port, '/api/me', { token: bilalToken });
    check("Bilal's account came back with his new name and colour", meB.status === 200 && meB.data.user.name === 'Bilal K' && meB.data.user.color === '#22c55e', meB.data);
    const login = await api(port, '/api/login', { method: 'POST', body: { email: 'asha@example.com', password: 'correct-horse-battery' } });
    check('Asha can log in with her password again on a new device', login.status === 200, login);
    const wrong = await api(port, '/api/login', { method: 'POST', body: { email: 'asha@example.com', password: 'wrong-password-123' } });
    check('a wrong password is still refused', wrong.status === 401, wrong.status);

    // ---------------------------------------------------------------- 2. room locks survive a wipe
    console.log('\n== 2. A locked room stays locked after a wipe');
    const eve = await signup(port, 'Eve', 'eve@example.com');
    const e1 = await join(port, room, { auth: eve.data.token, client: 'eve1' });
    check('(before any member is back, the empty room has no lock yet)', !!first(e1, 'welcome'));
    const a2 = await join(port, room, { auth: asha.data.token, password: 'room-pass', seal: roomSeal, client: 'asha2' });
    const w2 = first(a2, 'welcome');
    check('Asha comes back: the lock is restored from her sealed copy', w2 && w2.locked === true, a2.msgs);
    check('Eve, who got in while the lock was missing, is sent to the password prompt', await waitFor(() => e1.msgs.some(m => m.t === 'denied' && m.reason === 'locked') && e1.closed), e1.msgs.slice(-2));
    const e2 = await join(port, room, { auth: eve.data.token, client: 'eve2' });
    check('Eve cannot get back in without the password', !!first(e2, 'denied') && !first(e2, 'welcome'), e2.msgs);
    a2.ws.send(JSON.stringify({ t: 'ops', ops: [{ k: 'ins', c: 'asha1', s: 1, lam: 1, f: 'index.html', o: '~root', x: 'hello' }] }));
    await waitFor(() => a2.msgs.some(m => m.t === 'ack'));
    const e3 = await join(port, room, { auth: eve.data.token, password: 'room-pass', client: 'eve3' });
    check('with the right password Eve gets in and receives the project Asha re-sent', !!first(e3, 'welcome') && await waitFor(() => e3.msgs.some(m => m.t === 'ops' && m.ops.some(o => o.x === 'hello'))), e3.msgs);
    const forged = await join(port, room, { auth: eve.data.token, client: 'eve4', seal: roomSeal.slice(0, -4) + 'AAAA' });
    check('a tampered lock copy is ignored', !!first(forged, 'denied'), forged.msgs);
    for (const c of [a2, e3, forged]) c.ws.close();

    // ---------------------------------------------------------------- 3. what must still be refused
    console.log('\n== 3. Security after a wipe');
    const out = await signup(port, 'Omar', 'omar@example.com');
    await api(port, '/api/logout', { method: 'POST', token: out.data.token });
    check('a logged-out token is refused', (await api(port, '/api/me', { token: out.data.token })).status === 401);
    const t = asha.data.token;
    const tampered = t.slice(0, 20) + (t[20] === 'A' ? 'B' : 'A') + t.slice(21);
    check('a tampered token is refused', (await api(port, '/api/me', { token: tampered })).status === 401);
    await api(port, '/api/logout', { method: 'POST', token: bilalToken });
    check('logging out ends the renewed token and the older one it replaced',
      (await api(port, '/api/me', { token: bilalToken })).status === 401 && (await api(port, '/api/me', { token: bilal.data.token })).status === 401);
    const health = await api(port, '/health');
    check('/health shows counts only, never room names', health.status === 200 && typeof health.data.rooms === 'number' && !JSON.stringify(health.data).includes(room), health.data);

    await stopServer(); wipe(dataDir);
    await startServer(port, dataDir, SECRET);
    const newAsha = await signup(port, 'Someone', 'asha@example.com');
    check('after a wipe the email can be signed up again', newAsha.status === 201);
    check("then the old token for that email no longer works (the new account wins)", (await api(port, '/api/me', { token: asha.data.token })).status === 401);

    await stopServer(); wipe(dataDir);
    await startServer(port, dataDir, 'a-completely-different-secret');
    check('a different DRAGON_SECRET does not accept old tokens', (await api(port, '/api/me', { token: bilalToken })).status === 401);

    // ---------------------------------------------------------------- 4. no secret: old behaviour
    console.log('\n== 4. Without DRAGON_SECRET (old behaviour)');
    await stopServer(); wipe(dataDir);
    await startServer(port, dataDir, '');
    const p0 = await api(port, '/api/ping');
    check('server says it does not keep logins across a wipe', p0.data && p0.data.keepsLogins === false, p0.data);
    const z = await signup(port, 'Zara', 'zara@example.com');
    check('tokens still work normally', (await api(port, '/api/me', { token: z.data.token })).status === 200);
    await stopServer(); wipe(dataDir);
    await startServer(port, dataDir, '');
    check('after a wipe the login is gone (as before)', (await api(port, '/api/me', { token: z.data.token })).status === 401);
  } catch (e) {
    failures++;
    console.log('FAIL crashed: ' + (e && e.stack || e));
  } finally {
    await stopServer();
    wipe(dataDir);
  }
  console.log(`\n${passes}/${passes + failures} checks passed`);
  process.exit(failures ? 1 : 0);
})();
