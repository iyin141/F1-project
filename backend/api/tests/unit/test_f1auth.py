"""FASTF1_AUTH switch: no automatic login in either mode; `none` also hides any stored token."""
import pytest

from api.session.f1auth import apply_auth_mode


class _Err(Exception):
    pass


class _TM:
    _default_auth_func = None

    def get_stored(self):
        return "stored-token"


def test_none_hides_stored_token_and_never_logs_in():
    tm = _TM()
    assert apply_auth_mode(None, tm, _Err) == "none"
    assert tm.get_stored() is None
    with pytest.raises(_Err):
        tm._default_auth_func()


def test_token_mode_keeps_stored_token_but_never_logs_in():
    tm = _TM()
    assert apply_auth_mode("token", tm, _Err) == "token"
    assert tm.get_stored() == "stored-token"
    with pytest.raises(_Err):
        tm._default_auth_func()


def test_unknown_value_falls_back_to_none():
    assert apply_auth_mode("browser", _TM(), _Err) == "none"


def test_real_fastf1_token_manager_still_has_the_attributes_we_patch():
    f1account = pytest.importorskip("fastf1.internals.f1account")
    tm = f1account.token_manager
    assert hasattr(tm, "_default_auth_func") and callable(tm.get_stored)
