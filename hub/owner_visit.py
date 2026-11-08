"""Signs the hub in as the owners while they're staying (an owner visit).

Nothing is stored in the session: each request checks the current stay, so
the hub signs itself out when the visit ends. Anyone on the network gets
owner access during the visit, like at the kiosk.
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.functional import SimpleLazyObject

from .modes import current_stay

logger = logging.getLogger(__name__)


def owner_visit_user():
    return getattr(settings, "HUB_OWNER_VISIT_USER", "")


def _resolve(request, user, username):
    if user.is_authenticated:
        return user
    stay = current_stay(request)
    if not (stay and stay.get("owner")):
        return user
    model = get_user_model()
    try:
        owner = model.objects.get(**{model.USERNAME_FIELD: username, "is_active": True})
    except model.DoesNotExist:
        logger.warning("Owner visit user %r doesn't exist or is inactive", username)
        return user
    request.owner_visit = True
    return owner


class OwnerVisitMiddleware:
    """Goes after AuthenticationMiddleware; off unless HUB_OWNER_VISIT_USER is set."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        username = owner_visit_user()
        if username:
            user = request.user
            request.user = SimpleLazyObject(lambda: _resolve(request, user, username))
        return self.get_response(request)
