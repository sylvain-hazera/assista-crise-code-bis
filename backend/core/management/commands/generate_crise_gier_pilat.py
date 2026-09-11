"""Génère la crise démo "Inondation — vallée du Gier et Pilat" (Loire) avec des offres,
demandes, signalements et déclarations de sécurité réalistes, géolocalisés sur de vraies
adresses BAN (voir data/gier_pilat_addresses.json, récupéré par reverse-géocodage autour du
centre de chaque commune — voir la conversation qui a produit ce fichier). Suit le même
patron que generate_benevoles_pompiers.py (Faker fr_FR, bulk_create, environnement DEMO).

Contrairement à generate_benevoles_pompiers (une seule table, aucune relation), cette
commande construit un scénario complet et cohérent : une crise, des points opérationnels
réels (cellule de crise, regroupement des moyens, centres d'accueil), une institution et des
équipes rattachées à la crise (pour que le matching "équipes Hébergement" existant
fonctionne réellement, voir _notify_equipes_hebergement dans views.py), puis les offres/
demandes/signalements/déclarations de sécurité eux-mêmes.

Usage :
  python manage.py generate_crise_gier_pilat --total 600
  python manage.py generate_crise_gier_pilat --total 20      # lot de test
  python manage.py generate_crise_gier_pilat --delete        # supprime tout et recommence à zéro
"""
import json
import random
import secrets
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, MultiPoint, MultiPolygon, Point
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import (
    Besoin,
    Competence,
    Creneau,
    Crisis,
    DeclarationSecurite,
    DisponibiliteOffre,
    Environment,
    Information,
    InformationType,
    Institution,
    InstitutionType,
    Offer,
    OfferType,
    PointOperationnel,
    PointType,
    RegistrePresence,
    Request,
    RequestType,
    SituationDeclarant,
    Team,
    TypeCrise,
    TypeDeclarant,
    TypePersonneAccueillie,
)

ADDRESSES_FILE = Path(__file__).resolve().parent / "data" / "gier_pilat_addresses.json"
CRISIS_NAME = "Inondation — vallée du Gier et Pilat"
INSTITUTION_NOM = "Mairie de Saint-Chamond"

EQUIPE_HEBERGEMENT = "Équipe hébergement — Gier/Pilat"
EQUIPE_LOGISTIQUE = "Équipe logistique/nettoyage — Gier/Pilat"
EQUIPE_TRANSPORT = "Équipe transport/évacuation — Gier/Pilat"
EQUIPES_NOMS = [EQUIPE_HEBERGEMENT, EQUIPE_LOGISTIQUE, EQUIPE_TRANSPORT]

CENTRE_CRISE_NOM = "Cellule de crise — Mairie de Saint-Chamond"
CENTRE_REGROUPEMENT_NOM = "Centre de regroupement des moyens — Gier/Pilat"
CENTRES_ACCUEIL_NOMS = [
    ("Centre d'accueil — Salle des fêtes de Saint-Chamond", 120),
    ("Centre d'accueil — Gymnase de Rive-de-Gier", 80),
    ("Centre d'accueil — Salle polyvalente de Pélussin", 40),
]

