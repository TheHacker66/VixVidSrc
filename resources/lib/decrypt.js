'use strict';
// Only stdin/stdout cross the helper boundary. No WASI or host imports.
const fs = require('fs');
let phase = 'runtime';
const runtime = {node: process.version, arch: process.arch, platform: process.platform};
(async () => {
  if (typeof WebAssembly === 'undefined') throw Error('wasm_unavailable');
  const Decoder = typeof TextDecoder !== 'undefined' ? TextDecoder : require('util').TextDecoder;
  if (!Decoder) throw Error('decoder_unavailable');
  if (process.argv.indexOf('--self-test') !== -1) {
    // Test alloc/decrypt exports, memory and UTF-8 without network or tokens.
    phase = 'self_test_compile';
    const bytes = Buffer.from('0061736d01000000010c0260017f017f60027f7f017f03030200010503010001071c0305616c6c6f63000007646563727970740001066d656d6f727902000a0e02040041000b07002001410c6b0b', 'hex');
    const ex = (await WebAssembly.instantiate(await WebAssembly.compile(bytes), {})).exports;
    phase = 'self_test_memory';
    const enc = Buffer.from('000000000000ok');
    const ptr = ex.alloc(enc.length);
    new Uint8Array(ex.memory.buffer, ptr, enc.length).set(enc);
    const len = ex.decrypt(ptr, enc.length);
    const txt = new Decoder('utf-8', {fatal: true}).decode(new Uint8Array(ex.memory.buffer, ptr + 12, len));
    if (txt !== 'ok') throw Error('self_test_failed');
    process.stdout.write(JSON.stringify(Object.assign({ok: true}, runtime)));
    return;
  }
  phase = 'input';
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const bytes = Buffer.from(input.wasm, 'base64');
  const encrypted = Buffer.from(input.encrypted, 'base64');
  if (!bytes.length || bytes.length > 8 * 1024 * 1024 || encrypted.length < 12 || encrypted.length > 1024 * 1024)
    throw Error('Dimensioni WASM o payload non valide');
  phase = 'compile';
  const mod = await WebAssembly.compile(bytes);
  if (WebAssembly.Module.imports(mod).length) throw Error('Il modulo richiede import esterni');
  phase = 'instantiate';
  const ex = (await WebAssembly.instantiate(mod, {})).exports;
  if (!(ex.memory instanceof WebAssembly.Memory) || typeof ex.alloc !== 'function' || typeof ex.decrypt !== 'function')
    throw Error('Interfaccia WASM inattesa');
  phase = 'allocate';
  const ptr = ex.alloc(encrypted.length) >>> 0;
  if (ptr + encrypted.length > ex.memory.buffer.byteLength) throw Error('Allocazione fuori memoria');
  new Uint8Array(ex.memory.buffer, ptr, encrypted.length).set(encrypted);
  phase = 'decrypt';
  const len = ex.decrypt(ptr, encrypted.length);
  if (!Number.isInteger(len) || len < 0 || len > 1024 * 1024 || ptr + 12 + len > ex.memory.buffer.byteLength)
    throw Error('Lunghezza risultato non valida');
  phase = 'decode';
  const txt = new Decoder('utf-8', {fatal: true}).decode(new Uint8Array(ex.memory.buffer, ptr + 12, len));
  process.stdout.write(JSON.stringify(txt.split('\n').map(x => x.trim()).filter(Boolean)));
})().catch((error) => {
  // Report a fixed classification, never raw error strings or payload content.
  const message = String(error.message || '').toLowerCase();
  let category = 'module_error';
  if (/memory|allocation|allocate|out of bounds/.test(message)) category = 'memory';
  else if (/unsupported|not supported|disabled|unavailable/.test(message)) category = 'unsupported';
  else if (/interfaccia|import/.test(message)) category = 'interface';
  else if (/utf|encoded/.test(message)) category = 'utf8';
  process.stderr.write(JSON.stringify(Object.assign({phase: phase, category: category, error: error.name || 'Error'}, runtime)));
  process.exitCode = 1;
});
