from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("<slug:slug>", views.report, name="report"),
    path("<slug:slug>/merci", views.report_thanks, name="report_thanks"),
]
