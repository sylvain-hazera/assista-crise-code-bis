import concurrent.futures
import json
import random
import secrets
import urllib.parse
import urllib.request

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Commune, Competence, DisponibiliteOffre, Environment, Offer, OfferType

BAN_SEARCH_URL = "https://api-adresse.data.gouv.fr/search/"

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
        "Simule ~N anciens sapeurs-pompiers bénévoles répartis sur TOUTE LA FRANCE (Offer, "
        "type Bénévolat, environnement DEMO uniquement), pondéré par population des communes "
        "mais AMORTI (population**damping) pour sous-représenter les grandes villes. Chaque "
        "fiche est placée sur une VRAIE adresse (Base Adresse Nationale) plutôt qu'un point "
        "approximatif jitteré — jamais de coordonnée qui échouerait à se résoudre plus tard."
    )

    def add_arguments(self, parser):
        parser.add_argument("--total", type=int, default=10000)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--population-damping", type=float, default=0.3,
                             help="Poids = population**damping (0=uniforme, 1=proportionnel pur). "
                                  "0.3 par défaut : les grandes villes restent favorisées mais "
                                  "beaucoup moins que leur poids démographique réel.")
        parser.add_argument("--workers", type=int, default=15,
                             help="Requêtes parallèles vers l'API adresse (une par commune distincte).")

    def handle(self, *args, **options):
        total = options["total"]
        damping = options["population_damping"]
        random.seed(options["seed"])

        try:
            from faker import Faker
        except ImportError:
            raise CommandError("faker n'est pas installé.")
        fake = Faker("fr_FR")
        Faker.seed(options["seed"])

        if Commune.objects.filter(population__gt=0).count() < 30000:
            self.stdout.write("Import du référentiel national des communes (population/EPCI/département)...")
            call_command("import_communes", "all")

        communes = list(Commune.objects.filter(population__gt=0))
        self.stdout.write(f"{len(communes)} communes avec population connue.")
        if not communes:
            raise CommandError("Aucune commune avec population — import_communes a-t-il échoué ?")

        weights = [c.population ** damping for c in communes]
        chosen_communes = random.choices(communes, weights=weights, k=total)

        distinct = {c.code: c for c in chosen_communes}
        self.stdout.write(f"{len(distinct)} communes distinctes tirées sur {total} fiches — récupération d'adresses réelles (BAN)...")

        addresses_by_code = self._fetch_real_addresses(distinct, workers=options["workers"])

        offer_type, _ = OfferType.objects.get_or_create(type="Bénévolat")
        competences = [Competence.objects.get_or_create(nom=nom)[0] for nom in COMPETENCES_POMPIER]

        today = timezone.now().date()
        offers = []
        for commune in chosen_communes:
            lon, lat = random.choice(addresses_by_code.get(commune.code) or [(commune.centre_longitude, commune.centre_latitude)])
            if lat is None or lon is None:
                continue
            years = random.randint(3, 35)
            offers.append(Offer(
                title=random.choice(TITRES),
                description=random.choice(DESCRIPTIONS).format(years=years),
                location=f"POINT ({lon} {lat})",
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

        self.stdout.write(f"Création de {len(offers)} offres...")
        created = Offer.objects.bulk_create(offers, batch_size=1000)

        competence_links = []
        for offre in created:
            for comp in random.sample(competences, k=random.randint(2, 4)):
                competence_links.append(Offer.competences.through(offer_id=offre.id, competence_id=comp.id))
        Offer.competences.through.objects.bulk_create(competence_links, batch_size=2000, ignore_conflicts=True)

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

        self.stdout.write(self.style.SUCCESS(
            f"Terminé : {len(created)} bénévoles créés (DEMO), {len(competence_links)} compétences, "
            f"{len(dispo_links)} disponibilités, sur {len(distinct)} communes distinctes."
        ))

    def _fetch_real_addresses(self, communes_by_code, workers):
        """Une vraie adresse (Base Adresse Nationale) par commune distincte, en parallèle —
        essaie d'abord une recherche générique ('rue', qui matche quasi toujours au moins une
        voie), puis le nom de la commune elle-même (renvoie au moins son point officiel de
        type 'municipality'), et ne retombe sur le centroïde déjà en base que si les deux
        échouent (jamais observé en test, gardé par sécurité)."""
        results = {}

        def fetch_one(code_commune):
            code, commune = code_commune
            for query in ("rue", commune.nom or code):
                url = (
                    f"{BAN_SEARCH_URL}?q={urllib.parse.quote(query)}&citycode={code}&limit=10"
                )
                try:
                    with urllib.request.urlopen(url, timeout=5) as response:
                        data = json.loads(response.read().decode("utf-8"))
                except Exception:
                    continue
                points = [
                    (f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1])
                    for f in data.get("features", [])
                ]
                if points:
                    return code, points
            return code, []

        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch_one, item) for item in communes_by_code.items()]
            for future in concurrent.futures.as_completed(futures):
                code, points = future.result()
                results[code] = points
                done += 1
                if done % 200 == 0:
                    self.stdout.write(f"  ... {done}/{len(communes_by_code)} communes traitées")

        return results
