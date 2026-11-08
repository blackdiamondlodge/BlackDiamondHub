import io
import base64
import qrcode

from django.conf import settings
from django.shortcuts import render

def wifi_qr(request):
    # Choose networks based on authentication.
    if request.user.is_authenticated:
        networks = settings.WIFI_NETWORKS_AUTH
    else:
        networks = settings.WIFI_NETWORKS_PUBLIC

    qr_codes = []
    for network in networks:
        ssid = network.strip()

        # Look up a password from settings based on the SSID.
        # Construct the key typically by uppercasing and replacing spaces.
        key = f'WIFI_PASSWORD_FOR_{ssid.upper().replace(" ", "_")}'
        password = getattr(settings, key, 'password')
        
        print(f"SSID: {ssid}, Password: {password}")

        # For QR code generation, we use the typical WiFi QR code string format.
        # Format: WIFI:S:<SSID>;T:WPA;P:<password>;;
        qr_text = f"WIFI:S:{ssid};T:WPA;P:{password};;"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_text)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        qr_codes.append({'ssid': ssid, 'qr_image': image_base64, 'password': password})

    return render(request, 'wifi/wifi_qr.html', {'qr_codes': qr_codes})