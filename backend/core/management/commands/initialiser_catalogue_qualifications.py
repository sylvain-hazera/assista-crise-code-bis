"""Pré-remplit le catalogue des titres, avec leur régime de conservation déjà réglé.

Constaté en production le 13/11/2026 : le catalogue était **vide**. La liste « Type de
document » de la page de dépôt ne proposait donc rien, et personne ne pouvait déposer quoi que
ce soit — un écran parfaitement fonctionnel, et parfaitement inutilisable.

Le catalogue est partagé par toutes les institutions (voir `Qualification`) et reste
librement extensible : ce qui est posé ici est un socle, pas une liste fermée. Une association
qui a ses propres titres les ajoute, et ceux-là arrivent sur la catégorie prudente par défaut.

**Les catégories sont posées ici, et c'est le point important.** Sans elles, tout le catalogue
resterait sur le défaut `SECOURISME` (régime « conserver »), et une photo de permis ne serait
jamais détruite — la politique de conservation s'afficherait sans jamais s'appliquer. Voir
`core/conservation_pieces.py`.

**Idempotent** : `get_or_create` sur le nom, et la catégorie n'est écrite que si elle est
restée au défaut. Une institution qui a délibérément reclassé un titre garde son choix — on
ne revient pas sur une décision humaine à chaque démarrage du conteneur.

`validite_mois` ne sert qu'à PRÉ-REMPLIR l'échéance à la saisie : c'est la date portée par
l'attestation réelle qui fait foi, jamais notre calcul. Les durées ci-dessous sont les usages
courants, pas une norme.
"""
from django.core.management.base import BaseCommand

from core.conservation_pieces import CLE_PAR_DEFAUT
from core.models import Qualification

#: (nom, catégorie de conservation, durée de validité habituelle en mois ou None)
CATALOGUE = [
    # ── Secourisme : le cœur du métier d'une AASC ─────────────────────────────────────
    ("PSC1 — Prévention et secours civiques niveau 1", "SECOURISME", None),
    ("PSE1 — Premiers secours en équipe niveau 1", "SECOURISME", 12),
    ("PSE2 — Premiers secours en équipe niveau 2", "SECOURISME", 12),
    ("BNSSA — Sauvetage aquatique", "SECOURISME", 60),
    ("Attestation de formation continue", "FORMATION_CONTINUE", 12),

    # ── Encadrement et formation ───────────────────────────────────────────────────────
    ("PAE FPS — Formateur premiers secours", "FORMATEUR", None),
    ("PAE FPSC — Formateur prévention et secours civiques", "FORMATEUR", None),

    # ── Conduite et habilitations ──────────────────────────────────────────────────────
    ("Permis de conduire B", "PERMIS", None),
    ("Permis de conduire C — poids lourd", "PERMIS", None),
    ("Permis de conduire D — transport en commun", "PERMIS", None),
    ("CACES — conduite d'engins", "HABILITATION", 60),
    ("Permis bateau", "HABILITATION", None),
    ("CRR — Certificat restreint de radiotéléphoniste", "HABILITATION", None),

    # ── Pièces de la personne ──────────────────────────────────────────────────────────
    ("Pièce d'identité", "IDENTITE", None),
    ("Titre de séjour", "TITRE_SEJOUR", None),
    ("Justificatif de domicile", "DOMICILE", None),
    ("Certificat médical d'aptitude", "MEDICAL", 12),
    ("Attestation d'assurance personnelle", "ASSURANCE_PERSONNELLE", 12),
    ("Autorisation parentale (bénévole mineur)", "AUTORISATION_PARENTALE", None),
    ("Photo d'identité", "PHOTO", None),
    ("RIB", "RIB", None),
]


class Command(BaseCommand):
    help = ("Crée les titres du socle commun et pose leur régime de conservation. "
            "Idempotent : ne touche pas à une catégorie déjà choisie à la main.")

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--silencieux", action="store_true",
            help="N'affiche que le bilan. Utilisé au démarrage du conteneur.",
        )

    def handle(self, *args, **options):
        crees = reclasses = 0
        for nom, categorie, validite in CATALOGUE:
            titre, cree = Qualification.objects.get_or_create(
                nom=nom, defaults={"categorie_piece": categorie,
                                   "validite_mois": validite},
            )
            if cree:
                crees += 1
                if not options["silencieux"]:
                    self.stdout.write(f"  + {nom} ({categorie})")
                continue
            # Entrée déjà là : on ne pose la catégorie que si personne ne l'a choisie. Écraser
            # un reclassement fait à la main reviendrait à défaire une décision humaine à
            # chaque redémarrage.
            if titre.categorie_piece in ("", CLE_PAR_DEFAUT) and categorie != CLE_PAR_DEFAUT:
                titre.categorie_piece = categorie
                if titre.validite_mois is None and validite is not None:
                    titre.validite_mois = validite
                titre.save(update_fields=["categorie_piece", "validite_mois"])
                reclasses += 1
                if not options["silencieux"]:
                    self.stdout.write(f"  ~ {nom} → {categorie}")

        self.stdout.write(self.style.SUCCESS(
            f"Catalogue des titres : {crees} créé(s), {reclasses} reclassé(s), "
            f"{Qualification.objects.count()} au total."
        ))
