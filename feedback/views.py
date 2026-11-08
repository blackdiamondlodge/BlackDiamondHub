# feedback/views.py
import json
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.dateparse import parse_datetime
from .models import Feedback
from django.http import JsonResponse
from django_tables2 import RequestConfig
from .tables import FeedbackTable

def submit_feedback(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')
        page_url = request.POST.get('page_url', '')
        
        Feedback.objects.create(name=name, email=email, page_url=page_url, message=message)
        return JsonResponse({'success': True})  # Return a JSON response indicating success

    return JsonResponse({'success': False})  # Return a JSON response indicating failure

def get_unread_feedback_count(request):
    if request.user.is_authenticated and request.user.is_staff:
        count = Feedback.objects.filter(is_read=False).count()
    else:
        count = 0
    return JsonResponse({'unread_feedback_count': count})

def view_feedback(request):
    feedback_queryset = Feedback.objects.all().order_by('-submitted_at')
    table = FeedbackTable(feedback_queryset)
    RequestConfig(request, paginate={"per_page": 20}).configure(table)
    return render(request, "feedback/view_feedback.html", {"table": table})

def refresh_feedback_table(request):
    # Get the current page number from the request, default to 1
    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', 20)
    
    # Apply ordering here before pagination
    feedback_queryset = Feedback.objects.all().order_by('-submitted_at')
    
    table = FeedbackTable(feedback_queryset)
    table.paginate(page=page_number, per_page=page_size)

    # Render the partial table view
    return render(request, "feedback/partials/feedback_table.html", {"table": table})


def bulk_feedback_action(request):
    if request.method == 'POST':
        # Parse the JSON body of the request
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

        feedback_ids = data.get('feedback_ids', [])
        action = data.get('action')

        if not feedback_ids or not action:
            return JsonResponse({'success': False, 'error': 'Missing data'}, status=400)

        print(f'{action} Feedback IDs: {feedback_ids}')

        if action == 'delete':
            Feedback.objects.filter(id__in=feedback_ids).delete()
        elif action == 'mark_read':
            Feedback.objects.filter(id__in=feedback_ids).update(is_read=True)
        elif action == 'mark_unread':
            Feedback.objects.filter(id__in=feedback_ids).update(is_read=False)
        else:
            return JsonResponse({'success': False, 'error': 'Invalid action'}, status=400)

        return JsonResponse({'success': True})

    return redirect('view_feedback')