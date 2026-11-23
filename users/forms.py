from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from cars.forms import country_choices, phone_validator

User = get_user_model()


class ProfileFieldsMixin(forms.Form):
    first_name = forms.CharField(label=_('First name'), max_length=50)
    last_name = forms.CharField(label=_('Last name'), max_length=50)
    middle_name = forms.CharField(label=_('Middle name'), max_length=50, required=False)
    country = forms.ChoiceField(label=_('Country'), choices=country_choices)


class AccountFieldsMixin(ProfileFieldsMixin):
    phone = forms.CharField(label=_('Phone'), max_length=30, validators=[phone_validator],
                            required=False)
    country = forms.ChoiceField(label=_('Country'), choices=country_choices, required=False)

    def clean_phone(self):
        phone = ' '.join(self.cleaned_data['phone'].split())
        if not phone:
            return None
        taken = User.objects.filter(phone=phone)
        if self.instance and self.instance.pk:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError(_('This phone number is already registered.'))
        return phone


class RegistrationForm(ProfileFieldsMixin, UserCreationForm):
    email = forms.EmailField(label=_('Email'), max_length=254)
    middle_name = None  # not asked at sign-up

    class Meta:
        model = User
        fields = ('last_name', 'first_name', 'email', 'country')

    field_order = ('last_name', 'first_name', 'email', 'country',
                   'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_('This email is already in use.'))
        return email


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label=_('Email'), widget=forms.EmailInput(attrs={'autofocus': True}))


class AccountForm(AccountFieldsMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ('last_name', 'first_name', 'middle_name', 'email', 'phone', 'country')

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_('This email is already in use.'))
        return email
