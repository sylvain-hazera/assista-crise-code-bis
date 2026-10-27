from django.core.management.base import BaseCommand
from django.db.models.functions import Upper

from core.models import Institution, TYPES_COLLECTIVITE_TERRITORIALE


class Command(BaseCommand):
    help = (
        "Rattrapage pour les collectivités territoriales (mairie/EPCI/département/région) "
        "créées AVANT la mise en place de la Zone \"Mon territoire\" automatique "
        "(Institution.save(), voir core/models.py::_assurer_zone_mon_territoire) -- "
        "une institution créée après n'a pas besoin de ce rattrapage, le save() suffit. "
        "Ré-exécute simplement .save() sur chacune : idempotent, peut être relancé sans risque "
        "(get_or_create ne duplique jamais une zone déjà présente)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste les institutions concernées sans rien modifier.",
        )

    def handle(self, *args, **options):
        # Comparaison sur le code MIS EN MAJUSCULES, comme partout ailleurs
        # (Institution.save(), _institution_est_autorite_locale) : le catalogue des types
        # contient des doublons de casse — « MAIRIE » et « mairie » coexistent, 4 institutions
        # d'un côté et 5 de l'autre au 27/10/2026 — parce que
        # find_or_create_institution_from_annuaire crée son type en minuscules. Sans cette
        # normalisation, ce rattrapage sautait silencieusement cinq mairies sur neuf.
        qs = Institution.objects.annotate(
            code_type_majuscule=Upper("type__code"),
        ).filter(
            code_type_majuscule__in=TYPES_COLLECTIVITE_TERRITORIALE,
        ).exclude(commune_code__isnull=True).exclude(commune_code="")

        total = qs.count()
        if total == 0:
            self.stdout.write("Aucune collectivité territoriale avec commune connue trouvée.")
            return

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] {total} institution(s) seraient traitées :")
            for institution in qs.select_related("type"):
                self.stdout.write(f"  - {institution.nom} ({institution.type.code}, commune {institution.commune_code})")
            return

        traitees = 0
        erreurs = 0
        for institution in qs.select_related("type"):
            try:
                institution.save()
                traitees += 1
                zone = institution.zones.filter(nom="Mon territoire").first()
                nb_communes = len(zone.communes) if zone else 0
                self.stdout.write(f"  - {institution.nom} ({institution.type.code}) : {nb_communes} commune(s)")
            except Exception as exc:
                erreurs += 1
                self.stdout.write(self.style.ERROR(f"  - {institution.nom} : échec ({exc})"))

        self.stdout.write(self.style.SUCCESS(
            f"Terminé : {traitees}/{total} institution(s) traitée(s), {erreurs} erreur(s)."
        ))
