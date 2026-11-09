"""Initial reference data for Cameroon (loaded by migration core.0002_seed_cameroon)."""

COUNTRIES = [
    # code, name, prefix, currency, active
    ("CM", "Cameroun", "+237", "XAF", True),
    ("CI", "Côte d'Ivoire", "+225", "XOF", False),
    ("SN", "Sénégal", "+221", "XOF", False),
    ("GA", "Gabon", "+241", "XAF", False),
]

CITIES_CM = [
    # name, slug, region
    ("Douala", "douala", "Littoral"),
    ("Yaoundé", "yaounde", "Centre"),
    ("Bafoussam", "bafoussam", "Ouest"),
    ("Bamenda", "bamenda", "Nord-Ouest"),
    ("Garoua", "garoua", "Nord"),
    ("Maroua", "maroua", "Extrême-Nord"),
    ("Ngaoundéré", "ngaoundere", "Adamaoua"),
    ("Bertoua", "bertoua", "Est"),
    ("Buea", "buea", "Sud-Ouest"),
    ("Limbé", "limbe", "Sud-Ouest"),
    ("Kumba", "kumba", "Sud-Ouest"),
    ("Kribi", "kribi", "Sud"),
    ("Ebolowa", "ebolowa", "Sud"),
    ("Edéa", "edea", "Littoral"),
    ("Nkongsamba", "nkongsamba", "Littoral"),
    ("Dschang", "dschang", "Ouest"),
    ("Bafang", "bafang", "Ouest"),
    ("Foumban", "foumban", "Ouest"),
    ("Mbalmayo", "mbalmayo", "Centre"),
    ("Sangmélima", "sangmelima", "Sud"),
]

