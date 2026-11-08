from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth import logout
from django.urls import reverse
from django.db.models import Q
from .forms import ItemForm  # Ensure you have an ItemForm in forms.py
from .models import Item
from django.http import JsonResponse
import json

import base64
import qrcode
import io

def index(request):
    keyword = request.GET.get('keyword', '')
    
    if keyword:
        items = Item.objects.filter(
            Q(name__icontains=keyword) |
            Q(description__icontains=keyword) |
            Q(room__icontains=keyword) |
            Q(desc_long__icontains=keyword)
        ).order_by('id')
    else:
        items = Item.objects.all().order_by('id')
    
    context = {
        'items': items,
        'keyword': keyword
    }
    
    return render(request, 'inventory/inventory.html', context)

def item_detail(request, id):
    item = get_object_or_404(Item, pk=id)
    
    # Generate QR code
    item_url = request.build_absolute_uri(reverse('item_detail', args=[id]))
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(item_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_code_data = base64.b64encode(buffer.getvalue()).decode("utf-8")    
    
    context = {
        'item': item,
        'qr_code_data': qr_code_data,  # Pass the QR code data to the template
    }
    return render(request, 'inventory/item_detail.html', context)

def item_detail_json(request, id):
    item = get_object_or_404(Item, pk=id)
    
    item_url = request.build_absolute_uri(reverse('item_detail', args=[id]))
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(item_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_code_data = base64.b64encode(buffer.getvalue()).decode("utf-8")     
    
    item_data = {
        'id': item.id,
        'name': item.name,
        'image': item.picture.url,
        'description': item.description,
        'room': item.room,
        'desc_long': item.desc_long,
        'qr_code': qr_code_data,
    }
    return JsonResponse(item_data)

@login_required
def edit_item(request, id):
    # Get the item object or return 404 if not found
    item = get_object_or_404(Item, pk=id)
    
    print(f"Editing item: {item}, request method: {request.method}")
    
    # If the request is POST, it means the form was submitted
    if request.method == 'POST':
        # Bind the form to the POST data and the current item instance
        form = ItemForm(request.POST, request.FILES, instance=item)
        
        if form.is_valid():
            # Save the form and redirect to the inventory view
            print("Form is valid. Saving...")
            form.save()
            return redirect('inventory')
        else:
            print(f"Form is invalid. Errors: {form.errors}")
    else:
        # If the request is GET, populate the form with the item data
        form = ItemForm(instance=item)
    
    # Render the inventory/edit.html template with the form and item data
    return render(request, 'inventory/edit.html', {'form': form, 'item': item})

@login_required
@require_POST
def update_item(request, id):
    # Check if the user is a staff member
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    # Get the item by ID or return 404 if not found
    item = get_object_or_404(Item, pk=id)

    try:
        # Parse the JSON data from the request body
        data = json.loads(request.body)
        
        # Update the item fields with the provided data
        item.room = data.get('room', item.room)
        item.description = data.get('description', item.description)
        item.desc_long = data.get('long_description', item.desc_long)

        # Save the item
        item.save()

        # Return a success response
        return JsonResponse({'success': True})

    except (KeyError, ValueError) as e:
        # Handle missing or invalid data
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
  
def add_item(request):
    if request.method == 'POST':
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('inventory')  # Redirect to the inventory page after adding the item
    else:
        form = ItemForm()
    return render(request, 'inventory/add_item.html', {'form': form})
  
  
@login_required
def profile(request):
    return render(request, 'inventory/profile.html')
