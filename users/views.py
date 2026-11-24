from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import captcha, verification
from .forms import AccountForm, LoginForm, RegistrationForm

User = get_user_model()


def register(request):
    if request.user.is_authenticated:
        return redirect('cars:my_cars')
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid() and captcha.check(request, form):
        user = form.save(commit=False)
        user.language = get_language() or 'en'
        user.is_active = False  # until the email address is confirmed
        user.save()
        verification.send_link(request, user)
        request.session['verify_email'] = user.email
        return redirect('users:verify_sent')
    return render(request, 'users/register.html', {'form': form})


def verify_sent(request):
    """"Check your inbox" page with a button to send the link again."""
    email = request.session.get('verify_email', '')
    if request.method == 'POST':
        email = (request.POST.get('email') or email).strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        # Same answer whether or not the address is registered.
        if user and user.awaits_verification and verification.may_resend(request, user):
            verification.send_link(request, user)
        request.session['verify_email'] = email
        messages.success(request, _('If this address is waiting for confirmation, we have sent the link again.'))
        return redirect('users:verify_sent')
    return render(request, 'users/verify_sent.html', {'email': email})


def verify_email(request, uidb64, token):
    user = verification.user_from_link(uidb64, token)
    if user is None:
        return render(request, 'users/verify_failed.html', status=400)
    if not user.email_verified or not user.is_active:
        user.email_verified = True
        user.is_active = True
        user.save(update_fields=['email_verified', 'is_active'])
    request.session.pop('verify_email', None)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, _('Your email is confirmed. Welcome to FIBONACCI!'))
    return redirect('cars:my_cars')


def confirm_email_change(request, token):
    found = verification.email_change_from_link(token)
    if found is None:
        return render(request, 'users/verify_failed.html', status=400)
    user, new_email = found
    if User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
        messages.error(request, _('This email is already in use.'))
        return redirect('users:account')
    user.email = new_email
    user.email_verified = True
    user.save(update_fields=['email', 'email_verified'])
    messages.success(request, _('Your email has been changed to %(email)s.') % {'email': new_email})
    return redirect('users:account')


class EmailLoginView(LoginView):
    template_name = 'users/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True


@require_POST
def logout(request):
    auth_logout(request)
    return redirect('cars:home')


@login_required
def account(request):
    current_email = request.user.email
    form = AccountForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        new_email = form.cleaned_data['email']
        user = form.save(commit=False)
        user.email = current_email  # changes only after the new address is confirmed
        user.save()
        if new_email != current_email.lower():
            verification.send_change_link(request, user, new_email)
            notice = _('To change your email, open the link we sent to %(email)s. Until then your current address stays.')  # noqa: E501
            messages.info(request, notice % {'email': new_email})
        else:
            messages.success(request, _('Your details have been saved.'))
        return redirect('users:account')
    return render(request, 'users/account.html', {'form': form, 'section': 'account'})
