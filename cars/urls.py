from django.urls import path

from . import views

app_name = 'cars'

urlpatterns = [
    path('', views.home, name='home'),
    path('vehicles/', views.car_list, name='list'),
    path('new/', views.car_list, {'new': True}, name='new'),
    path('vehicle-collection/<slug:category_slug>/', views.car_list, name='category'),
    path('manufacturer/<slug:make_slug>/', views.car_list, name='make'),
    path('vehicle/<int:pk>/', views.car_detail, name='detail'),
    path('vehicle/<int:pk>/favorite/', views.toggle_favorite, name='favorite'),

    path('cabinet/', views.my_cars, name='my_cars'),
    path('cabinet/favorites/', views.favorites, name='favorites'),
    path('cabinet/add/', views.car_create, name='add'),
    path('cabinet/<int:pk>/edit/', views.car_edit, name='edit'),
    path('cabinet/<int:pk>/delete/', views.car_delete, name='delete'),
    path('cabinet/<int:pk>/activate/', views.car_activate, name='activate'),
    path('cabinet/<int:pk>/deactivate/', views.car_deactivate, name='deactivate'),
    path('cabinet/payment/success/', views.payment_success, name='payment_success'),
]