# name, feminine, english, slug, plural_slug, plural_name, segment, schema.org type
TRADES = [
    ("Plombier", "Plombière", "Plumber", "plombier", "plombiers", "Plombiers", "craft", "Plumber"),
    (
        "Électricien",
        "Électricienne",
        "Electrician",
        "electricien",
        "electriciens",
        "Électriciens",
        "craft",
        "Electrician",
    ),
    ("Maçon", "Maçonne", "Mason", "macon", "macons", "Maçons", "craft", "GeneralContractor"),
    ("Carreleur", "Carreleuse", "Tiler", "carreleur", "carreleurs", "Carreleurs", "craft", "GeneralContractor"),
    (
        "Menuisier",
        "Menuisière",
        "Carpenter",
        "menuisier",
        "menuisiers",
        "Menuisiers",
        "craft",
        "HomeAndConstructionBusiness",
    ),
    (
        "Peintre en bâtiment",
        "Peintre en bâtiment",
        "House painter",
        "peintre",
        "peintres",
        "Peintres en bâtiment",
        "craft",
        "HousePainter",
    ),
    ("Couvreur", "Couvreuse", "Roofer", "couvreur", "couvreurs", "Couvreurs", "craft", "RoofingContractor"),
    ("Serrurier", "Serrurière", "Locksmith", "serrurier", "serruriers", "Serruriers", "craft", "Locksmith"),
    ("Soudeur", "Soudeuse", "Welder", "soudeur", "soudeurs", "Soudeurs", "craft", "HomeAndConstructionBusiness"),
    (
        "Frigoriste",
        "Frigoriste",
        "Refrigeration technician",
        "frigoriste",
        "frigoristes",
        "Frigoristes",
        "craft",
        "HVACBusiness",
    ),
    (
        "Mécanicien auto",
        "Mécanicienne auto",
        "Car mechanic",
        "mecanicien",
        "mecaniciens",
        "Mécaniciens auto",
        "craft",
        "AutoRepair",
    ),
    (
        "Réparateur de téléphones",
        "Réparatrice de téléphones",
        "Phone repairer",
        "reparateur-telephone",
        "reparateurs-telephone",
        "Réparateurs de téléphones",
        "craft",
        "LocalBusiness",
    ),
    ("Couturier", "Couturière", "Tailor", "couturier", "couturiers", "Couturiers", "craft", "LocalBusiness"),
    ("Coiffeur", "Coiffeuse", "Hairdresser", "coiffeur", "coiffeurs", "Coiffeurs", "craft", "HairSalon"),
    (
        "Esthéticien",
        "Esthéticienne",
        "Beautician",
        "estheticien",
        "estheticiens",
        "Esthéticiens",
        "craft",
        "BeautySalon",
    ),
    (
        "Restaurateur",
        "Restauratrice",
        "Restaurant owner",
        "restaurateur",
        "restaurants",
        "Restaurants",
        "craft",
        "Restaurant",
    ),
    ("Traiteur", "Traiteuse", "Caterer", "traiteur", "traiteurs", "Traiteurs", "craft", "FoodEstablishment"),
    ("Boulanger", "Boulangère", "Baker", "boulanger", "boulangers", "Boulangers", "craft", "Bakery"),
    ("Commerçant", "Commerçante", "Shopkeeper", "commercant", "commerces", "Commerces", "craft", "Store"),
    (
        "Agent immobilier",
        "Agente immobilière",
        "Real estate agent",
        "agent-immobilier",
        "agents-immobiliers",
        "Agents immobiliers",
        "liberal",
        "RealEstateAgent",
    ),
    ("Photographe", "Photographe", "Photographer", "photographe", "photographes", "Photographes", "liberal", "Person"),
    (
        "Développeur web",
        "Développeuse web",
        "Web developer",
        "developpeur",
        "developpeurs",
        "Développeurs web",
        "liberal",
        "Person",
    ),
    ("Graphiste", "Graphiste", "Graphic designer", "graphiste", "graphistes", "Graphistes", "liberal", "Person"),
    (
        "Community manager",
        "Community manager",
        "Community manager",
        "community-manager",
        "community-managers",
        "Community managers",
        "liberal",
        "Person",
    ),
    ("Consultant", "Consultante", "Consultant", "consultant", "consultants", "Consultants", "liberal", "Person"),
    ("Comptable", "Comptable", "Accountant", "comptable", "comptables", "Comptables", "liberal", "AccountingService"),
    ("Avocat", "Avocate", "Lawyer", "avocat", "avocats", "Avocats", "liberal", "Attorney"),
    ("Architecte", "Architecte", "Architect", "architecte", "architectes", "Architectes", "liberal", "Person"),
    ("Traducteur", "Traductrice", "Translator", "traducteur", "traducteurs", "Traducteurs", "liberal", "Person"),
    ("Répétiteur", "Répétitrice", "Tutor", "repetiteur", "repetiteurs", "Répétiteurs", "liberal", "Person"),
    ("Médecin", "Médecin", "Doctor", "medecin", "medecins", "Médecins", "liberal", "Physician"),
    ("Dentiste", "Dentiste", "Dentist", "dentiste", "dentistes", "Dentistes", "liberal", "Dentist"),
]


def load(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    City = apps.get_model("core", "City")
    Trade = apps.get_model("core", "Trade")
    for code, name, prefix, currency, active in COUNTRIES:
        Country.objects.update_or_create(
            code=code, defaults={"name": name, "phone_prefix": prefix, "currency": currency, "is_active": active}
        )
    cm = Country.objects.get(code="CM")
    for name, slug, region in CITIES_CM:
        City.objects.update_or_create(country=cm, slug=slug, defaults={"name": name, "region": region})
    for name, fem, en, slug, plural_slug, plural_name, segment, schema_type in TRADES:
        Trade.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "name_feminine": fem,
                "name_en": en,
                "plural_slug": plural_slug,
                "plural_name": plural_name,
                "segment": segment,
                "schema_type": schema_type,
            },
        )


def unload(apps, schema_editor):
    pass
