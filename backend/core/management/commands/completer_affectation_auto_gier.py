"""Rend l'affectation automatique réellement opérante sur la crise démo du Gier, puis rattrape
le retard des demandes et signalements déjà en base.

Pourquoi cette commande existe (constat du 28/10/2026) : `generate_crise_gier_pilat` fabrique
une crise crédible, mais quatre maillons de la chaîne d'affectation automatique manquent, et un
seul suffit à la rendre muette.

1. `Team.competences` ne sert QU'À l'affichage de la fiche équipe. Seule une
   `AffectationCompetence(crise, competence, equipe)` est lue par
   `meilleure_equipe_pour_competence` — le générateur n'en crée aucune, donc aucune équipe n'est
   jamais candidate. `affecter_competences_aux_crises` (views.py, 24/10) fait exactement ce
   travail : on l'appelle ici plutôt que d'en réécrire une variante.
2. Les correspondances `Besoin -> Competence` manquent sur l'essentiel des thèmes de cette
   crise, et sur la TOTALITÉ des types de signalement : la migration 0174 a créé les cinq
   `Besoin` des signalements (« Route barrée », « Danger imminent »...) sans jamais les relier à
   une compétence. `resolve_competence_for_information` renvoyait donc None pour 100 % des
   signalements, et un dossier sans compétence ne peut pas trouver d'équipe.
3. Aucune `AffectationRoleOperationnel` REGULATEUR disponible : le dossier naissait en
   EN_ATTENTE_DISTRIBUTION (« personne ne surveille ce thème ») au lieu de
   EN_ATTENTE_AFFECTATION, et la file `/dossiers/ma_file/` restait vide pour tout le monde.
4. Les équipes n'ont aucune zone déclarée. `team_zone_specificity` les fait alors toutes
   retomber sur la zone de la crise, donc toutes à égalité de score 0 : dès que deux équipes
   partagent une compétence, l'égalité parfaite (zone ET charge) fait renvoyer None par
   décision explicite du 26/09 — ne jamais trancher au hasard. On déclare donc les communes de
   la crise sur chaque équipe, et on répartit les compétences sans recouvrement.

Et surtout : le générateur crée demandes et signalements par `bulk_create`, qui ne passe par
aucun `perform_create`. Même avec la chaîne réparée, **aucun dossier n'existe pour les lignes
déjà en base** — d'où la phase de rattrapage, qui rejoue exactement la résolution de
`RequestViewSet.perform_create` sur ce qui n'a pas de dossier.

Usage :
  python manage.py completer_affectation_auto_gier --simulation
  python manage.py completer_affectation_auto_gier --intervenant "Fred Bouchet"
  python manage.py completer_affectation_auto_gier --intervenant prenom.nom@exemple.fr --notifier

`--simulation` fait tout le travail dans une transaction annulée à la fin : le rapport décrit
donc des écritures réelles, pas une estimation parallèle qui pourrait divergir du code exécuté.
"""
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.crypto_fields import blind_index
from core.management.commands.generate_crise_gier_pilat import (
    CRISIS_NAME,
    EQUIPE_HEBERGEMENT,
    EQUIPE_LOGISTIQUE,
    EQUIPE_TRANSPORT,
)
from core.models import (
    AffectationRoleOperationnel,
    Besoin,
    BesoinCompetence,
    Competence,
    Crisis,
    DisponibiliteOperationnelle,
    Dossier,
    DossierHistorique,
    DossierParticipant,
    Environment,
    Information,
    InformationType,
    InformationTypeBesoin,
    Request,
    RequestType,
    RequestTypeBesoin,
    RoleOperationnel,
    Team,
    User,
    UserRole,
)

# Thèmes dont le nom ne coïncide pas avec celui du Besoin correspondant : la convention de
# 0042_seed_besoins_categories est le miroir exact des noms, ces trois-là y échappent pour des
# raisons historiques (renommage du catch-all matériel en 0139, libellé du formulaire public).
REQUEST_TYPE_ALIAS_BESOIN = {
    "Nettoyage / déblaiement": "Nettoyage - déblaiement",
    "Assistance à évacuation": "Assistance immédiate",
    "Matériel": "Matériel divers (à préciser)",
}

