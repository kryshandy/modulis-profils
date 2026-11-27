from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("webhook/<str:provider>", views.payment_webhook, name="webhook"),
]
