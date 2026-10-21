import datetime

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from core.models import AuditLog, Crisis, User
from core.tracabilite import champ_crise, est_compte_systeme


class Command(BaseCommand):
    help = (
        "Complète l'historique de la main courante avec ce que les lignes antérieures au "
        "21/10/2026 ne portaient pas (voir core/tracabilite.py) : marque « compte système » "
        "(case « Masquer les comptes système ») et rattachement à une crise ou au fonctionnement "
        "général (filtre Crise / fonctionnement général). Une ligne qui cite une fiche précise "
        "prend la crise de cette fiche ; une ligne sans fiche sur un type lié aux crises (lecture "
        "de liste surtout) reste « non déterminable » -- on ne sait pas ce qu'elle affichait. "
        "Par lots d'un jour et d'un environnement : chaque lot est une courte transaction, les "
        "écritures de l'application ne sont jamais bloquées longtemps. Idempotent : ne touche "
        "que les lignes encore incomplètes, peut être relancé ou interrompu sans risque."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Compte les lignes qui seraient complétées, sans rien modifier.",
        )

    def handle(self, *args, **options):
        simulation = options["dry_run"]
        table = AuditLog._meta.db_table

        comptes_systeme = [u.id for u in User.objects.only("id", "username") if est_compte_systeme(u)]
        modeles_crise = self._modeles_lies_aux_crises()
        noms_lies = [m.__name__ for m, _ in modeles_crise] + [Crisis.__name__]

        dates = AuditLog.objects.values_list("date_action", flat=True)
        premiere, derniere = dates.order_by("date_action").first(), dates.order_by("-date_action").first()
        if premiere is None:
            self.stdout.write("Main courante vide : rien à reprendre.")
            return

        totaux = {"compte_systeme": 0, "fiche": 0, "crise_explicite": 0, "general": 0}
        jour = timezone.localtime(premiere).date()
        dernier_jour = timezone.localtime(derniere).date()
        while jour <= dernier_jour:
            debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
            fin = debut + datetime.timedelta(days=1)
            for environnement in ("PROD", "DEMO"):
                # environment + date_action : servi par l'index auditlog_env_date_idx (0208).
                fenetre = "a.environment = %s AND a.date_action >= %s AND a.date_action < %s"
                bornes_sql = [environnement, debut, fin]
                with transaction.atomic():
                    with connection.cursor() as c:
                        totaux["compte_systeme"] += self._executer(
                            c, simulation, table, "compte_systeme = true", None,
                            f"{fenetre} AND NOT a.compte_systeme AND a.utilisateur_id = ANY(%s)",
                            bornes_sql + [comptes_systeme],
                        ) if comptes_systeme else 0

                        # Crise déjà renseignée par une vue (appels explicites d'audit_log) : elle
                        # prime sur celle qu'on déduirait de la fiche.
                        totaux["crise_explicite"] += self._executer(
                            c, simulation, table, "perimetre = 'CRISE'", None,
                            f"{fenetre} AND a.perimetre IS NULL AND a.crise_id IS NOT NULL", bornes_sql,
                        )

                        # Fiche précise -> crise de la fiche (ou fonctionnement général si elle
                        # n'en a pas).
                        totaux["fiche"] += self._executer(
                            c, simulation, table, "crise_id = a.objet_id, perimetre = 'CRISE'",
                            f"{Crisis._meta.db_table} o",
                            f"{fenetre} AND a.perimetre IS NULL AND a.objet_type = 'Crisis' AND a.objet_id = o.id",
                            bornes_sql,
                        )
                        for modele, champ in modeles_crise:
                            totaux["fiche"] += self._reprendre_modele(c, simulation, table, fenetre, bornes_sql, modele, champ)

                        # Type sans lien avec les crises (connexions, comptes, satellites, radio,
                        # institutions...) -> fonctionnement général.
                        totaux["general"] += self._executer(
                            c, simulation, table, "perimetre = 'GENERAL'", None,
                            f"{fenetre} AND a.perimetre IS NULL AND NOT (a.objet_type = ANY(%s))",
                            bornes_sql + [noms_lies],
                        )
            self.stdout.write(f"{jour:%d/%m/%Y} traité.")
            jour += datetime.timedelta(days=1)

        verbe = "seraient complétées" if simulation else "complétées"
        self.stdout.write(self.style.SUCCESS(
            f"Lignes {verbe} : {totaux['compte_systeme']} marquée(s) compte système, "
            f"{totaux['fiche']} rattachée(s) via leur fiche, {totaux['crise_explicite']} via leur "
            f"crise déjà notée, {totaux['general']} classée(s) fonctionnement général."
        ))
        restantes = AuditLog.objects.filter(perimetre__isnull=True).count()
        self.stdout.write(f"Lignes restées « non déterminable » : {restantes} (lectures de listes surtout).")

    def _modeles_lies_aux_crises(self):
        modeles = []
        for modele in apps.get_app_config("core").get_models():
            if modele in (Crisis, AuditLog):
                continue
            champ = champ_crise(modele)
            if champ:
                modeles.append((modele, modele._meta.get_field(champ)))
        return modeles

    def _reprendre_modele(self, c, simulation, table, fenetre, bornes_sql, modele, champ):
        nom, cible = modele.__name__, modele._meta.db_table
        if champ.many_to_one:
            colonne = champ.column
            return self._executer(
                c, simulation, table,
                f"crise_id = o.{colonne}, perimetre = CASE WHEN o.{colonne} IS NULL THEN 'GENERAL' ELSE 'CRISE' END",
                f"{cible} o",
                f"{fenetre} AND a.perimetre IS NULL AND a.objet_type = %s AND a.objet_id = o.id",
                bornes_sql + [nom],
            )
        # ManyToMany (Team.assigned_crises) : aucune crise -> général, une seule -> elle,
        # plusieurs -> MULTI.
        lien = champ.remote_field.through._meta.db_table
        source, cible_m2m = champ.m2m_column_name(), champ.m2m_reverse_name()
        return self._executer(
            c, simulation, table,
            "crise_id = CASE WHEN r.nb = 1 THEN r.unique_crise END, "
            "perimetre = CASE WHEN r.nb = 0 THEN 'GENERAL' WHEN r.nb = 1 THEN 'CRISE' ELSE 'MULTI' END",
            f"(SELECT o.id, COUNT(l.{cible_m2m}) AS nb, MIN(l.{cible_m2m}::text)::uuid AS unique_crise "
            f"FROM {cible} o LEFT JOIN {lien} l ON l.{source} = o.id GROUP BY o.id) r",
            f"{fenetre} AND a.perimetre IS NULL AND a.objet_type = %s AND a.objet_id = r.id",
            bornes_sql + [nom],
        )

    @staticmethod
    def _executer(c, simulation, table, affectations, jointure, condition, params):
        """UPDATE {table} a SET {affectations} [FROM {jointure}] WHERE {condition} ; en simulation,
        le même FROM/WHERE en simple comptage (rien n'est écrit, pas même annulé ensuite)."""
        if simulation:
            source = f"{table} a" + (f", {jointure}" if jointure else "")
            c.execute(f"SELECT COUNT(*) FROM {source} WHERE {condition}", params)
            return c.fetchone()[0]
        c.execute(
            f"UPDATE {table} a SET {affectations}" + (f" FROM {jointure}" if jointure else "")
            + f" WHERE {condition}", params,
        )
        return c.rowcount
