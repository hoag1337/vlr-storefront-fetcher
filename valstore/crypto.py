"""
Two layers of protection for the session cookie:

1. In transit (user -> bot via Telegram): the user seals the cookie to the
   bot's PUBLIC key with a NaCl sealed box (seal_ssid.py). Only the bot's
   private key can open it, so the plaintext ssid never passes through
   Telegram's servers.

2. At rest (bot's SQLite DB): the cookie is encrypted with Fernet (AES-128-CBC
   + HMAC) using a key held only in the environment. A stolen DB file is
   useless without that key.
"""

import base64

from cryptography.fernet import Fernet
from nacl.public import PrivateKey, PublicKey, SealedBox


# ---- at rest (symmetric) ----

def encrypt_at_rest(fernet_key: bytes, plaintext: str) -> bytes:
    return Fernet(fernet_key).encrypt(plaintext.encode())


def decrypt_at_rest(fernet_key: bytes, token: bytes) -> str:
    return Fernet(fernet_key).decrypt(token).decode()


# ---- in transit (asymmetric sealed box) ----

def unseal(private_key_b64: str, sealed_blob_b64: str) -> str:
    sk = PrivateKey(base64.b64decode(private_key_b64))
    box = SealedBox(sk)
    return box.decrypt(base64.b64decode(sealed_blob_b64)).decode()


def seal(public_key_b64: str, plaintext: str) -> str:
    pk = PublicKey(base64.b64decode(public_key_b64))
    box = SealedBox(pk)
    return base64.b64encode(box.encrypt(plaintext.encode())).decode()


# ---- key generation ----

def generate_keypair():
    """Returns (private_b64, public_b64) for the sealed-box keypair."""
    sk = PrivateKey.generate()
    return (
        base64.b64encode(bytes(sk)).decode(),
        base64.b64encode(bytes(sk.public_key)).decode(),
    )


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode()
