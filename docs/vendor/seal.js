// Sealed-box encryption matching PyNaCl's SealedBox (libsodium crypto_box_seal).
//
// The bot opens the blob with valstore.crypto.unseal(), so this reproduces
// crypto_box_seal exactly:
//   ephemeral_pk, ephemeral_sk = box keypair
//   nonce   = blake2b(ephemeral_pk || recipient_pk, 24)          // no key
//   cipher  = box(msg, nonce, recipient_pk, ephemeral_sk)        // 16-byte tag prepended
//   blob    = ephemeral_pk (32) || cipher
// Proven against valstore.crypto.unseal by a node<->python round-trip test.
//
// `nacl` (tweetnacl) is passed in rather than imported, so the page can load it
// as a plain <script> global while node loads it as CommonJS — the same seal
// code runs in both.
import { blake2b } from "./blakejs.esm.js";

function b64decode(s) {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function b64encode(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

// Seal `message` (string) to `recipientPublicKeyB64`. Returns a base64 blob.
export function sealToBase64(message, recipientPublicKeyB64, nacl) {
  let recipientPk;
  try {
    recipientPk = b64decode(recipientPublicKeyB64.trim());
  } catch (e) {
    throw new Error("The bot key isn't valid base64.");
  }
  if (recipientPk.length !== nacl.box.publicKeyLength) {
    throw new Error("The bot key looks wrong (expected a 32-byte X25519 key).");
  }
  const messageBytes = new TextEncoder().encode(message);

  const ephemeral = nacl.box.keyPair();

  const nonceInput = new Uint8Array(ephemeral.publicKey.length + recipientPk.length);
  nonceInput.set(ephemeral.publicKey, 0);
  nonceInput.set(recipientPk, ephemeral.publicKey.length);
  const nonce = blake2b(nonceInput, undefined, nacl.box.nonceLength); // 24 bytes

  const boxed = nacl.box(messageBytes, nonce, recipientPk, ephemeral.secretKey);

  const blob = new Uint8Array(ephemeral.publicKey.length + boxed.length);
  blob.set(ephemeral.publicKey, 0);
  blob.set(boxed, ephemeral.publicKey.length);
  return b64encode(blob);
}
