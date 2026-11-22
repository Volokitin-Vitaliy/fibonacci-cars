from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import AccountForm, LoginForm, RegistrationForm


def register(request):
    if request.user.is_authenticated:
        return redirect('cars:my_cars')
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(commit=False)
        user.language = get_language() or 'en'
        user.save()
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, _('Welcome! Your account has been created.'))
        return redirect('cars:my_cars')
    return render(request, 'users/register.html', {'form': form})


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
    form = AccountForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Your details have been saved.'))
        return redirect('users:account')
    return render(request, 'users/account.html', {'form': form, 'section': 'account'})
