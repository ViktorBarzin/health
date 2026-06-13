"""Credential encryption at rest — the security-critical core (connections).

A per-user **Connection** stores the user's own API credential (a bring-your-own
token, e.g. an Oura Personal Access Token). That secret is **never** persisted in
plaintext: it is encrypted here before it touches the database and only ever
decrypted in-memory at pull time. This module is the single home of that
primitive, so every Connection write/read goes through one audited path.

Scheme + key management (documented decision)
=============================================
* **Fernet** (from ``cryptography``'s recipes layer) — authenticated symmetric
  encryption (AES-128-CBC + HMAC-SHA256, random IV per message). It is the
  library's own recommended high-level primitive: confidentiality *and*
  integrity, with a tamper or wrong-key decryption raising ``InvalidToken``
  rather than returning garbage. We don't hand-roll AES-GCM when the maintained
  recipe gives the same guarantees with no nonce-reuse footguns.
* **Master key from configuration** — ``CONNECTION_ENCRYPTION_KEY`` is a URL-safe
  base64 32-byte key (``Fernet.generate_key()``). In production it is injected
  from the secret store (Vault ``secret/health-connection-key``), exactly like
  ``CLAUDE_AGENT_TOKEN`` — never committed. When **unset**, the Connection
  feature is disabled (the API returns a clear 503) rather than storing tokens
  unprotected: **fail closed, never plaintext**.
* **Key rotation** is supported via :class:`~cryptography.fernet.MultiFernet`:
  ``CONNECTION_ENCRYPTION_KEY`` may be a comma-separated list — the **first** key
  encrypts new tokens; every key in the list can still **decrypt** older ones. So
  to rotate, prepend a fresh key; old ciphertext keeps reading until you
  re-encrypt and drop the retired key.

The token text itself is never logged anywhere in the codebase — only the
Connection's *status* and a *last_error* string (which never includes the
credential) are surfaced.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, MultiFernet

from app.config import settings

__all__ = ["CredentialCipher", "EncryptionNotConfigured"]


class EncryptionNotConfigured(RuntimeError):
    """Raised when a cipher is constructed with no usable key.

    The Connection API treats this as "the feature is unavailable" (503) — we
    never fall back to storing a credential in plaintext.
    """


class CredentialCipher:
    """Encrypt / decrypt a Connection credential with a (rotatable) Fernet key.

    Construct with an explicit list of URL-safe base64 keys (newest first), or
    via :meth:`from_settings` to read ``CONNECTION_ENCRYPTION_KEY``. Encryption
    uses the first key; decryption tries every key (so a token written under a
    retired key still reads during a rotation window).
    """

    def __init__(self, keys: list[str] | None) -> None:
        usable = [k.strip() for k in (keys or []) if k and k.strip()]
        if not usable:
            raise EncryptionNotConfigured(
                "CONNECTION_ENCRYPTION_KEY is not set — Connection credential "
                "encryption is unavailable (fail closed; never store plaintext)."
            )
        # MultiFernet: encrypts with the first, decrypts with any. A single key
        # is just a one-element ring, so the code path is uniform.
        self._fernet = MultiFernet([Fernet(k) for k in usable])

    @classmethod
    def from_settings(cls) -> "CredentialCipher | None":
        """Build a cipher from ``CONNECTION_ENCRYPTION_KEY``, or None if unset.

        The env value may be a single key or a comma-separated rotation list
        (newest first). Returns ``None`` when no key is configured so callers can
        present a clear "not configured" response rather than crashing.
        """
        raw = settings.CONNECTION_ENCRYPTION_KEY
        if not raw or not raw.strip():
            return None
        return cls(keys=raw.split(","))

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a credential string into ciphertext bytes (persisted as bytea).

        Each call uses a fresh random IV, so encrypting the same secret twice
        yields different ciphertext (uncorrelatable). The result never contains
        the plaintext in any readable form.
        """
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt stored ciphertext back to the credential string.

        Raises :class:`cryptography.fernet.InvalidToken` if the ciphertext was
        tampered with or none of the configured keys can authenticate it — never
        returns corrupted output.
        """
        return self._fernet.decrypt(ciphertext).decode("utf-8")
