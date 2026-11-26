from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from . import services
from .models import Car, CarPhoto, Favorite, ImportRun, ListingPeriod, Make, Payment


@admin.register(Make)
class MakeAdmin(ModelAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


class CarPhotoInline(TabularInline):
    model = CarPhoto
    extra = 0


class ListingPeriodInline(TabularInline):
    model = ListingPeriod
    extra = 0
    readonly_fields = ('starts_at', 'ends_at', 'amount', 'method', 'created_at')


class ModerationFilter(admin.SimpleListFilter):
    title = _('moderation')
    parameter_name = 'moderation'

    def lookups(self, request, model_admin):
        return Car.Moderation.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(source=Car.Source.USER, moderation=self.value())
        return queryset


HOME_HELP = _('Cars shown in the slideshow at the top of the home page (lower number first). Without any, the most expensive cars are shown.')  # noqa: E501


@admin.register(Car)
class CarAdmin(ModelAdmin):
    list_display = ('title_with_make', 'source_badge', 'moderation_badge', 'price_display',
                    'status_badge', 'show_on_home', 'home_order', 'active_until', 'owner', 'created_at')
    list_display_links = ('title_with_make',)
    list_editable = ('show_on_home', 'home_order')
    list_filter = (ModerationFilter, 'show_on_home', 'source', 'status', 'is_published', 'is_new',
                   'fuel', 'accident', 'make')
    search_fields = ('model', 'make__name', 'external_id', 'owner__email', 'contact_phone')
    autocomplete_fields = ('make',)
    raw_id_fields = ('owner',)
    inlines = (CarPhotoInline, ListingPeriodInline)
    actions = ('approve_selected', 'reject_selected', 'add_to_home', 'remove_from_home')
    list_per_page = 50
    date_hierarchy = 'created_at'
    readonly_fields = ('price_eur', 'external_id', 'source_url', 'last_synced_at',
                       'created_at', 'updated_at')
    fieldsets = (
        (_('Moderation'), {'fields': ('moderation', 'rejection_reason')}),
        (_('Vehicle'), {'fields': (('make', 'fuel'), 'model', 'description')}),
        (_('Characteristics'), {'fields': (('year', 'mileage_km'), ('transmission', 'accident'),
                                           ('power_hp', 'color'), 'specs')}),
        (_('Price'), {'fields': (('price', 'currency'), 'price_net', 'price_eur')}),
        (_('Contacts'), {'fields': ('owner', 'contact_name', 'contact_phone',
                                    'contact_whatsapp', 'contact_telegram')}),
        (_('Publication'), {'fields': ('source', 'status', ('activated_at', 'active_until'),
                                       'is_published', 'is_new')}),
        (_('Home page'), {'fields': (('show_on_home', 'home_order'),),
                          'description': HOME_HELP}),
        (_('Import'), {'classes': ('collapse',),
                       'fields': ('external_id', 'source_url', 'last_synced_at',
                                  'created_at', 'updated_at')}),
    )

    @display(description=_('Vehicle'), header=True)
    def title_with_make(self, obj):
        return obj.model, obj.make.name

    @display(description=_('Source'), label={'hollmann': 'info', 'user': 'primary'})
    def source_badge(self, obj):
        return obj.source, ('Hollmann' if obj.is_imported else _('Private'))

    @display(description=_('moderation'), label={'pending': 'warning', 'approved': 'success',
                                                   'rejected': 'danger'})
    def moderation_badge(self, obj):
        if obj.source != Car.Source.USER:
            return None
        return obj.moderation, obj.get_moderation_display()

    @display(description=_('Price'), ordering='price_eur')
    def price_display(self, obj):
        return f'{obj.currency_symbol}{obj.price:,.0f}'

    @display(description=_('Status'), label={'active': 'success', 'inactive': 'info',
                                               'hidden': 'danger'})
    def status_badge(self, obj):
        if obj.is_imported:
            return ('active', _('Active')) if obj.is_published else ('hidden', _('Removed'))
        return ('active', _('Active')) if obj.is_listing_active else ('inactive', _('Inactive'))

    def save_model(self, request, obj, form, change):
        # Changing "moderation" in the form goes through the same steps as the
        # list actions: the first month starts and the owner gets an email.
        moderation_changed = change and 'moderation' in form.changed_data
        new_state = obj.moderation
        if moderation_changed and obj.source == Car.Source.USER:
            obj.moderation = form.initial.get('moderation')
        super().save_model(request, obj, form, change)
        if moderation_changed and obj.source == Car.Source.USER:
            if new_state == Car.Moderation.APPROVED:
                services.approve(obj)
            elif new_state == Car.Moderation.REJECTED:
                services.reject(obj, obj.rejection_reason)
            else:
                obj.moderation = new_state
                obj.save(update_fields=['moderation'])

    @admin.action(description=_('Approve selected listings'))
    def approve_selected(self, request, queryset):
        count = 0
        for car in queryset.filter(source=Car.Source.USER).exclude(moderation=Car.Moderation.APPROVED):
            services.approve(car)
            count += 1
        self.message_user(request, _('Approved: %(n)s') % {'n': count}, messages.SUCCESS)

    @admin.action(description=_('Show on the home page'))
    def add_to_home(self, request, queryset):
        count = queryset.update(show_on_home=True)
        self.message_user(request, _('On the home page: %(n)s') % {'n': count}, messages.SUCCESS)

    @admin.action(description=_('Remove from the home page'))
    def remove_from_home(self, request, queryset):
        count = queryset.update(show_on_home=False)
        self.message_user(request, _('Removed from the home page: %(n)s') % {'n': count}, messages.SUCCESS)

    @admin.action(description=_('Reject selected listings'))
    def reject_selected(self, request, queryset):
        count = 0
        for car in queryset.filter(source=Car.Source.USER).exclude(moderation=Car.Moderation.REJECTED):
            services.reject(car)
            count += 1
        self.message_user(
            request,
            _('Rejected: %(n)s. To give a reason, open the listing and fill in "rejection reason".')
            % {'n': count}, messages.WARNING)


@admin.register(Favorite)
class FavoriteAdmin(ModelAdmin):
    list_display = ('user', 'car', 'created_at')
    raw_id_fields = ('user', 'car')


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = ('created_at', 'car', 'user', 'amount', 'currency', 'provider', 'status',
                    'paid_at', 'used_at')
    list_filter = ('status', 'provider')
    search_fields = ('reference', 'user__email')
    readonly_fields = [f.name for f in Payment._meta.fields]


@admin.register(ImportRun)
class ImportRunAdmin(ModelAdmin):
    list_display = ('started_at', 'finished_at', 'ok', 'created', 'updated', 'unpublished')
    readonly_fields = [f.name for f in ImportRun._meta.fields]
