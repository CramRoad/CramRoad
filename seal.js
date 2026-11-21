'use strict';
// Sealed tokens: small pieces of server data that browsers keep for the server.
//
// Free hosts such as Render wipe the server's disk whenever it sleeps, restarts or redeploys.
// With a secret set (DRAGON_SECRET, at least 16 characters), the server hands each browser an
// encrypted, tamper-proof copy of what it would lose: the account behind a login, and a room's
// password lock. After a wipe, the first browser that comes back gives the copy back, and the
// server restores it. Browsers cannot read or change a sealed token (AES-256-GCM).
const crypto = require('crypto');

function createSealer(secret) {
  secret = String(secret || '');
  if (secret.length < 16) return null;
  const key = crypto.createHash('sha256').update('dragon-seal-v1:' + secret).digest();
  return {
    seal(data) {
      const iv = crypto.randomBytes(12);
      const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
      const body = Buffer.concat([cipher.update(JSON.stringify(data), 'utf8'), cipher.final()]);
      return 'v1.' + Buffer.concat([iv, cipher.getAuthTag(), body]).toString('base64url');
    },
    // The data inside a sealed token, or null if it is not one of ours (or was changed).
    unseal(text) {
      if (typeof text !== 'string' || !text.startsWith('v1.') || text.length > 8192) return null;
      try {
        const raw = Buffer.from(text.slice(3), 'base64url');
        if (raw.length < 29) return null;
        const decipher = crypto.createDecipheriv('aes-256-gcm', key, raw.subarray(0, 12));
        decipher.setAuthTag(raw.subarray(12, 28));
        const json = Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]).toString('utf8');
        const data = JSON.parse(json);
        return data && typeof data === 'object' ? data : null;
      } catch (e) { return null; }
    }
  };
}

module.exports = { createSealer };
