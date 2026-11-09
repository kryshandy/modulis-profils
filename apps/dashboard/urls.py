"""Espace pro at /espace/ — discreet entry linked from public pages."""

from django.urls import path

from .views import auth, editor, onboarding, pages

app_name = "dashboard"

urlpatterns = [
    # Auth (SMS code only)
    path("connexion", auth.login_view, name="login"),
    path("connexion/code", auth.verify_view, name="verify"),
    path("deconnexion", auth.logout_view, name="logout"),
    # Onboarding & walkthrough
    path("bienvenue/<slug:step>", onboarding.onboarding, name="onboarding"),
    path("visite-terminee", pages.tour_done, name="tour_done"),
    # Home
    path("", pages.home, name="home"),
    path("profil/changer", pages.switch_profile, name="switch_profile"),
    # Editor
    path("page/<slug:section>", editor.edit, name="edit"),
    path("page/prestations/ajouter", editor.service_add, name="service_add"),
    path("page/prestations/<int:pk>/modifier", editor.service_update, name="service_update"),
    path("page/prestations/<int:pk>/supprimer", editor.service_delete, name="service_delete"),
    path("page/prestations/<int:pk>/deplacer", editor.service_move, name="service_move"),
    path("page/galerie/ajouter", editor.media_add, name="media_add"),
    path("page/galerie/<int:pk>/legende", editor.media_update, name="media_update"),
    path("page/galerie/<int:pk>/supprimer", editor.media_delete, name="media_delete"),
    path("page/galerie/<int:pk>/deplacer", editor.media_move, name="media_move"),
    path("page/liens/ajouter", editor.link_add, name="link_add"),
    path("page/liens/<int:pk>/supprimer", editor.link_delete, name="link_delete"),
    path("page/liens/<int:pk>/deplacer", editor.link_move, name="link_move"),
    # Other screens
    path("partager", pages.share, name="share"),
    path("partager/affiche", pages.poster, name="poster"),
    path("cartes", pages.cards, name="cards"),
    path("cartes/lier", pages.card_link, name="card_link"),
    path("cartes/<int:pk>/perdue", pages.card_lost, name="card_lost"),
    path("statistiques", pages.stats, name="stats"),
    path("parametres", pages.settings_view, name="settings"),
    path("parametres/adresse-disponible", pages.slug_check, name="slug_check"),
    path("aide", pages.help_view, name="help"),
]
