"""Liveness/readiness endpoint used by the Docker HEALTHCHECK and CI."""
from django.db import connection
from django.http import JsonResponse

HEALTH_PATH = '/healthz'


class HealthCheckMiddleware:
    """Answer ``/healthz`` before any other middleware.

    It runs ahead of CommonMiddleware so probes from inside the container
    (Host: 127.0.0.1) are not rejected by ALLOWED_HOSTS.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != HEALTH_PATH:
            return self.get_response(request)
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception as exc:  # noqa: BLE001 - any DB failure means unhealthy
            return JsonResponse({'status': 'error', 'db': str(exc)[:200]}, status=503)
        return JsonResponse({'status': 'ok'})
