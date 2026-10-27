"""Fusionne deux Institution qui désignent la même collectivité.

Le doublon n'est pas un accident isolé : `find_or_create_institution_from_annuaire`
(institution_attachment.py) fait son `get_or_create` sur le SEUL nom de l'institution, sans
recouper le code commune ni le type. Une mairie déjà présente sous un nom court
(« Châteauneuf-du-Faou ») est donc recréée dès que quelqu'un s'inscrit par l'annuaire officiel,
qui la nomme autrement (« Mairie - Châteauneuf-du-Faou »). Mesuré sur la commune 29027 le
27/10/2026 : deux institutions, les deux déclarées acteur sur la même crise, deux équipes
jumelles, et un agent dont le compte pointait sur l'une pendant que son plan vivait sur l'autre.
Tant que la création n'est pas corrigée, le cas se reproduira — d'où une commande plutôt qu'un
script jetable.

Marche à suivre : TOUJOURS une passe à blanc d'abord (`--a-blanc`), lire le plan, et ne lancer
la fusion qu'après une sauvegarde de la base. L'opération est irréversible.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    AffectationRoleOperationnel, ContactInstitution, ContributionZoneCommune,
    DemandeMobilisation, ImplicationInstitution, Institution, Plan, RisqueCommunal, Team, User,
    Zone,
)

# Champs d'identité que l'absorbée peut légitimement apporter : une institution créée à la main
# par un administrateur porte les coordonnées officielles (standard de la mairie, adresse
# postale), là où celle créée par l'annuaire hérite de l'adresse personnelle du premier inscrit.
CHAMPS_IDENTITE = ("email", "telephone", "adresse")


class Command(BaseCommand):
    help = (
        "Fusionne deux institutions désignant la même collectivité : tout ce qui pointe vers "
        "l'absorbée est repointé vers celle qu'on garde, les doublons stricts sont écartés, et "
        "l'absorbée est désactivée et renommée (jamais supprimée : la fusion est déjà "
        "irréversible, autant garder une trace). Passe à blanc obligatoire d'abord."
    )

    def add_arguments(self, parser):
        parser.add_argument("--garder", required=True,
                            help="UUID de l'institution qui survit.")
        parser.add_argument("--absorber", required=True,
                            help="UUID de l'institution dont tout est transféré.")
        parser.add_argument("--a-blanc", action="store_true",
                            help="N'écrit rien : affiche le plan de fusion et s'arrête.")
        parser.add_argument(
            "--reprendre-identite", action="store_true",
            help="Reprend aussi email/téléphone/adresse de l'absorbée quand elle les a et que "
                 "l'autre ne les a pas, ou que l'autre porte une adresse personnelle. "
                 "À n'utiliser que si l'absorbée porte les coordonnées officielles.")

    def handle(self, *args, **options):
        garder = self._institution(options["garder"], "--garder")
        absorber = self._institution(options["absorber"], "--absorber")
        if garder.pk == absorber.pk:
            raise CommandError("--garder et --absorber désignent la même institution.")
        if garder.commune_code != absorber.commune_code:
            raise CommandError(
                f"Codes commune différents ({garder.commune_code!r} contre "
                f"{absorber.commune_code!r}) : ce ne sont pas deux doublons de la même "
                f"collectivité. Refus — vérifiez les identifiants."
            )

        a_blanc = options["a_blanc"]
        self.stdout.write(self.style.MIGRATE_HEADING(
            "PASSE À BLANC — rien ne sera écrit" if a_blanc else "FUSION RÉELLE"))
        self.stdout.write(f"  on garde   : {garder.nom}  (id={garder.pk}, "
                          f"type={garder.type.code if garder.type_id else '—'}, "
                          f"actif={garder.actif})")
        self.stdout.write(f"  on absorbe : {absorber.nom}  (id={absorber.pk}, "
                          f"type={absorber.type.code if absorber.type_id else '—'}, "
                          f"actif={absorber.actif})")
        self.stdout.write("")

        with transaction.atomic():
            self._fusionner(garder, absorber, options)
            if a_blanc:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING(
                    "\nPasse à blanc : tout a été annulé. Relancez sans --a-blanc, après une "
                    "sauvegarde de la base."))
            else:
                self.stdout.write(self.style.SUCCESS("\nFusion effectuée."))

    # ── mécanique ───────────────────────────────────────────────────────────────────────────

    def _institution(self, valeur, drapeau):
        institution = Institution.objects.filter(pk=valeur).first()
        if institution is None:
            raise CommandError(f"{drapeau} : aucune institution avec l'identifiant {valeur}.")
        return institution

    def _dire(self, verbe, texte):
        self.stdout.write(f"  {verbe:<12} {texte}")

    def _fusionner(self, garder, absorber, options):
        # 1. Les comptes : User.institution est ce que lisent les vues territoriales
        #    (zone_scoping._institution_commune_or_400), alors que le reste de l'application
        #    passe par ContactInstitution. Un compte oublié ici reste aveugle à sa propre
        #    commune sans qu'aucun message ne le dise.
        comptes = User.objects.filter(institution=absorber)
        for u in comptes:
            self._dire("compte", f"{u.last_name or u.username} → rattaché à {garder.nom}")
        comptes.update(institution=garder)

        # 2. Les rattachements. Une personne peut être contact des DEUX : on garde sa ligne
        #    côté survivante et on y verse ce que l'autre savait de mieux (une fonction
        #    précise vaut mieux que « Membre », et le contact principal ne doit pas se perdre).
        self._fusionner_contacts(garder, absorber)

        # 3. Ce qui se déplace sans discuter : aucune contrainte d'unicité ne s'y oppose.
        #
        #    La Zone « Mon territoire » n'en fait PAS partie, et c'est délibéré : les deux
        #    institutions en ont une, identique (même commune), et `_assurer_zone_mon_territoire`
        #    la recrée de toute façon à chaque enregistrement de l'institution. La déplacer
        #    donnerait deux « Mon territoire » jumelles à la survivante, et l'absorbée s'en
        #    verrait aussitôt refabriquer une. On laisse donc la sienne à l'absorbée et on
        #    repointe ce qui la désignait (voir _fusionner_contacts).
        for modele, champ, libelle in (
            (Team, "institution", "équipe"),
            (Plan, "institution", "plan"),
            (ContributionZoneCommune, "institution", "contribution de zone"),
            (DemandeMobilisation, "institution_emettrice", "demande de mobilisation"),
        ):
            for objet in modele.objects.filter(**{champ: absorber}):
                self._dire("déplace", f"{libelle} « {self._nom_de(objet)} »")
            modele.objects.filter(**{champ: absorber}).update(**{champ: garder})

        # 4. Ce qui se déplace SAUF si la survivante a déjà l'équivalent. Repointer sans
        #    vérifier violerait la contrainte d'unicité et ferait échouer toute la fusion.
        self._deplacer_sans_doublon(
            ImplicationInstitution, absorber, garder,
            cle=lambda o: (o.crise_id, o.type_implication),
            libelle=lambda o: f"implication {o.type_implication} sur « {o.crise.name} »")
        self._deplacer_sans_doublon(
            AffectationRoleOperationnel, absorber, garder,
            cle=lambda o: (o.utilisateur_id, o.competence_id, o.role_id),
            libelle=lambda o: f"rôle « {o.role} » de {o.utilisateur.last_name}")
        self._deplacer_sans_doublon(
            RisqueCommunal, absorber, garder,
            cle=lambda o: (o.risque_type_id,),
            libelle=lambda o: f"risque « {o.risque_type} »",
            # Un risque dont l'état des lieux ou les enjeux sont renseignés porte du travail
            # humain : il ne s'écarte pas en silence.
            porte_du_travail=lambda o: bool(o.etat_des_lieux or o.enjeux))

        # 5. Les coordonnées officielles, à la demande seulement.
        if options["reprendre_identite"]:
            for champ in CHAMPS_IDENTITE:
                valeur = getattr(absorber, champ, None)
                if valeur:
                    ancienne = getattr(garder, champ, None)
                    self._dire("identité", f"{champ} : {ancienne!r} → {valeur!r}")
                    setattr(garder, champ, valeur)

        # `save()` complet et non `update()` : c'est lui qui recalcule epci/département/région
        # et le niveau de secteur (voir Institution.save).
        garder.save()

        # 6. L'absorbée reste, désactivée et renommée sans ambiguïté : la fusion est déjà
        #    irréversible, un enregistrement vide ne coûte rien et dit ce qui s'est passé.
        #
        #    Par `update()` et non `save()` : `Institution.save()` déclenche
        #    `_assurer_zone_mon_territoire`, qui recréerait une zone sur l'absorbée — et comme
        #    `Zone.institution` est en PROTECT, cette zone fantôme interdirait ensuite toute
        #    suppression de l'enregistrement.
        marque = f"[fusionnée dans {garder.nom}]"
        nom_final = (absorber.nom if marque in (absorber.nom or "")
                     else f"{absorber.nom} {marque}"[:255])
        Institution.objects.filter(pk=absorber.pk).update(actif=False, nom=nom_final)
        absorber.refresh_from_db()
        self._dire("désactive", f"{absorber.nom}")

        restants = [
            (rel.related_model.__name__, rel.field.name, n)
            for rel in absorber._meta.related_objects
            for n in [self._compter(absorber, rel)]
            if n
        ]
        if restants:
            self.stdout.write(self.style.WARNING("\n  Pointent encore vers l'absorbée :"))
            for modele, champ, n in restants:
                self.stdout.write(f"    {modele}.{champ} : {n}")
            self.stdout.write(
                "    (la main courante est une archive : elle doit continuer de désigner "
                "l'institution telle qu'elle existait au moment des faits. Sa zone « Mon "
                "territoire » reste aussi, et comme Zone.institution est en PROTECT, elle "
                "empêchera la suppression définitive de l'enregistrement — ce qui est "
                "exactement ce qu'on veut d'une pierre tombale.)")

    def _compter(self, institution, rel):
        try:
            accesseur = getattr(institution, rel.get_accessor_name())
            return accesseur.count() if hasattr(accesseur, "count") else 0
        except Exception:
            return 0

    def _nom_de(self, objet):
        for champ in ("nom", "name", "libelle"):
            valeur = getattr(objet, champ, None)
            if valeur:
                return valeur
        return str(objet.pk)

    def _fusionner_contacts(self, garder, absorber):
        deja = {c.utilisateur_id: c
                for c in ContactInstitution.objects.filter(institution=garder)}
        zone_garder = Zone.objects.filter(institution=garder).first()
        principal_pris = any(c.contact_principal for c in deja.values())

        for contact in ContactInstitution.objects.filter(
                institution=absorber).select_related("utilisateur"):
            nom = contact.utilisateur.last_name or contact.utilisateur.username
            jumeau = deja.get(contact.utilisateur_id)
            if jumeau is None:
                contact.institution = garder
                # La zone appartenait à l'absorbée et va disparaître avec elle.
                contact.zone = zone_garder
                # `uq_contact_principal_institution` n'autorise qu'un contact principal par
                # institution : laisser le drapeau voyager alors que la survivante a déjà le
                # sien fait échouer TOUTE la fusion sur une violation d'unicité. La
                # désignation du principal appartient de toute façon à la collectivité, pas à
                # une opération de maintenance.
                degrade = contact.contact_principal and principal_pris
                if degrade:
                    contact.contact_principal = False
                elif contact.contact_principal:
                    principal_pris = True
                contact.save()
                self._dire("déplace", f"rattachement de {nom} ({contact.fonction})"
                                      + (" — n'est plus contact principal, la survivante en "
                                         "avait déjà un" if degrade else ""))
                continue

            change = []
            # « Membre » est le repli du formulaire ; toute autre fonction a été saisie.
            if contact.fonction and jumeau.fonction in (None, "", "Membre") \
                    and contact.fonction != jumeau.fonction:
                jumeau.fonction = contact.fonction
                change.append(f"fonction → {contact.fonction}")
            if contact.contact_principal and not principal_pris:
                jumeau.contact_principal = True
                principal_pris = True
                change.append("devient contact principal")
            if jumeau.zone_id is None and zone_garder is not None:
                jumeau.zone = zone_garder
                change.append(f"zone → {zone_garder.nom}")
            if change:
                jumeau.save()
            self._dire("fusionne", f"rattachement de {nom} : "
                                   f"{', '.join(change) if change else 'rien à reprendre'}")
            contact.delete()

    def _deplacer_sans_doublon(self, modele, absorber, garder, cle, libelle,
                               porte_du_travail=None):
        existants = {cle(o) for o in modele.objects.filter(institution=garder)}
        for objet in modele.objects.filter(institution=absorber):
            if cle(objet) in existants:
                if porte_du_travail is not None and porte_du_travail(objet):
                    self.stdout.write(self.style.WARNING(
                        f"  À REPRENDRE À LA MAIN : {libelle(objet)} existe des deux côtés et "
                        f"celui de l'absorbée est renseigné — rien n'est écarté, il reste "
                        f"rattaché à l'absorbée."))
                    continue
                self._dire("écarte", f"{libelle(objet)} (déjà présent, et vide)")
                objet.delete()
                continue
            objet.institution = garder
            objet.save()
            existants.add(cle(objet))
            self._dire("déplace", libelle(objet))
