"""Cookie-based identity: which browser is which ``User``, without a login.

``opinions.User`` has no password (see its docstring in models.py), so there
is nothing to authenticate against -- a browser is simply linked to a
``User`` by a signed cookie carrying that user's public uuid. Django's own
cookie signing (keyed off ``SECRET_KEY``) makes the cookie tamper-evident
without any new dependency: a visitor can't claim someone else's uuid by
editing the cookie by hand, since ``get_signed_cookie`` rejects a bad
signature the same way a missing cookie is rejected -- both come back as "no
identity", never as a different, wrong user.
"""

from .models import User

IDENTITY_COOKIE = "hivemind_user"
SALT = "opinions.identity"
# Long-lived by design: this cookie is the only thing standing in for an
# account. Two years, matching add_fictional_geo_time's "plausible recent
# span" order of magnitude elsewhere in this project.
MAX_AGE = 60 * 60 * 24 * 365 * 2


def get_current_user(request):
    """The ``User`` this browser is identified as, or ``None``.

    ``None`` covers a missing cookie, a tampered/unsigned one, and one
    naming a uuid that no longer exists (e.g. deleted by hand in /admin) --
    all three mean the same thing to a caller: this browser has no identity
    yet.
    """
    value = request.get_signed_cookie(IDENTITY_COOKIE, default=None, salt=SALT)
    if not value:
        return None
    return User.objects.filter(uuid=value).first()


def remember(response, user):
    """Attach ``user``'s identity cookie to an outgoing ``response``."""
    response.set_signed_cookie(
        IDENTITY_COOKIE,
        str(user.uuid),
        salt=SALT,
        max_age=MAX_AGE,
        httponly=True,
        samesite="Lax",
    )
