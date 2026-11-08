"""Spotify social-auth hooks owned by the hub platform.

Spotify login (social_django) is configured in core settings, so its
template context processor and disconnect-pipeline steps live here rather
than in an installable app.
"""
from django.contrib.auth import logout as auth_logout
from django.shortcuts import redirect
from social_django.models import UserSocialAuth

def custom_allowed_to_disconnect(strategy, user, name, user_storage, *args, **kwargs):
    return {}
    # # Custom logic to allow disconnection
    # # For example, check if the user has other authentication methods:
    # if user.social_auth.count() > 1 or user.has_usable_password():
    #     return {}
    # else:
    #     return strategy.redirect('some-page-to-prevent-disconnection')
    

def revoke_tokens(strategy, user, *args, **kwargs):
    try:
        # Check if the user has a Spotify social authentication
        social = user.social_auth.get(provider='spotify')
        print(f"Revoking access token: {social.extra_data['access_token']}")
        print(f"Revoking refresh token: {social.extra_data.get('refresh_token')}")
        
        # Revoke the tokens
        strategy.backend.revoke_token(social.extra_data['access_token'])
        strategy.backend.revoke_token(social.extra_data.get('refresh_token'))

        print("Tokens should now be revoked.")
    except UserSocialAuth.DoesNotExist:
        print("User does not have a Spotify social authentication.")
        # Optionally, handle the case where the user doesn't have a Spotify account connected
        return {}

    return {}

    
    
def clear_session_and_logout(strategy, user, *args, **kwargs):
    # Clear the session and logout the user
    request = strategy.request
    if user:
        auth_logout(request)  # This logs out the user and clears the session
        print("User logged out and session cleared.")
    return {}


def spotify_token(request):
    """Template context: whether this session holds a Spotify token."""
    return {"has_spotify_token": request.session.get("spotify_token_info") is not None}