# Besoin -> Competence. N'est posé que sur un Besoin qui n'a AUCUNE correspondance : plusieurs
# liens sur un même besoin rendraient `resolve_competence_for_request` non déterministe
# (`BesoinCompetence.objects.filter(besoin=...).first()`, sans ordre).
#
# Volontairement absents, et ce n'est pas un oubli :
#  - « Autre » : fourre-tout du formulaire public, aucune compétence ne s'en déduit — le dossier
#    doit tomber en tri manuel, c'est son rôle.
#  - « Information utile » : un signalement d'information n'appelle pas d'intervention.
BESOIN_VERS_COMPETENCE = [
    # Demandes d'aide
    ("Hébergement", "Organisation de l'accueil / hébergement"),
    ("Nourriture et eau", "Logistique"),
    ("Nettoyage - déblaiement", "Nettoyage et déblaiement"),
    ("Pompage", "Nettoyage et déblaiement"),
    ("Accompagnement administratif", "Accueil"),
    ("Groupe électrogène", "Logistique"),
    ("Matériel divers (à préciser)", "Logistique"),
    # Signalements — aucun n'avait de compétence (voir docstring)
    ("Route barrée", "Nettoyage et déblaiement"),
    ("Arbre sur la chaussée", "Nettoyage et déblaiement"),
    ("Danger imminent", "Secourisme"),
]

# Compétences par équipe, SANS RECOUVREMENT (voir point 4 de la docstring : deux équipes sur une
# même compétence, toutes deux sans zone propre et sans charge, donnent une égalité parfaite et
# donc aucune suggestion). Le générateur posait « Logistique » sur deux équipes à la fois.
EQUIPE_COMPETENCES = {
    EQUIPE_HEBERGEMENT: [
        "Organisation de l'accueil / hébergement",
        "Accueil",
        "Soutien psychologique",
    ],
    EQUIPE_LOGISTIQUE: ["Nettoyage et déblaiement", "Logistique"],
    EQUIPE_TRANSPORT: ["Transport", "Secourisme"],
}


class Annulation(Exception):
    """Sort de la transaction en --simulation sans rien laisser en base."""