# ── Offres d'aide ──────────────────────────────────────────────────────────
OFFER_KINDS = [
    # (offer_type, poids, générateur de titre)
    ("Bénévolat", 32, [
        "Disponible pour aider au nettoyage",
        "Bénévole polyvalent, dispo plusieurs jours",
        "Aide à l'évacuation et au portage",
        "Bénévole — soutien logistique",
        "Ancien secouriste, disponible en renfort",
        "Étudiant disponible pour donner un coup de main",
        "Retraité, disponible en journée",
    ]),
    ("Hébergement", 16, [
        "Chambre disponible pour famille sinistrée",
        "Studio indépendant à prêter",
        "Maison avec jardin, peut accueillir une famille",
        "Appartement disponible quelques semaines",
        "Chambre chez l'habitant",
    ]),
    ("Matériel", 16, [
        "Groupe électrogène à prêter",
        "Pompe à eau disponible",
        "Remorque pour transport de matériel",
        "Nettoyeur haute pression à disposition",
        "Déshumidificateur professionnel",
        "Cuve mobile d'eau potable",
    ]),
    ("Transport", 12, [
        "Camionnette disponible pour transport",
        "Véhicule 7 places pour évacuation",
        "Remorque + attelage disponibles",
        "Minibus disponible pour navettes",
    ]),
    ("Nourriture et eau", 12, [
        "Bouteilles d'eau et conserves disponibles",
        "Repas chauds à distribuer",
        "Stock de nourriture non périssable",
        "Eau potable en bonbonnes",
    ]),
    ("Soutien psychologique", 6, [
        "Psychologue bénévole disponible",
        "Écoute et soutien pour sinistrés",
    ]),
    ("Autre", 6, [
        "Vêtements secs à donner",
        "Couvertures et duvets disponibles",
        "Aide administrative pour les démarches",
    ]),
]

REQUEST_KINDS = [
    ("Nettoyage / déblaiement", 22, [
        "Cave inondée, besoin d'aide pour le nettoyage",
        "Rez-de-chaussée envahi de boue, aide au déblaiement",
        "Garage inondé, matériel à évacuer",
        "Besoin de bras pour vider la maison inondée",
    ]),
    ("Hébergement", 16, [
        "Famille évacuée cherchant un hébergement temporaire",
        "Maison inhabitable, besoin d'un logement d'urgence",
        "Recherche hébergement le temps des travaux",
    ]),
    ("Transport", 12, [
        "Véhicule bloqué, besoin d'un transport",
        "Besoin d'aide pour évacuer des affaires",
        "Personne âgée à évacuer, pas de moyen de transport",
    ]),
    ("Pompage", 10, [
        "Cave inondée, besoin d'une pompe",
        "Sous-sol rempli d'eau, pompage urgent",
    ]),
    ("Nourriture et eau", 10, [
        "Plus d'accès à l'eau potable",
        "Besoin de nourriture, magasins inaccessibles",
    ]),
    ("Soutien psychologique", 6, [
        "Famille choquée, besoin de soutien",
        "Personne isolée, besoin d'être accompagnée",
    ]),
    ("Assistance à évacuation", 8, [
        "Personne à mobilité réduite à évacuer",
        "Famille avec enfants en bas âge à évacuer",
    ]),
    ("Accompagnement administratif", 6, [
        "Besoin d'aide pour les démarches d'assurance",
        "Aide pour la déclaration de sinistre",
    ]),
    ("Matériel", 6, [
        "Besoin d'un groupe électrogène",
        "Besoin de bâches pour protéger la toiture",
    ]),
    ("Groupe électrogène", 4, [
        "Coupure de courant, besoin d'un groupe électrogène",
    ]),
]

INFORMATION_KINDS = [
    ("Route barrée", 30, [
        "Route submergée, circulation impossible",
        "Pont fermé suite à la montée des eaux",
        "Chaussée effondrée après le passage de la crue",
        "Route coupée par un éboulement de berge",
    ]),
    ("Danger imminent", 20, [
        "Mur de soutènement fissuré, risque d'effondrement",
        "Niveau du Gier toujours en hausse",
        "Câble électrique tombé dans l'eau",
        "Talus instable au-dessus de la route",
    ]),
    ("Arbre sur la chaussée", 15, [
        "Arbre tombé bloquant la route",
        "Grosse branche sur la voie après les intempéries",
    ]),
    ("Information utile", 20, [
        "Point de distribution d'eau potable ouvert",
        "La boulangerie du centre reste ouverte",
        "Numéro d'urgence de la mairie communiqué en porte-à-porte",
        "Collecte de vêtements organisée à la salle des fêtes",
    ]),
    ("Autre", 15, [
        "Coupure d'électricité sur plusieurs rues",
        "Réseau téléphonique instable dans le secteur",
    ]),
]

