from django.urls import path

from . import views

app_name = 'users'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.EmailLoginView.as_view(), name='login'),
    path('logout/', views.logout, name='logout'),
    path('account/', views.account, name='account'),
]
