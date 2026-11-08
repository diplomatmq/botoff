from __future__ import annotations

from app.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    mask_token,
    sanitize_payload,
    token_fingerprint,
    verify_password,
)

TOKEN = "prt_live_abcdefghijklmnop1234567890"


def test_password_hash_roundtrip():
    stored = hash_password("super-secret-pass")
    assert stored.startswith("scrypt$")
    assert verify_password("super-secret-pass", stored) is True
    assert verify_password("wrong-pass", stored) is False


def test_password_hash_is_salted():
    assert hash_password("same") != hash_password("same")


def test_encrypt_decrypt_roundtrip():
    ciphertext = encrypt_secret(TOKEN)
    assert ciphertext != TOKEN
    assert decrypt_secret(ciphertext) == TOKEN


def test_mask_token_keeps_edges_only():
    masked = mask_token(TOKEN)
    assert masked == "prt_****7890"
    assert TOKEN not in masked


def test_sanitize_payload_removes_secrets():
    payload = {
        "amount": "1",
        "Authorization": "partners secret-token",
        "nested": {"token": "abc", "password": "x"},
    }
    clean = sanitize_payload(payload)
    assert clean["Authorization"] == "***"
    assert clean["nested"]["token"] == "***"
    assert clean["nested"]["password"] == "***"
    assert clean["amount"] == "1"


def test_sanitize_payload_handles_lists():
    clean = sanitize_payload([{"token": "abc"}])
    assert clean[0]["token"] == "***"


def test_token_fingerprint_is_stable_and_not_reversible():
    first = token_fingerprint(TOKEN)
    assert first == token_fingerprint(TOKEN)
    assert TOKEN not in first
    assert len(first) == 64