FIRST_NAMES_ENFANT_AGE = list(range(1, 16))


def weighted_choice(items):
    """items = [(valeur, poids, ...), ...] -> une valeur tirée au sort selon le poids."""
    total = sum(w for _, w, *_ in items)
    r = random.uniform(0, total)
    upto = 0
    for entry in items:
        val, w = entry[0], entry[1]
        upto += w
        if upto >= r:
            return entry
    return items[-1]


class Command(BaseCommand):
    help = (
        "Génère la crise démo 'Inondation — vallée du Gier et Pilat' avec des offres/"
        "demandes/signalements/déclarations de sécurité réalistes, géolocalisés sur de "
        "vraies adresses BAN. --delete supprime tout ce que cette commande a créé."
    )

    def add_arguments(self, parser):
        parser.add_argument("--total", type=int, default=600, help="Nombre total de points à générer (défaut 600).")
        parser.add_argument("--seed", type=int, default=91142026)
        parser.add_argument("--delete", action="store_true", help="Supprime la crise et toutes ses données au lieu d'en générer.")

    def handle(self, *args, **options):
        if options["delete"]:
            self._delete()
            return

        if Crisis.objects.filter(name=CRISIS_NAME, environment=Environment.DEMO).exists():
            raise CommandError(
                f"La crise « {CRISIS_NAME} » existe déjà en DEMO — lancez d'abord "
                f"--delete si vous voulez la régénérer."
            )

        random.seed(options["seed"])
        try:
            from faker import Faker
        except ImportError:
            raise CommandError("faker n'est pas installé.")
        self.fake = Faker("fr_FR")
        Faker.seed(options["seed"])

        with open(ADDRESSES_FILE, encoding="utf-8") as f:
            self.addresses_data = json.load(f)

        self.zone_addresses = []
        for citycode, info in self.addresses_data["zone"].items():
            for a in info["adresses"]:
                self.zone_addresses.append(a)
        self.hors_zone_addresses = []
        for citycode, info in self.addresses_data["hors_zone"].items():
            for a in info["adresses"]:
                self.hors_zone_addresses.append(a)

        if not self.zone_addresses:
            raise CommandError("Aucune adresse dans la zone — fichier d'adresses vide ou introuvable.")

        total = options["total"]
        self.stdout.write(f"Génération de la crise « {CRISIS_NAME} » (~{total} points, DEMO)...")

        crisis = self._creer_crisis()
        self.stdout.write(f"  Crise créée : {crisis.id}")

        points = self._creer_points(crisis)
        self.stdout.write(f"  {len(points)} points opérationnels créés (cellule de crise, regroupement, {len(CENTRES_ACCUEIL_NOMS)} centres d'accueil).")

        equipes = self._creer_equipes(crisis, points)
        self.stdout.write(f"  {len(equipes)} équipes créées et rattachées à la crise.")

        # Répartition du volume total entre les 4 familles de contenu.
        n_offers = round(total * 0.33)
        n_requests = round(total * 0.33)
        n_informations = round(total * 0.15)
        n_declarations = max(total - n_offers - n_requests - n_informations, 10)

        n_offers_created = self._creer_offers(crisis, n_offers)
        self.stdout.write(f"  {n_offers_created} offres d'aide créées.")

        n_requests_created = self._creer_requests(crisis, n_requests)
        self.stdout.write(f"  {n_requests_created} demandes d'aide créées.")

        n_info_created = self._creer_informations(crisis, n_informations)
        self.stdout.write(f"  {n_info_created} signalements créés.")

        centres_accueil = [p for p in points if p.type.code == "HEBERGEMENT"]
        n_decl_created = self._creer_declarations_securite(crisis, centres_accueil, n_declarations)
        self.stdout.write(f"  {n_decl_created} déclarations de sécurité créées.")

        grand_total = n_offers_created + n_requests_created + n_info_created + n_decl_created
        self.stdout.write(self.style.SUCCESS(
            f"Terminé : {grand_total} points générés pour « {CRISIS_NAME} » (crise {crisis.id})."
        ))

    # ── Suppression ──────────────────────────────────────────────────────
    def _delete(self):
        crisis = Crisis.objects.filter(name=CRISIS_NAME, environment=Environment.DEMO).first()
        if not crisis:
            self.stdout.write("Rien à supprimer (crise introuvable).")
        else:
            # Les compteurs de .delete() incluent les lignes cascadées (M2M through,
            # DisponibiliteOffre, photos...) — pas comparables aux "N créés" affichés à la
            # génération, on ne les affiche donc pas ligne à ligne pour éviter de laisser
            # croire à un écart. Le compte réel de crise/équipes/institution supprimées, lui,
            # est fiable (un seul niveau, pas de cascade).
            n_declarations = DeclarationSecurite.objects.filter(crise=crisis).count()
            n_offers = Offer.objects.filter(crisis=crisis).count()
            n_requests = Request.objects.filter(crisis=crisis).count()
            n_informations = Information.objects.filter(crisis=crisis).count()
            n_points = PointOperationnel.objects.filter(crise=crisis).count()

            registre_ids = list(
                DeclarationSecurite.objects.filter(crise=crisis, registre_presence__isnull=False)
                .values_list("registre_presence_id", flat=True)
            )
            DeclarationSecurite.objects.filter(crise=crisis).delete()
            RegistrePresence.objects.filter(id__in=registre_ids).delete()
            Offer.objects.filter(crisis=crisis).delete()
            Request.objects.filter(crisis=crisis).delete()
            Information.objects.filter(crisis=crisis).delete()
            PointOperationnel.objects.filter(crise=crisis).delete()
            crisis_id = crisis.id
            crisis.delete()
            self.stdout.write(
                f"Crise {crisis_id} supprimée ({n_declarations} déclarations, {n_offers} offres, "
                f"{n_requests} demandes, {n_informations} signalements, {n_points} points)."
            )

        n_equipes = Team.objects.filter(name__in=EQUIPES_NOMS).count()
        Team.objects.filter(name__in=EQUIPES_NOMS).delete()
        n_inst = Institution.objects.filter(nom=INSTITUTION_NOM, teams__isnull=True).count()
        Institution.objects.filter(nom=INSTITUTION_NOM, teams__isnull=True).delete()
        self.stdout.write(self.style.SUCCESS(f"Nettoyage terminé ({n_equipes} équipes, {n_inst} institution)."))

    # ── Crise, points, équipes ──────────────────────────────────────────
    def _creer_crisis(self) -> Crisis:
        lons = [a["lon"] for a in self.zone_addresses]
        lats = [a["lat"] for a in self.zone_addresses]
        centre_lon = sum(lons) / len(lons)
        centre_lat = sum(lats) / len(lats)

        # zone/zone_secteurs approximés par l'enveloppe convexe des adresses de la zone,
        # bufferisée d'un peu (~1.5km en degrés) — le frontend calcule normalement ceci à
        # partir des contours officiels des communes, non reproduit ici pour rester simple ;
        # suffisant pour que la crise ait une emprise géographique cohérente à l'affichage.
        multipoint = MultiPoint([Point(a["lon"], a["lat"], srid=4326) for a in self.zone_addresses], srid=4326)
        hull = multipoint.convex_hull
        zone_poly = hull.buffer(0.015)
        if zone_poly.geom_type == "Polygon":
            zone_secteurs = MultiPolygon(zone_poly, srid=4326)
        else:
            zone_secteurs = zone_poly
        zone_secteurs.srid = 4326

        communes = list(self.addresses_data["zone"].keys())

        crisis = Crisis.objects.create(
            name=CRISIS_NAME,
            type=TypeCrise.INONDATION,
            description=(
                "Crues du Gier après plusieurs jours de pluies intenses sur le bassin versant "
                "et le massif du Pilat — inondations dans les communes riveraines, routes "
                "coupées, caves et rez-de-chaussée envahis, plusieurs familles évacuées vers "
                "les centres d'accueil ouverts par les mairies concernées."
            ),
            location=Point(centre_lon, centre_lat, srid=4326),
            radius=15,
            zone=zone_poly if zone_poly.geom_type == "Polygon" else zone_poly[0],
            zone_communes=communes,
            zone_departements=["42"],
            zone_secteurs=zone_secteurs,
            environment=Environment.DEMO,
        )
        # start_date est auto_now_add : on recule la date après coup pour un scénario réaliste
        # (crise déclarée il y a 3 jours, pas à l'instant).
        Crisis.objects.filter(pk=crisis.pk).update(start_date=timezone.now() - timezone.timedelta(days=3, hours=6))
        crisis.refresh_from_db()
        return crisis

    def _pick_zone_address(self, citycode_filter=None):
        if citycode_filter:
            candidats = [a for a in self.zone_addresses if a["citycode"] == citycode_filter]
            if candidats:
                return random.choice(candidats)
        return random.choice(self.zone_addresses)

    def _creer_points(self, crisis: Crisis) -> list:
        type_cellule = PointType.objects.get(code="CELLULE_CRISE")
        type_regroupement = PointType.objects.get(code="REGROUPEMENT_MOYENS")
        type_hebergement = PointType.objects.get(code="HEBERGEMENT")

        points = []

        addr = self._pick_zone_address("42207")  # Saint-Chamond
        points.append(PointOperationnel.objects.create(
            nom=CENTRE_CRISE_NOM, type=type_cellule, crise=crisis,
            adresse=addr["label"], location=Point(addr["lon"], addr["lat"], srid=4326),
            actif=True, environment=Environment.DEMO,
        ))

        addr = self._pick_zone_address("42186")  # Rive-de-Gier
        points.append(PointOperationnel.objects.create(
            nom=CENTRE_REGROUPEMENT_NOM, type=type_regroupement, crise=crisis,
            adresse=addr["label"], location=Point(addr["lon"], addr["lat"], srid=4326),
            actif=True, environment=Environment.DEMO,
        ))

        centre_citycodes = ["42207", "42186", "42168"]  # Saint-Chamond, Rive-de-Gier, Pélussin
        for (nom, capacite), citycode in zip(CENTRES_ACCUEIL_NOMS, centre_citycodes):
            addr = self._pick_zone_address(citycode)
            points.append(PointOperationnel.objects.create(
                nom=nom, type=type_hebergement, crise=crisis,
                adresse=addr["label"], location=Point(addr["lon"], addr["lat"], srid=4326),
                capacite_accueil=capacite, actif=True, environment=Environment.DEMO,
            ))

        return points

    def _creer_equipes(self, crisis: Crisis, points: list) -> list:
        type_mairie = InstitutionType.objects.get(code="mairie")
        institution, _ = Institution.objects.get_or_create(
            nom=INSTITUTION_NOM,
            defaults={"type": type_mairie, "commune_code": "42207", "commune_nom": "Saint-Chamond"},
        )

        besoin_hebergement = Besoin.objects.filter(nom="Hébergement").first()
        besoin_nettoyage = Besoin.objects.filter(nom="Nettoyage - déblaiement").first()
        besoin_transport = Besoin.objects.filter(nom="Transport").first()

        comp_accueil = Competence.objects.filter(nom="Organisation de l'accueil / hébergement").first()
        comp_nettoyage = Competence.objects.filter(nom="Nettoyage et déblaiement").first()
        comp_transport = Competence.objects.filter(nom="Transport").first()
        comp_logistique = Competence.objects.filter(nom="Logistique").first()
        comp_secourisme = Competence.objects.filter(nom="Secourisme").first()

        equipes_config = [
            (EQUIPE_HEBERGEMENT, [besoin_hebergement], [comp_accueil, comp_logistique]),
            (EQUIPE_LOGISTIQUE, [besoin_nettoyage], [comp_nettoyage, comp_logistique]),
            (EQUIPE_TRANSPORT, [besoin_transport], [comp_transport, comp_secourisme]),
        ]

        equipes = []
        for nom, themes, competences in equipes_config:
            equipe = Team.objects.create(
                name=nom, institution=institution, environment=Environment.DEMO,
                color=random.choice(["#3b82f6", "#16a34a", "#dc2626", "#f59e0b"]),
            )
            equipe.themes.set([t for t in themes if t])
            equipe.competences.set([c for c in competences if c])
            equipe.assigned_crises.add(crisis)
            equipes.append(equipe)

        # L'équipe hébergement gère les centres d'accueil, l'équipe logistique tient le
        # regroupement des moyens — cohérent avec les thèmes ci-dessus.
        equipe_hebergement = equipes[0]
        equipe_logistique = equipes[1]
        for p in points:
            if p.type.code == "HEBERGEMENT":
                p.equipe = equipe_hebergement
                p.save(update_fields=["equipe"])
            elif p.type.code == "REGROUPEMENT_MOYENS":
                p.equipe = equipe_logistique
                p.save(update_fields=["equipe"])

        return equipes

    # ── Offres ────────────────────────────────────────────────────────────
    def _creer_offers(self, crisis: Crisis, n: int) -> int:
        offer_types = {t.type: t for t in OfferType.objects.filter(type__in=[k[0] for k in OFFER_KINDS])}
        today = timezone.now().date()

        offers = []
        offer_kind_by_index = []
        for _ in range(n):
            kind_type, _, titres = weighted_choice(OFFER_KINDS)
            offer_type = offer_types.get(kind_type)
            if offer_type is None:
                continue
            # ~12% des offres sont situées à quelques km hors zone (aide venant de l'extérieur).
            hors_zone = random.random() < 0.12 and self.hors_zone_addresses
            addr = random.choice(self.hors_zone_addresses) if hors_zone else random.choice(self.zone_addresses)

            offer = Offer(
                title=random.choice(titres),
                description=self.fake.sentence(nb_words=random.randint(10, 22)),
                location=Point(addr["lon"], addr["lat"], srid=4326),
                commune_code=addr["citycode"],
                departement_code=addr["citycode"][:2],
                region_code="84",  # Auvergne-Rhône-Alpes — couvre les 42/69/38 de la zone et hors-zone.
                first_name_offer=self.fake.first_name(),
                last_name_offer=self.fake.last_name(),
                email_offer=self.fake.unique.email(),
                phone_offer=self.fake.phone_number(),
                offer_type=offer_type,
                crisis=crisis,
                environment=Environment.DEMO,
                deletion_token=secrets.token_urlsafe(32),
                reponse_token=secrets.token_urlsafe(32),
                presence_physique=kind_type in ("Bénévolat", "Transport"),
            )

            if kind_type == "Hébergement":
                offer.hebergement_duree = random.choice(["TEMPORAIRE", "TEMPORAIRE", "LONGUE_DUREE"])
                offer.type_loyer = "GRATUIT"
                offer.type_logement = random.choice(["MAISON", "APPARTEMENT", "STUDIO", "CHAMBRE"])
                offer.niveau_logement = random.choice(["PLAIN_PIED", "ETAGE"])
                if offer.niveau_logement == "ETAGE":
                    offer.acces_etage = random.choice(["ESCALIER", "ASCENSEUR"])
                offer.nombre_pieces = random.randint(1, 5)
                offer.nombre_chambres = max(1, offer.nombre_pieces - random.randint(1, 2))
                offer.capacite_adultes = random.randint(1, 4)
                offer.capacite_enfants = random.randint(0, 3)
                offer.animaux_acceptes = random.random() < 0.3
                offer.jardin = random.random() < 0.4
                offer.pmr_compatible = random.random() < 0.15
            elif kind_type == "Matériel":
                offer.materiel_type = random.choice(["POMPE", "CUVE", "REMORQUE", None])
                offer.quantite = random.randint(1, 5)
                offer.unite = random.choice(["unité(s)", "pièce(s)"])
                offer.materiel_livraison = random.choice(["LIVRAISON", "DEPOT_CENTRE"])
            elif kind_type == "Transport":
                offer.transport_type = "PERSONNES"
                offer.nombre_places_assises = random.randint(2, 8)
                offer.confirmation_reglementaire = True
            elif kind_type == "Bénévolat":
                offer.diplome_secourisme = random.random() < 0.25
                offer.ancien_sapeur_pompier = random.random() < 0.08

            offers.append(offer)
            offer_kind_by_index.append(kind_type)

        created = Offer.objects.bulk_create(offers, batch_size=1000)

        # Compétences (Bénévolat uniquement, 1-3 par offre).
        competences_benevolat = list(Competence.objects.filter(
            nom__in=["Secourisme", "Logistique", "Nettoyage et déblaiement", "Évacuation", "Accueil", "Soutien psychologique"]
        ))
        competence_links = []
        for offre, kind_type in zip(created, offer_kind_by_index):
            if kind_type == "Bénévolat" and competences_benevolat:
                for comp in random.sample(competences_benevolat, k=min(random.randint(1, 3), len(competences_benevolat))):
                    competence_links.append(Offer.competences.through(offer_id=offre.id, competence_id=comp.id))
        if competence_links:
            Offer.competences.through.objects.bulk_create(competence_links, batch_size=2000, ignore_conflicts=True)

        # Disponibilités (Bénévolat uniquement) — créneaux sur les 21 prochains jours.
        dispo_links = []
        for offre, kind_type in zip(created, offer_kind_by_index):
            if kind_type != "Bénévolat":
                continue
            jours = random.sample(range(0, 21), k=random.randint(3, 8))
            for jour in jours:
                dispo_links.append(DisponibiliteOffre(
                    offer=offre,
                    date=today + timezone.timedelta(days=jour),
                    creneau=random.choice([Creneau.MATIN, Creneau.MIDI, Creneau.SOIR, Creneau.NUIT]),
                ))
        if dispo_links:
            DisponibiliteOffre.objects.bulk_create(dispo_links, batch_size=2000, ignore_conflicts=True)

        return len(created)

    # ── Demandes ─────────────────────────────────────────────────────────
    def _creer_requests(self, crisis: Crisis, n: int) -> int:
        request_types = {t.type: t for t in RequestType.objects.filter(type__in=[k[0] for k in REQUEST_KINDS])}

        requests_ = []
        for _ in range(n):
            kind_type, _, titres = weighted_choice(REQUEST_KINDS)
            request_type = request_types.get(kind_type)
            if request_type is None:
                continue
            addr = random.choice(self.zone_addresses)

            req = Request(
                title=random.choice(titres),
                description=self.fake.sentence(nb_words=random.randint(10, 20)),
                location=Point(addr["lon"], addr["lat"], srid=4326),
                commune_code=addr["citycode"],
                departement_code=addr["citycode"][:2],
                region_code="84",
                first_name_request=self.fake.first_name(),
                last_name_request=self.fake.last_name(),
                email_request=self.fake.unique.email(),
                phone_request=self.fake.phone_number(),
                request_type=request_type,
                crisis=crisis,
                environment=Environment.DEMO,
                deletion_token=secrets.token_urlsafe(32),
            )

            if kind_type == "Hébergement":
                req.hebergement_duree = "TEMPORAIRE"
                req.type_logement = random.choice(["APPARTEMENT", "MAISON", "STUDIO", None])
                req.capacite_adultes = random.randint(1, 4)
                req.capacite_enfants = random.randint(0, 3)
                req.zone_recherche_communes = [addr["citycode"]]
                req.zone_recherche_rayon_km = random.choice([5, 10, 15])
            elif kind_type == "Transport":
                req.nombre_places_assises = random.randint(1, 5)

            requests_.append(req)

        created = Request.objects.bulk_create(requests_, batch_size=1000)
        return len(created)

    # ── Signalements ─────────────────────────────────────────────────────
    def _creer_informations(self, crisis: Crisis, n: int) -> int:
        information_types = {t.type: t for t in InformationType.objects.filter(type__in=[k[0] for k in INFORMATION_KINDS])}

        informations = []
        for _ in range(n):
            kind_type, _, titres = weighted_choice(INFORMATION_KINDS)
            information_type = information_types.get(kind_type)
            if information_type is None:
                continue
            addr = random.choice(self.zone_addresses)

            informations.append(Information(
                title=random.choice(titres),
                first_name_information=self.fake.first_name(),
                last_name_information=self.fake.last_name(),
                email_information=self.fake.unique.email(),
                phone_information=self.fake.phone_number(),
                location=Point(addr["lon"], addr["lat"], srid=4326),
                commune_code=addr["citycode"],
                information_type=information_type,
                crisis=crisis,
                environment=Environment.DEMO,
                deletion_token=secrets.token_urlsafe(32),
            ))

        created = Information.objects.bulk_create(informations, batch_size=1000)
        return len(created)

    # ── Déclarations de sécurité ("je suis en sécurité") ───────────────────
    def _creer_declarations_securite(self, crisis: Crisis, centres_accueil: list, n: int) -> int:
        if not centres_accueil:
            return 0

        situations = [
            (SituationDeclarant.HORS_ZONE, 30),
            (SituationDeclarant.EN_CENTRE, 30),
            (SituationDeclarant.RELOGE, 25),
            (SituationDeclarant.BESOIN_CENTRE, 15),
        ]

        created = 0
        for _ in range(n):
            situation, _ = weighted_choice(situations)
            type_declarant = random.choice([
                TypeDeclarant.PERSONNE_SEULE, TypeDeclarant.PERSONNE_SEULE, TypeDeclarant.FAMILLE, TypeDeclarant.GROUPE,
            ])
            nombre_adultes = 1 if type_declarant == TypeDeclarant.PERSONNE_SEULE else random.randint(1, 2)
            nombre_enfants = 0 if type_declarant == TypeDeclarant.PERSONNE_SEULE else random.randint(0, 3)
            ages_enfants = random.sample(FIRST_NAMES_ENFANT_AGE, k=nombre_enfants) if nombre_enfants else []

            addr_pool = self.hors_zone_addresses if situation == SituationDeclarant.HORS_ZONE and self.hors_zone_addresses else self.zone_addresses
            addr = random.choice(addr_pool)

            declaration = DeclarationSecurite.objects.create(
                crise=crisis,
                type_declarant=type_declarant,
                situation=situation,
                nom_referent=self.fake.last_name(),
                prenom_referent=self.fake.first_name(),
                contact_referent=self.fake.phone_number(),
                nombre_adultes=nombre_adultes,
                nombre_enfants=nombre_enfants,
                ages_enfants=ages_enfants,
                location=Point(addr["lon"], addr["lat"], srid=4326) if situation != SituationDeclarant.BESOIN_CENTRE else None,
                commune_code=addr["citycode"] if situation != SituationDeclarant.BESOIN_CENTRE else None,
                departement_code=addr["citycode"][:2] if situation != SituationDeclarant.BESOIN_CENTRE else None,
                region_code="84" if situation != SituationDeclarant.BESOIN_CENTRE else None,
                regime_alimentaire_specifique=random.random() < 0.1,
                environment=Environment.DEMO,
            )

            if situation == SituationDeclarant.EN_CENTRE:
                centre = random.choice(centres_accueil)
                declaration.centre_accueil = centre
                declaration.save(update_fields=["centre_accueil"])
                registre = RegistrePresence.objects.create(
                    point=centre,
                    type_personne=TypePersonneAccueillie.EVACUE,
                    nom=f"{declaration.prenom_referent} {declaration.nom_referent}".strip(),
                    nombre=nombre_adultes + nombre_enfants,
                    environment=Environment.DEMO,
                )
                declaration.registre_presence = registre
                declaration.save(update_fields=["registre_presence"])

            created += 1

        return created
