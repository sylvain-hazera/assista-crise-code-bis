import random
import secrets

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Commune, Competence, DisponibiliteOffre, Offer, OfferType, Environment

COMPETENCES_POMPIER = [
    "secourisme",
    "Coordination de crise",
    "Encadrement d'équipe",
    "Sauvetage",
    "Évacuation",
    "Logistique",
    "Radio",
    "Extinction bénévole du feu",
    "Formation aux gestes de secours",
]

TITRES = [
    "Ancien sapeur-pompier disponible comme bénévole",
    "Ancien sapeur-pompier volontaire — dispositifs de crise",
    "Retraité SDIS, disponible en cas de crise",
]

DESCRIPTIONS = [
    "{years} ans de service chez les sapeurs-pompiers, disponible pour appuyer une équipe locale en cas de crise.",
    "Ancien sapeur-pompier volontaire ({years} ans d'expérience), prêt à intervenir en soutien logistique ou encadrement.",
    "Retraité des sapeurs-pompiers ({years} ans de carrière), toujours formé aux gestes de secours, disponible ponctuellement.",
]


class Command(BaseCommand):
    help = (
        "Simule des anciens sapeurs-pompiers bénévoles (Offer, type Bénévolat, environnement "
        "DEMO uniquement) répartis par commune au prorata de la population, pour charger la "
        "vue secteur (mairie/EPCI/département) et mesurer la pagination à volume réaliste. "
        "Nécessite le référentiel Commune importé au préalable (import_communes) — lancé "
        "automatiquement si absent pour le département demandé."
    )

    def add_arguments(self, parser):
        parser.add_argument("departements", nargs="+", help="Codes département (ex: 38 69 75).")
        parser.add_argument("--total", type=int, default=10000, help="Nombre de fiches par département (défaut 10000).")
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **options):
        deps = options["departements"]
        total_par_dep = options["total"]
        random.seed(options["seed"])

        try:
            from faker import Faker
        except ImportError:
            raise CommandError("faker n'est pas installé.")
        fake = Faker("fr_FR")
        Faker.seed(options["seed"])

        offer_type, _ = OfferType.objects.get_or_create(type="Bénévolat")
        competences = [
            Competence.objects.get_or_create(nom=nom)[0] for nom in COMPETENCES_POMPIER
        ]

        grand_total = 0
        for dep in deps:
            grand_total += self._generate_departement(dep, total_par_dep, fake, offer_type, competences)

        self.stdout.write(self.style.SUCCESS(f"Total : {grand_total} bénévoles créés (DEMO)."))

    def _generate_departement(self, dep, total, fake, offer_type, competences):
        communes = list(Commune.objects.filter(departement_code=dep, population__isnull=False))
        if not communes:
            self.stdout.write(f"  {dep}: référentiel commune absent, import en cours...")
            call_command("import_communes", dep)
            communes = list(Commune.objects.filter(departement_code=dep, population__isnull=False))
        if not communes:
            self.stdout.write(self.style.WARNING(f"  {dep}: aucune commune avec population, département ignoré."))
            return 0

        weights = [c.population for c in communes]
        chosen_communes = random.choices(communes, weights=weights, k=total)

        today = timezone.now().date()
        offers = []
        for commune in chosen_communes:
            years = random.randint(3, 35)
            jitter_lat = random.uniform(-0.01, 0.01)
            jitter_lon = random.uniform(-0.01, 0.01)
            lat = (commune.centre_latitude or 0) + jitter_lat
            lon = (commune.centre_longitude or 0) + jitter_lon
            offers.append(Offer(
                title=random.choice(TITRES),
                description=random.choice(DESCRIPTIONS).format(years=years),
                location=Point(lon, lat, srid=4326) if commune.centre_latitude else None,
                commune_code=commune.code,
                epci_code=commune.epci_code,
                departement_code=commune.departement_code,
                first_name_offer=fake.first_name(),
                last_name_offer=fake.last_name(),
                email_offer=fake.unique.email(),
                phone_offer=fake.phone_number(),
                offer_type=offer_type,
                environment=Environment.DEMO,
                deletion_token=secrets.token_urlsafe(32),
                reponse_token=secrets.token_urlsafe(32),
            ))

        created = Offer.objects.bulk_create(offers, batch_size=1000)
        self.stdout.write(f"  {dep}: {len(created)} offres créées, ajout compétences/disponibilités...")

        # Compétences (2-4 par personne) — through-table en masse plutôt que .set() par objet
        # (qui ferait 1 requête par offre, invivable à ce volume).
        competence_links = []
        for offre in created:
            for comp in random.sample(competences, k=random.randint(2, 4)):
                competence_links.append(Offer.competences.through(offer_id=offre.id, competence_id=comp.id))
        Offer.competences.through.objects.bulk_create(competence_links, batch_size=2000, ignore_conflicts=True)

        # Disponibilités (2-6 créneaux sur les 30 prochains jours, variés) — bulk_create aussi.
        dispo_links = []
        for offre in created:
            jours = random.sample(range(1, 31), k=random.randint(2, 6))
            for jour in jours:
                dispo_links.append(DisponibiliteOffre(
                    offer=offre,
                    date=today + timezone.timedelta(days=jour),
                    creneau=random.choice(["MATIN", "MIDI", "SOIR", "NUIT"]),
                ))
        DisponibiliteOffre.objects.bulk_create(dispo_links, batch_size=2000, ignore_conflicts=True)

        self.stdout.write(f"  {dep}: OK ({len(created)} offres, {len(competence_links)} compétences, {len(dispo_links)} disponibilités)")
        return len(created)
