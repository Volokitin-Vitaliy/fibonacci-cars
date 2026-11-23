from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.utils.translation import get_language


class AccountAdapter(DefaultAccountAdapter):
    """Accounts are created by our own sign-up form; allauth is only used for
    Google / Apple sign-in, so its email/password sign-up stays closed."""

    def is_open_for_signup(self, request):
        return False


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return True

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        extra = sociallogin.account.extra_data or {}
        # Google: given_name/family_name; Apple sends the name only on the first sign-in.
        name = extra.get('name') if isinstance(extra.get('name'), dict) else {}
        user.first_name = (data.get('first_name') or extra.get('given_name')
                           or name.get('firstName') or '')[:50]
        user.last_name = (data.get('last_name') or extra.get('family_name')
                          or name.get('lastName') or '')[:50]
        if user.email:
            user.email = user.email.lower()
        user.language = (get_language() or 'en')[:2]
        return user
