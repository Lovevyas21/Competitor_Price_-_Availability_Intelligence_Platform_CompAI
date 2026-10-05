from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import require_api_key
from app.core.settings import Settings


def test_no_key_configured_allows_anonymous_access():
    require_api_key(x_api_key=None, settings=Settings(api_key=None))


def test_correct_key_is_accepted():
    require_api_key(x_api_key="secret", settings=Settings(api_key="secret"))


def test_missing_key_is_rejected_when_one_is_configured():
    with pytest.raises(HTTPException) as exc:
        require_api_key(x_api_key=None, settings=Settings(api_key="secret"))
    assert exc.value.status_code == 401


def test_wrong_key_is_rejected():
    with pytest.raises(HTTPException) as exc:
        require_api_key(x_api_key="wrong", settings=Settings(api_key="secret"))
    assert exc.value.status_code == 401


def test_rejection_includes_a_challenge_header():
    with pytest.raises(HTTPException) as exc:
        require_api_key(x_api_key="", settings=Settings(api_key="secret"))
    assert "WWW-Authenticate" in exc.value.headers


@pytest.mark.parametrize("supplied", ["secre", "secrett", "SECRET", " secret"])
def test_near_miss_keys_are_rejected(supplied):
    with pytest.raises(HTTPException):
        require_api_key(x_api_key=supplied, settings=Settings(api_key="secret"))
