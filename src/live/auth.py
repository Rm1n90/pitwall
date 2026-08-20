"""Formula 1 account handling for the lowest-latency live feed.

Timing, track status, weather and race control reach unauthenticated clients
on the SignalR feed. The car position and telemetry topics may additionally
require a Formula 1 account with an F1 TV subscription.

FastF1 owns the browser sign-in flow but keeps it in a private module, so
everything here degrades gracefully if that module moves: live mode still runs,
just on the public static feed.
"""

from typing import Optional

UNAVAILABLE_MESSAGE = (
    "FastF1's Formula 1 sign-in helper is not available in this version. "
    "Live mode will use the public timing archive instead, which needs no "
    "account."
)


def _f1auth():
    try:
        from fastf1.internals import f1auth
    except ImportError:
        return None
    return f1auth


def get_token_provider() -> Optional[callable]:
    """Return a callable that yields an account token, or ``None``.

    The returned callable never raises: if sign-in fails it yields an empty
    token and the connection proceeds anonymously.
    """
    module = _f1auth()
    if module is None:
        return None

    def _provider() -> str:
        try:
            return module.get_auth_token() or ""
        except Exception as exc:
            print(f"[live] could not obtain a Formula 1 token: {exc}")
            return ""

    return _provider


def print_status() -> int:
    """Print whether a Formula 1 token is stored. Returns an exit code."""
    module = _f1auth()
    if module is None:
        print(UNAVAILABLE_MESSAGE)
        return 1
    try:
        module.print_auth_status()
    except Exception as exc:
        print(f"Could not read the sign-in status: {exc}")
        return 1
    return 0


def sign_in() -> int:
    """Run the browser sign-in flow. Returns an exit code."""
    module = _f1auth()
    if module is None:
        print(UNAVAILABLE_MESSAGE)
        return 1
    try:
        # Clearing first guarantees the browser flow runs rather than
        # silently reusing a token the user wanted to replace.
        module.clear_auth_token()
        token = module.get_auth_token()
    except Exception as exc:
        print(f"Sign-in failed: {exc}")
        return 1
    if not token:
        print("Sign-in did not complete.")
        return 1
    print("Signed in. Live mode will now use the SignalR car data feed.")
    return 0


def sign_out() -> int:
    """Forget any stored Formula 1 token. Returns an exit code."""
    module = _f1auth()
    if module is None:
        print(UNAVAILABLE_MESSAGE)
        return 1
    try:
        module.clear_auth_token()
    except Exception as exc:
        print(f"Could not clear the stored token: {exc}")
        return 1
    print("Signed out.")
    return 0
