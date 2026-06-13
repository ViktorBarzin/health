"""Credential encryption at rest — the security-critical core (connections).

The per-user Connection credential (e.g. an Oura Personal Access Token) is stored
ENCRYPTED at rest and only ever decrypted in-memory at pull time. These tests pin
the contract that makes that safe:

* a round-trip recovers the exact plaintext;
* the stored ciphertext is **not** the plaintext (the secret never appears in the
  bytes we persist) and differs across encryptions of the same value (Fernet's
  random IV) so ciphertext can't be correlated;
* a tampered or wrong-key token is **rejected** (``InvalidToken``), never silently
  returning garbage;
* the key is read from configuration, and key **rotation** (a comma-separated
  list) still decrypts tokens written under an older key.

This is a pure, IO-free module (no DB, no network) — the single home of the
encrypt/decrypt primitive every Connection write/read goes through.
"""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.services.crypto import (
    CredentialCipher,
    EncryptionNotConfigured,
)

_KEY = Fernet.generate_key().decode()
_OTHER_KEY = Fernet.generate_key().decode()

# A representative Oura-style PAT — opaque, secret, must never leak.
# Deliberately a LOW-entropy obviously-fake string: the tests only need *a*
# non-empty value to round-trip, and a high-entropy literal trips secret scanners.
_TOKEN = "fake-token-for-crypto-tests"


def test_round_trip_recovers_the_exact_plaintext() -> None:
    cipher = CredentialCipher(keys=[_KEY])
    ciphertext = cipher.encrypt(_TOKEN)
    assert cipher.decrypt(ciphertext) == _TOKEN


def test_ciphertext_is_not_the_plaintext() -> None:
    """The persisted bytes must not contain the secret in any readable form."""
    cipher = CredentialCipher(keys=[_KEY])
    ciphertext = cipher.encrypt(_TOKEN)

    assert isinstance(ciphertext, bytes)
    assert ciphertext != _TOKEN.encode()
    # The raw secret characters never appear in the ciphertext bytes.
    assert _TOKEN.encode() not in ciphertext
    assert _TOKEN not in ciphertext.decode("latin-1")


def test_same_plaintext_encrypts_differently_each_time() -> None:
    """Fernet's random IV means two encryptions of one value differ — no correlation."""
    cipher = CredentialCipher(keys=[_KEY])
    a = cipher.encrypt(_TOKEN)
    b = cipher.encrypt(_TOKEN)
    assert a != b
    # …but both decrypt back to the same secret.
    assert cipher.decrypt(a) == _TOKEN
    assert cipher.decrypt(b) == _TOKEN


def test_wrong_key_cannot_decrypt() -> None:
    """A token encrypted under one key is unreadable under another."""
    writer = CredentialCipher(keys=[_KEY])
    ciphertext = writer.encrypt(_TOKEN)

    attacker = CredentialCipher(keys=[_OTHER_KEY])
    with pytest.raises(InvalidToken):
        attacker.decrypt(ciphertext)


def test_tampered_ciphertext_is_rejected() -> None:
    """Authenticated encryption: a flipped byte fails rather than returning garbage."""
    cipher = CredentialCipher(keys=[_KEY])
    ciphertext = bytearray(cipher.encrypt(_TOKEN))
    ciphertext[-1] ^= 0x01  # flip a bit in the last byte
    with pytest.raises(InvalidToken):
        cipher.decrypt(bytes(ciphertext))


def test_key_rotation_old_tokens_still_decrypt() -> None:
    """MultiFernet: a fresh key leads, but tokens under the old key still read.

    New writes use the first (newest) key; existing ciphertext written under the
    prior key still decrypts because it remains in the list.
    """
    old = CredentialCipher(keys=[_KEY])
    legacy_ciphertext = old.encrypt(_TOKEN)

    # Rotate: new key first, old key retained for decryption.
    rotated = CredentialCipher(keys=[_OTHER_KEY, _KEY])
    assert rotated.decrypt(legacy_ciphertext) == _TOKEN

    # A new write uses the new key; the old-only cipher can no longer read it.
    fresh = rotated.encrypt(_TOKEN)
    assert old_cannot_read(fresh)


def old_cannot_read(ciphertext: bytes) -> bool:
    try:
        CredentialCipher(keys=[_KEY]).decrypt(ciphertext)
        return False
    except InvalidToken:
        return True


def test_no_keys_raises_not_configured() -> None:
    """With no key configured the cipher refuses to operate — fail closed."""
    with pytest.raises(EncryptionNotConfigured):
        CredentialCipher(keys=[])
    with pytest.raises(EncryptionNotConfigured):
        CredentialCipher(keys=None)


def test_blank_or_whitespace_keys_are_ignored() -> None:
    """Empty entries in a comma-split env value don't count as keys."""
    with pytest.raises(EncryptionNotConfigured):
        CredentialCipher(keys=["", "   "])


def test_from_settings_uses_the_configured_key(monkeypatch) -> None:
    """The default constructor reads the comma-separated CONNECTION_ENCRYPTION_KEY."""
    from app.services import crypto

    monkeypatch.setattr(crypto.settings, "CONNECTION_ENCRYPTION_KEY", _KEY)
    cipher = CredentialCipher.from_settings()
    assert cipher is not None
    assert cipher.decrypt(cipher.encrypt(_TOKEN)) == _TOKEN


def test_from_settings_returns_none_when_unset(monkeypatch) -> None:
    """No key configured → from_settings yields None (feature disabled, not crash)."""
    from app.services import crypto

    monkeypatch.setattr(crypto.settings, "CONNECTION_ENCRYPTION_KEY", None)
    assert CredentialCipher.from_settings() is None


def test_from_settings_parses_a_comma_separated_rotation_list(monkeypatch) -> None:
    """A 'newkey,oldkey' value is parsed into a rotating MultiFernet."""
    from app.services import crypto

    legacy = CredentialCipher(keys=[_KEY]).encrypt(_TOKEN)
    monkeypatch.setattr(
        crypto.settings, "CONNECTION_ENCRYPTION_KEY", f"{_OTHER_KEY},{_KEY}"
    )
    cipher = CredentialCipher.from_settings()
    assert cipher is not None
    assert cipher.decrypt(legacy) == _TOKEN  # old key still in the ring
