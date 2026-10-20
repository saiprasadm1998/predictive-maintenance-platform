"""Password rules and hashing (FR-SEC-01, decision 5.1)."""

from __future__ import annotations

import pytest

from pmp.core import UserError, check_password
from pmp.core.users import _verify, hash_password


@pytest.mark.parametrize(
    ("password", "problem"),
    [("short-pw", "at least 12"), ("xx-alice-pass-xx", "username"), ("XXALICEXXXXXXX", "username")],
)
def test_weak_passwords_are_refused(password: str, problem: str) -> None:
    with pytest.raises(UserError, match=problem):
        check_password("alice", password)


def test_a_long_passphrase_is_fine() -> None:
    check_password("alice", "correct horse battery")


def test_hashes_are_argon2id_and_salted() -> None:
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert first.startswith("$argon2id$")
    assert first != second
    assert _verify(first, "correct horse battery")
    assert not _verify(first, "wrong horse battery")
    assert not _verify("not a hash", "anything")
