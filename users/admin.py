from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import CustomUser


class CustomUserAdmin(UserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    date_hierarchy = 'date_joined'
    list_display = ('email', 'last_name', 'first_name', 'phone', 'country', 'language', 'date_joined')
    list_filter = ('is_staff', 'is_active', 'language', 'country')
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {
            'fields': ('last_name', 'first_name', 'middle_name', 'phone', 'country', 'language')
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser',
                       'groups', 'user_permissions')
        }),
        ('Important dates', {
            'fields': ('last_login', 'date_joined')
        }),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1',
                       'password2', 'is_staff', 'is_active'),
        }),
    )


    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'username' in form.base_fields:
            form.base_fields['username'].disabled = True

        return form
    

admin.site.register(CustomUser, CustomUserAdmin)

# Groups and Google/Apple accounts in the same admin style. Social apps,
# tokens and email records are configured in settings and not edited here.
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


for model in (SocialApp, SocialToken, EmailAddress, SocialAccount):
    if admin.site.is_registered(model):
        admin.site.unregister(model)


@admin.register(SocialAccount)
class SocialAccountAdmin(ModelAdmin):
    list_display = ('user', 'provider', 'uid', 'date_joined', 'last_login')
    list_filter = ('provider',)
    search_fields = ('user__email', 'uid')
    readonly_fields = ('user', 'provider', 'uid', 'extra_data', 'date_joined', 'last_login')

    def has_add_permission(self, request):
        return False