class Command(BaseCommand):
    help = "Complète la chaîne d'affectation automatique de la crise démo du Gier et rattrape les dossiers manquants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--intervenant", default=None,
            help="Personne à rendre intervenante sur les trois équipes et régulatrice sur leurs "
                 "thèmes. Email, ou « Prénom Nom » si l'email n'est pas connu.",
        )
        parser.add_argument(
            "--notifier", action="store_true",
            help="Notifie les régulateurs des dossiers rattrapés, comme le ferait une création "
                 "en direct. Désactivé par défaut : un rattrapage de plusieurs centaines de "
                 "lignes produirait autant de notifications d'un coup, ce qui noierait la "
                 "cloche au lieu de l'alimenter.",
        )
        parser.add_argument(
            "--simulation", action="store_true",
            help="N'écrit rien : exécute tout dans une transaction annulée à la fin.",
        )

    def handle(self, *args, **options):
        self.simulation = options["simulation"]
        self.notifier = options["notifier"]
        try:
            with transaction.atomic():
                self._executer(options.get("intervenant"))
                if self.simulation:
                    raise Annulation
        except Annulation:
            self.stdout.write(self.style.WARNING(
                "\n--simulation : transaction annulée, rien n'a été écrit."))

    def _executer(self, intervenant_ref):
        crise = Crisis.objects.filter(
            name=CRISIS_NAME, environment=Environment.DEMO).first()
        if crise is None:
            raise CommandError(
                f"Crise démo « {CRISIS_NAME} » introuvable — lancer d'abord "
                f"generate_crise_gier_pilat."
            )
        nb_communes = len(crise.zone_communes or [])
        self._titre(f"Crise : {crise.name} — {nb_communes} commune(s) dans la zone")

        self._correspondances(crise)
        equipes = self._equipes(crise)
        self._intervenant(intervenant_ref, crise, equipes)
        self._rattrapage(crise)

    # ── Rapport ───────────────────────────────────────────────────────────
    def _titre(self, texte):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{texte}"))

    def _ok(self, texte):
        self.stdout.write(f"  + {texte}")

    def _note(self, texte):
        self.stdout.write(f"    {texte}")

    def _alerte(self, texte):
        self.stdout.write(self.style.WARNING(f"  ! {texte}"))

    # ── 1. Correspondances type -> besoin -> compétence ───────────────────
    def _correspondances(self, crise):
        self._titre("1. Correspondances (catalogue partagé PROD/DEMO)")

        types_demande = RequestType.objects.filter(
            id__in=Request.objects.filter(crisis=crise)
            .values_list("request_type_id", flat=True).distinct()
        )
        for request_type in types_demande:
            if RequestTypeBesoin.objects.filter(request_type=request_type).exists():
                continue
            nom_besoin = REQUEST_TYPE_ALIAS_BESOIN.get(request_type.type, request_type.type)
            besoin = self._besoin_miroir(nom_besoin)
            RequestTypeBesoin.objects.create(request_type=request_type, besoin=besoin)
            self._ok(f"Demande « {request_type.type} » -> besoin « {besoin.nom} »")

        types_signalement = InformationType.objects.filter(
            id__in=Information.objects.filter(crisis=crise)
            .values_list("information_type_id", flat=True).distinct()
        )
        for information_type in types_signalement:
            if InformationTypeBesoin.objects.filter(information_type=information_type).exists():
                continue
            besoin = self._besoin_miroir(information_type.type)
            InformationTypeBesoin.objects.create(
                information_type=information_type, besoin=besoin)
            self._ok(f"Signalement « {information_type.type} » -> besoin « {besoin.nom} »")

        for nom_besoin, nom_competence in BESOIN_VERS_COMPETENCE:
            besoin = Besoin.objects.filter(nom=nom_besoin).first()
            if besoin is None:
                self._alerte(f"Besoin « {nom_besoin} » absent du catalogue.")
                continue
            existant = BesoinCompetence.objects.filter(besoin=besoin).first()
            if existant is not None:
                if existant.competence and existant.competence.nom != nom_competence:
                    self._note(f"« {nom_besoin} » déjà relié à « {existant.competence.nom} » — laissé tel quel.")
                continue
            competence = Competence.objects.filter(nom=nom_competence).first()
            if competence is None:
                self._alerte(f"Compétence « {nom_competence} » absente du catalogue — « {nom_besoin} » reste sans compétence.")
                continue
            BesoinCompetence.objects.create(besoin=besoin, competence=competence)
            self._ok(f"Besoin « {nom_besoin} » -> compétence « {competence.nom} »")

    def _besoin_miroir(self, nom):
        """Le Besoin homonyme du type, créé s'il manque — convention des seeds 0042 (demandes)
        et 0174 (signalements), qui montent RequestType/InformationType et Besoin en miroir de
        nom. `nature` reste vide : dire d'un thème s'il mobilise du savoir-faire ou du matériel
        est une qualification métier, que cette commande n'a pas à inventer."""
        besoin = Besoin.objects.filter(nom=nom).first()
        if besoin is None:
            besoin = Besoin.objects.create(nom=nom, actif=True)
            self._note(f"besoin « {nom} » créé (absent du catalogue)")
        return besoin

    # ── 2. Équipes : compétences, zone, affectations ──────────────────────
    def _equipes(self, crise):
        from core.views import affecter_competences_aux_crises

        self._titre("2. Équipes")
        equipes = []
        for nom_equipe, noms_competences in EQUIPE_COMPETENCES.items():
            equipe = Team.objects.filter(name=nom_equipe, environment=Environment.DEMO).first()
            if equipe is None:
                self._alerte(f"Équipe « {nom_equipe} » introuvable.")
                continue
            equipes.append(equipe)

            competences = list(Competence.objects.filter(nom__in=noms_competences))
            manquantes = set(noms_competences) - {c.nom for c in competences}
            for nom in sorted(manquantes):
                self._alerte(f"Compétence « {nom} » absente du catalogue.")
            equipe.competences.set(competences)
            self._ok(f"{equipe.name} : {', '.join(sorted(c.nom for c in competences))}")

            if crise not in equipe.assigned_crises.all():
                equipe.assigned_crises.add(crise)
                self._note("rattachée à la crise")

            # Zone explicite : fait passer le score de 0 (repli sur la zone de la crise) à 2,
            # et rend la couverture lisible sur la fiche équipe au lieu d'être implicite.
            if not equipe.communes and crise.zone_communes:
                equipe.communes = list(crise.zone_communes)
                equipe.save(update_fields=["communes"])
                self._note(f"zone déclarée : {len(equipe.communes)} communes")

            crees = affecter_competences_aux_crises(equipe)
            self._note(f"{crees} affectation(s) de compétence créée(s)")
        return equipes

    # ── 3. Intervenant / régulateur ───────────────────────────────────────
    def _resoudre_personne(self, reference):
        if "@" in reference:
            return User.objects.filter(email_bidx=blind_index(reference.strip().lower())).first()
        morceaux = reference.split()
        nom = morceaux[-1]
        candidats = User.objects.filter(last_name__iexact=nom)
        if len(morceaux) > 1:
            candidats = candidats.filter(first_name__istartswith=morceaux[0])
        return candidats.first()

    def _intervenant(self, reference, crise, equipes):
        self._titre("3. Intervenant")
        if not reference:
            self._note("aucun --intervenant fourni : phase ignorée.")
            return

        personne = self._resoudre_personne(reference)
        if personne is None:
            self._alerte(f"Personne « {reference} » introuvable — phase ignorée.")
            return
        self._ok(f"{personne.first_name} {personne.last_name} — rôle {personne.type}")
        # Les entrées du menu d'administration dépendent du RÔLE du compte, pas de
        # l'appartenance à une équipe (voir admin-nav.config.ts, `visibilite`) : être
        # intervenant fait apparaître les dossiers dans « Mes interventions », pas les menus.
        if personne.type == UserRole.SIMPLE_USER:
            self._alerte(
                "Compte UTIL_SIMPLE : il verra ses interventions, mais aucun menu "
                "d'administration tant que son rôle n'est pas relevé."
            )

        role_regulateur = RoleOperationnel.objects.filter(code="REGULATEUR").first()
        if role_regulateur is None:
            self._alerte("Rôle REGULATEUR absent (migration 0093) — régulation non posée.")

        for equipe in equipes:
            if not equipe.members.filter(pk=personne.pk).exists():
                equipe.members.add(personne)
                self._note(f"ajouté comme intervenant à « {equipe.name} »")

            if role_regulateur is None or equipe.institution_id is None:
                continue
            # Régulateur sur les thèmes de l'équipe : sans cela le dossier naît en
            # EN_ATTENTE_DISTRIBUTION et /dossiers/ma_file/ reste vide (voir docstring, point 3).
            for competence in equipe.competences.all():
                affectation, cree = AffectationRoleOperationnel.objects.get_or_create(
                    utilisateur=personne, institution=equipe.institution,
                    competence=competence, role=role_regulateur,
                    defaults={"actif": True, "environment": Environment.DEMO,
                              "commentaire": "Posée pour la crise démo du Gier."},
                )
                if not affectation.actif:
                    affectation.actif = True
                    affectation.save(update_fields=["actif"])
                if not affectation.disponibilites.filter(
                        disponible=True, date_fin__isnull=True).exists():
                    DisponibiliteOperationnelle.objects.create(
                        affectation=affectation, disponible=True,
                        environment=Environment.DEMO,
                        commentaire="Permanence ouverte (crise démo du Gier).",
                    )
                if cree:
                    self._note(f"régulateur sur « {competence.nom} »")

    # ── 4. Rattrapage du delta ────────────────────────────────────────────
    def _rattrapage(self, crise):
        from core.views import (
            meilleure_equipe_pour_competence,
            populate_dossier_participants_and_notify,
            resolve_besoin_for_information,
            resolve_besoin_for_request,
            resolve_competence_for_information,
            resolve_competence_for_request,
        )

        self._titre("4. Rattrapage des dossiers manquants")

        comptes = {"demandes": 0, "signalements": 0, "avec_equipe": 0,
                   "sans_competence": 0, "en_attente_distribution": 0}

        def _regulateur_disponible(competence):
            return AffectationRoleOperationnel.objects.filter(
                competence=competence, role__code="REGULATEUR", actif=True,
                disponibilites__disponible=True, disponibilites__date_fin__isnull=True,
            ).exists()

        def _creer(objet, champ, competence, besoin, libelle):
            equipe = (
                meilleure_equipe_pour_competence(crise, competence, objet)
                if competence else None
            )
            if competence is None:
                statut = Dossier.Statut.EN_ATTENTE_AFFECTATION
                comptes["sans_competence"] += 1
            elif _regulateur_disponible(competence):
                statut = Dossier.Statut.EN_ATTENTE_AFFECTATION
            else:
                statut = Dossier.Statut.EN_ATTENTE_DISTRIBUTION
                comptes["en_attente_distribution"] += 1
            if equipe is not None:
                comptes["avec_equipe"] += 1

            dossier = Dossier.objects.create(
                numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
                crise=crise, competence=competence, besoin=besoin, equipe=equipe,
                titre=objet.title,
                description=f"{libelle} créé(e) automatiquement : {objet.title}",
                statut=statut, environment=objet.environment,
                **{champ: objet},
            )
            # Le demandeur n'est volontairement PAS résolu ici : `resolve_or_invite_demandeur`
            # crée un compte à la volée depuis les coordonnées du formulaire, ce qui
            # fabriquerait plusieurs centaines de comptes pour des contacts Faker. Les
            # participants qui comptent pour la démo — l'équipe et la régulation — le sont.
            if self.notifier:
                populate_dossier_participants_and_notify(dossier, equipe=equipe)
            else:
                self._participants_sans_notification(dossier, equipe)
            return dossier

        for demande in (
            Request.objects.filter(crisis=crise, dossiers__isnull=True)
            .select_related("request_type")
        ):
            _creer(demande, "demande", resolve_competence_for_request(demande),
                   resolve_besoin_for_request(demande), "Demande")
            comptes["demandes"] += 1

        for signalement in (
            Information.objects.filter(crisis=crise, dossiers__isnull=True)
            .select_related("information_type")
        ):
            _creer(signalement, "information", resolve_competence_for_information(signalement),
                   resolve_besoin_for_information(signalement), "Signalement")
            comptes["signalements"] += 1

        self._ok(f"{comptes['demandes']} demande(s) et {comptes['signalements']} signalement(s) dotés d'un dossier")
        self._note(f"{comptes['avec_equipe']} avec une équipe suggérée")
        self._note(f"{comptes['sans_competence']} sans compétence (tri manuel)")
        self._note(f"{comptes['en_attente_distribution']} en attente de distribution (aucun régulateur disponible sur le thème)")
        if not self.notifier:
            self._note("notifications non envoyées (--notifier pour les produire)")

    def _participants_sans_notification(self, dossier, equipe):
        """Même peuplement que `populate_dossier_participants_and_notify`, sans la cloche :
        un rattrapage de masse doit laisser les dossiers consultables dans « Mes interventions »
        sans produire des centaines de notifications datées d'aujourd'hui pour des faits
        vieux de trois jours."""
        if equipe is None:
            return
        DossierHistorique.objects.create(
            dossier=dossier, evenement=f"Équipe affectée : {equipe.name}",
            environment=dossier.environment,
        )
        for membre in equipe.members.all():
            DossierParticipant.objects.get_or_create(
                dossier=dossier, utilisateur=membre, role=DossierParticipant.Role.EQUIPE,
                defaults={"environment": dossier.environment},
            )
