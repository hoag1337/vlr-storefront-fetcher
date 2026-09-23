"""
Run this LOCALLY to turn your Riot cookie into a sealed blob you can safely
paste to the bot. The plaintext cookie never leaves your machine.

1. Log in at https://auth.riotgames.com/ (incognito), then from DevTools ->
   Application -> Cookies copy at least the ssid (and clid) values.
2. Run:  python tools/seal_ssid.py --pubkey <BOT_PUBLIC_KEY>
   Paste the cookie when prompted (hidden input).
3. Copy the printed blob and send:  /link <blob>   to the bot.
4. Delete your /link message afterward.
"""

import argparse
import getpass
import sys
from pathlib import Path

# Run directly from a clone (`python tools/seal_ssid.py`), so the project root
# has to be importable before valstore resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valstore import crypto as cu


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pubkey", required=True, help="Bot public key from gen_keys.py")
    args = p.parse_args()

    print("Paste your cookie header, e.g.  ssid=...; clid=as1")
    cookie = getpass.getpass("cookie (hidden): ").strip()
    if "ssid=" not in cookie:
        print("That doesn't contain an ssid= value. Aborting.")
        return

    blob = cu.seal(args.pubkey, cookie)
    print("\nSend this to the bot:\n")
    print(f"/link {blob}")


if __name__ == "__main__":
    main()

