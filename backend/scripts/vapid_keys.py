"""A new VAPID key pair for PrediGol's notices on devices (plan UX, B7; the owner's action P12).

Run it ON THE SERVER, where the key will live, into a file only root reads - never onto the screen - and append its first
line to /etc/predigol/app.env (root, 600: the file that already holds the second factor's key); then recreate the API and
the messenger (docs/owner/AVISOS_UX_B7.md, section 9, has every command):

    sudo sh -c 'umask 077; docker exec predigol-api python -m scripts.vapid_keys > /root/predigol-vapid.txt'

It prints FBI_VAPID_PRIVATE_KEY (the secret: never in a chat, a ticket or a repository) and, for reference, the public key
the browsers will subscribe with (the API derives it from the private one). A new pair makes every browser subscribe again:
change it only if the old one leaked.
"""

from __future__ import annotations

from fbi.messaging import push


def main() -> None:
    private = push.new_private_key()
    public = push.Vapid(private=push.private_key_from(private), subject="https://predigol.com").public
    print(f"FBI_VAPID_PRIVATE_KEY={private}")
    print(f"# public key (derived, for reference): {public}")


if __name__ == "__main__":
    main()
