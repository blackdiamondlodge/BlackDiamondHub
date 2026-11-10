# feedback/views.py
import json
import logging
from functools import wraps
from urllib.parse import urlsplit

from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_POST

from hub.modes import current_stay, plugins

from .models import Feedback

log = logging.getLogger(__name__)


def _is_staff(user):
    return user.is_active and user.is_staff


staff_page = user_passes_test(_is_staff)


def staff_api(view):
    """Like ``staff_page`` but answers 403 JSON instead of redirecting."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not _is_staff(request.user):
            return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


def _stay_label(request):
    """"the <guest> stay" / "an owner visit" for the stay in progress, else ""."""
    try:
        stay = current_stay(request)
    except Exception:
        log.exception("stay lookup failed")
        return ''
    if not stay:
        return ''
    if stay.get('owner'):
        return 'an owner visit'
    guest = (stay.get('guest') or '').strip()
    return f'the {guest} stay'[:120] if guest else ''


@require_POST
def submit_feedback(request):
    message = (request.POST.get('message') or '').strip()
    if not message:
        return JsonResponse({'success': False, 'error': 'Empty message'}, status=400)
    Feedback.objects.create(
        message=message,
        page_url=(request.POST.get('page_url') or '')[:200],
        stay=_stay_label(request),
    )
    return JsonResponse({'success': True})


def get_unread_feedback_count(request):
    if request.user.is_authenticated and request.user.is_staff:
        count = Feedback.objects.filter(is_read=False).count()
    else:
        count = 0
    return JsonResponse({'unread_feedback_count': count})


def _page(page_url):
    """Title and tile icon of the hub page a message was sent from."""
    path = urlsplit(page_url or '').path or ''
    if path in ('', '/'):
        return {'title': 'Home', 'icon': ''}
    best, best_len = None, -1
    for spec in plugins():
        if not spec.urls or not spec.tiles:
            continue
        prefix = '/' + spec.prefix
        if path.startswith(prefix) and len(prefix) > best_len:
            best, best_len = spec, len(prefix)
    if best is None:
        return {'title': path, 'icon': ''}
    tile = best.tiles[0]
    try:
        icon = static(tile.icon) if tile.icon else ''
    except Exception:
        icon = ''
    return {'title': tile.title, 'icon': icon}


def _items():
    pages = {}
    items = []
    for fb in Feedback.objects.order_by('-submitted_at', '-id'):
        if fb.page_url not in pages:
            pages[fb.page_url] = _page(fb.page_url)
        items.append({
            'id': fb.id,
            'message': fb.message,
            'submitted_at': fb.submitted_at.isoformat(),
            'is_read': fb.is_read,
            'page': pages[fb.page_url],
            'stay': fb.stay,
        })
    return items


@staff_page
def view_feedback(request):
    return render(request, 'feedback/view_feedback.html', {'items': _items()})


@staff_api
def feedback_list(request):
    return JsonResponse({'items': _items()})


@require_POST
@staff_api
def bulk_feedback_action(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    feedback_ids = data.get('feedback_ids', [])
    action = data.get('action')
    if not feedback_ids or not action:
        return JsonResponse({'success': False, 'error': 'Missing data'}, status=400)

    rows = Feedback.objects.filter(id__in=feedback_ids)
    if action == 'delete':
        rows.delete()
    elif action == 'mark_read':
        rows.update(is_read=True)
    elif action == 'mark_unread':
        rows.update(is_read=False)
    else:
        return JsonResponse({'success': False, 'error': 'Invalid action'}, status=400)
    return JsonResponse({'success': True})
