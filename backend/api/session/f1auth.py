"""FASTF1_AUTH switch for FastF1 >= 3.9 (F1 livetiming needs an F1TV Bearer token since ~2026-10).

    FASTF1_AUTH=none   (default) never send a token and never try to log in.
    FASTF1_AUTH=token  send the token stored by the one-time login (see docs/v2/VM_RUNBOOK.md) when it is
                       still valid. The app never logs in by itself (no credentials in env, no prompts);
                       when the token expires, FastF1 logs a warning and continues unauthenticated, and the
                       operator repeats the login command.

The token file lives where FastF1 puts it: <XDG_DATA_HOME>/fastf1/f1auth_token.json; compose sets
XDG_DATA_HOME=/fastf1-auth, a named volume, so it is never in git or in the image.
"""
import logging

logger = logging.getLogger(__name__)


def apply_auth_mode(mode, token_manager, auth_error):
    """Configure a FastF1 TokenManager for `mode`. `auth_error` is fastf1.exceptions.F1AuthError."""
    mode = (mode or "none").strip().lower()
    if mode not in ("none", "token"):
        logger.warning("FASTF1_AUTH=%r is not none|token; using none", mode)
        mode = "none"

    def _never_login():
        raise auth_error("automatic F1 sign-in is disabled; run the one-time login (docs/v2/VM_RUNBOOK.md)")

    # ponytail: pokes FastF1's TokenManager attributes (private-ish, pinned fastf1==3.9.2); if a FastF1
    # upgrade renames them the tests below fail loudly.
    token_manager._default_auth_func = _never_login
    if mode == "none":
        token_manager.get_stored = lambda: None
    return mode
