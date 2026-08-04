"""Run once. Generates the bot's sealed-box keypair and the at-rest key,
then prints the env lines to paste into your .env. Keep the private key and
at-rest key secret; share only the PUBLIC key (it goes into seal_ssid.py)."""

import crypto_util as cu

priv, pub = cu.generate_keypair()
fernet = cu.generate_fernet_key()

print("# --- paste into .env (keep secret) ---")
print(f"BOT_PRIVATE_KEY={priv}")
print(f"AT_REST_KEY={fernet}")
print()
print("# --- public key: put this in seal_ssid.py or share with linkers ---")
print(f"BOT_PUBLIC_KEY={pub}")
