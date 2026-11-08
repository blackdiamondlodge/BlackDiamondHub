from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST, require_GET
import json

from .executor import (
    get_away_mode_state,
    get_current_season,
    start_execution,
    get_run_status,
    get_active_run,
)
from .steps import build_vacation_steps, build_home_steps, SEASON_COOLING
from . import bdl_client


@login_required
def vacation_mode_view(request):
    """Main page view — renders the vacation mode UI."""
    if bdl_client.enabled():
        return bdl_modes_view(request)
    is_away = get_away_mode_state()
    active_run = get_active_run()

    # Determine which steps to show based on current state
    if active_run:
        # If a run is in progress, show those steps
        mode = active_run["mode"]
        steps = active_run["steps"]
        run_id = active_run["run_id"]
        season = active_run.get("season")
        season_avg = active_run.get("season_avg")
    else:
        # Show the steps for the action they'd take next, for the season the
        # system would pick right now.
        season, season_avg = get_current_season()
        mode = "home" if is_away else "vacation"
        steps_def = (
            build_home_steps(season) if is_away else build_vacation_steps(season)
        )
        steps = [
            {"alias": s["alias"], "icon": s["icon"], "status": "pending", "attempt": 0, "error": None, "progress": None}
            for s in steps_def
        ]
        run_id = None

    context = {
        "is_away": is_away,
        "mode": mode,
        "steps": json.dumps(steps),
        "run_id": run_id,
        "active_run": active_run is not None,
        "season": season,
        "season_is_cooling": season == SEASON_COOLING,
        "season_avg": season_avg,
    }
    return render(request, "vacation_mode/vacation_mode.html", context)


@login_required
@require_POST
def execute_view(request):
    """API endpoint to start executing vacation or home mode steps."""
    try:
        body = json.loads(request.body)
        mode = body.get("mode")
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid request body"}, status=400)

    if mode not in ("vacation", "home"):
        return JsonResponse({"error": "Invalid mode. Must be 'vacation' or 'home'"}, status=400)

    dry_run = body.get("dry_run", False)
    skip_steps = body.get("skip_steps", [])

    run_id, error = start_execution(mode, dry_run=dry_run, skip_steps=skip_steps)
    if error:
        return JsonResponse({"error": error}, status=409)

    return JsonResponse({"run_id": run_id, "mode": mode})


@login_required
@require_GET
def status_view(request, run_id):
    """API endpoint to poll the status of a run."""
    run_data = get_run_status(run_id)
    if not run_data:
        return JsonResponse({"error": "Run not found"}, status=404)

    return JsonResponse(run_data)


@login_required
@require_GET
def state_view(request):
    """API endpoint to get current away mode state and any active run."""
    is_away = get_away_mode_state()
    active_run = get_active_run()

    return JsonResponse({
        "is_away": is_away,
        "active_run": {
            "run_id": active_run["run_id"],
            "mode": active_run["mode"],
            "steps": active_run["steps"],
        } if active_run else None,
    })


# --------------------------------------------------------------------------
# bdl_modes (AppDaemon) client views — used when BDL_MODES_URL is set.

@login_required
def bdl_modes_view(request):
    status, error, _ = bdl_client.call("status")
    previews = {}
    if status:
        for kind in ("vacation", "home"):
            p, err, _ = bdl_client.call("preview", kind=kind)
            previews[kind] = p["groups"] if p else []
            error = error or err
    return render(request, "vacation_mode/bdl_modes.html", {
        "status": status,
        "previews": previews,
        "error": error,
        "preheat_enabled": settings.BDL_MODES_PREHEAT,
        "allow_dry_run": request.user.is_staff,
    })


@login_required
@require_GET
def bdl_modes_status_view(request):
    data, error, code = bdl_client.call("status")
    if error:
        return JsonResponse({"error": error}, status=code)
    return JsonResponse(data)


@login_required
@require_POST
def bdl_modes_command_view(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid request body"}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({"error": "Invalid request body"}, status=400)
    cmd = body.get("cmd")
    if cmd not in bdl_client.COMMANDS:
        return JsonResponse({"error": "Unknown command"}, status=400)
    if cmd == "preheat" and not settings.BDL_MODES_PREHEAT:
        return JsonResponse({"error": "Preheat is not enabled"}, status=400)
    skip = body.get("skip_steps")
    if skip is not None and not (
            isinstance(skip, list) and all(isinstance(s, str) for s in skip)):
        return JsonResponse({"error": "Invalid skip_steps"}, status=400)
    data, error, code = bdl_client.call(
        cmd, arrival=body.get("arrival"), skip_steps=skip,
        request_id=str(body["request_id"])[:64]
        if body.get("request_id") else None,
        dry_run=True if (body.get("dry_run") and request.user.is_staff)
        else None)
    if error:
        return JsonResponse({"error": error}, status=code)
    return JsonResponse(data)