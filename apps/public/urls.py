"""Public pages. ORDER MATTERS: the /<slug> catch-all is the very last pattern of the site."""

from django.urls import path

from . import views

app_name = "public"

urlpatterns = [
    path("", views.home, name="home"),
    path("villes/<slug:city>", views.city, name="city"),
    path("villes/<slug:city>/", views.city_trailing_slash, name="city_slash"),
    path("<slug:slug>/contact.vcf", views.vcard, name="vcard"),
    path("<slug:slug>/qr.svg", views.qr_svg, name="qr_svg"),
    path("<slug:slug>/qr.png", views.qr_png, name="qr_png"),
    path("<slug:slug>/og.png", views.og_image, name="og_image"),
    path("<slug:trade_plural>/<slug:city>", views.directory, name="directory"),
    path("<slug:trade_plural>/<slug:city>/", views.directory_trailing_slash, name="directory_slash"),
    path("<slug:slug>/", views.profile_trailing_slash, name="profile_slash"),
    path("<slug:slug>", views.profile, name="profile"),
]
