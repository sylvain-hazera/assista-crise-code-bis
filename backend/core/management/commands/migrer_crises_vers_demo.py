"""Déplace des crises de la production vers la zone de démonstration, en rendant anonymes les
données des personnes, puis prévient par courriel les responsables des institutions actrices
(demande de Sylvain du 18/11/2026 : « migrer les 4 crises de la prod vers la dev et prévenir par
mail leurs acteurs pour qu'ils les retrouvent » ; choix faits avec lui : zone de démonstration,
données des habitants rendues anonymes, courriel aux responsables des institutions actrices).

    manage.py migrer_crises_vers_demo                       # montre les crises de production
    manage.py migrer_crises_vers_demo --crises ID,ID        # montre ce qui serait fait
    manage.py migrer_crises_vers_demo --crises ID,ID --appliquer

Par défaut RIEN n'est modifié : la commande dit ce qu'elle ferait. `--appliquer` agit, en une
seule transaction ; les courriels partent seulement une fois la transaction réussie.

Ce qui part en démonstration : la crise et tout ce qui la compose, et les fiches qui en dépendent
(commentaires d'un dossier, réponses d'un formulaire…). Ce qui reste en production, non touché :
- la main courante, qui est une trace et ne se réécrit pas ;
- le stock permanent (mouvements, prêts) : le déplacer fausserait les quantités de production ;
- la radio et les salons de messagerie, liés à de vrais appareils et de vrais salons ;
- les campagnes de disponibilité et les exercices du plan, qui appartiennent à l'institution ;
- les photos, pièces jointes et rapports : personnels, ils ne suivent pas.

Anonymisation : tout champ chiffré (la convention du projet : ce qui est personnel est chiffré)
des fiches déplacées est remplacé — nom, courriel, téléphone, adresse — et dans les textes libres
les courriels et numéros de téléphone sont effacés. Irréversible : la sauvegarde de la base faite
juste avant (scripts/114/) est le seul retour possible. Les originaux ne sont copiés nulle part.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

#: Rattachés à la crise, mais qui ne la suivent pas (voir l'en-tête).
NE_SUIVENT_PAS = {
    "User", "AuditLog", "MouvementStock", "PretMateriel", "CanalMeshCore", "CanalMeshtastic",
    "SalonMatrixEquipe", "CampagneDisponibilite", "ExercicePCS", "RapportConserve",
    # Enfants de fiches déplacées, qui restent eux aussi : photos et pièces.
    "RequestPhoto", "OfferPhoto", "Document", "RecherchePersonnePhoto", "RattachementHabitation",
    "DepotStock", "DemandeTransfertStock",
}

_COURRIEL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_TELEPHONE = re.compile(r"(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}")


def _nettoyer_texte(texte):
    if not isinstance(texte, str):
        return texte
    return _TELEPHONE.sub("[numéro retiré]", _COURRIEL.sub("[courriel retiré]", texte))


def _nettoyer(valeur):
    """Pour un champ JSON (réponses d'un formulaire) : même nettoyage, sur chaque texte."""
    if isinstance(valeur, dict):
        return {k: _nettoyer(v) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [_nettoyer(v) for v in valeur]
    return _nettoyer_texte(valeur)


def valeur_anonyme(nom_champ, valeur, rang):
    """Ce qui remplace un champ personnel. Le nom du champ dit sa nature."""
    if valeur in (None, ""):
        return valeur
    nom = nom_champ.lower()
    if "email" in nom or "courriel" in nom:
        return f"anonyme-{rang}@exemple.invalide"
    if any(m in nom for m in ("telephone", "phone", "tel_")) or nom in ("contact", "contact_referent", "hebergeur_contact",
                                                                         "reparateur_contact"):
        return "0600000000"
    if "adresse" in nom or nom in ("lieu",):
        return "Adresse anonymisée"
    if any(m in nom for m in ("prenom", "first_name")):
        return "Prénom"
    if any(m in nom for m in ("nom", "last_name", "name", "hebergeur", "identification", "immatriculation", "adeli")):
        return f"Personne {rang}"
    if isinstance(valeur, (dict, list)):
        return _nettoyer(valeur)
    return _nettoyer_texte(valeur)


def collecter(crise):
    """{modèle: [identifiants]} de tout ce qui suit cette crise, dans l'ordre de traitement."""
    from core.models import Crisis

    def relations(modele, cascade_seulement):
        for relation in modele._meta.related_objects:
            if not (relation.one_to_many or relation.one_to_one):
                continue
            if relation.related_model.__name__ in NE_SUIVENT_PAS:
                continue
            if cascade_seulement and relation.on_delete.__name__ != "CASCADE":
                continue
            yield relation

    a_deplacer = {}
    for relation in relations(Crisis, cascade_seulement=False):
        modele = relation.related_model
        ids = list(modele.objects.filter(**{relation.field.name: crise}).values_list("pk", flat=True))
        if ids:
            a_deplacer.setdefault(modele, set()).update(ids)
    for parent in list(a_deplacer):
        for relation in relations(parent, cascade_seulement=True):
            enfant = relation.related_model
            ids = list(enfant.objects.filter(**{f"{relation.field.name}__in": a_deplacer[parent]}).values_list("pk", flat=True))
            if ids:
                a_deplacer.setdefault(enfant, set()).update(ids)
    return a_deplacer


def champs_personnels(modele):
    return [f for f in modele._meta.concrete_fields if "Encrypted" in type(f).__name__]


def textes_libres(modele):
    """Les textes non chiffrés (un commentaire de dossier, par exemple) : on n'y remplace pas tout,
    mais on en efface courriels et numéros de téléphone. Un nom écrit en toutes lettres dans une
    phrase ne se détecte pas de façon sûre : c'est la limite de ce nettoyage."""
    from django.db import models as m
    return [f for f in modele._meta.concrete_fields
            if isinstance(f, m.TextField) and "Encrypted" not in type(f).__name__]


def champs_fichier(modele):
    return [f for f in modele._meta.concrete_fields if "File" in type(f).__name__ or "Image" in type(f).__name__]


def responsables(crises):
    """{courriel: (nom, [noms de crises])} des responsables des institutions actrices."""
    from core.models import ImplicationInstitution

    destinataires = {}
    for implication in ImplicationInstitution.objects.filter(crise__in=crises, actif=True).select_related("responsable", "crise"):
        compte = implication.responsable
        if compte is None or not compte.email:
            continue
        nom, noms = destinataires.setdefault(compte.email, (f"{compte.first_name} {compte.last_name}".strip(), []))
        if implication.crise.name not in noms:
            noms.append(implication.crise.name)
    return destinataires


class Command(BaseCommand):
    help = "Déplace des crises de la production vers la zone de démonstration (données anonymisées) et prévient leurs responsables."

    def add_arguments(self, parser):
        parser.add_argument("--crises", default="", help="Identifiants des crises, séparés par des virgules.")
        parser.add_argument("--appliquer", action="store_true", help="Agir. Sans lui, la commande montre seulement.")
        parser.add_argument("--sans-courriel", action="store_true", help="Ne prévenir personne.")

    def handle(self, *args, crises="", appliquer=False, sans_courriel=False, **options):
        from core.models import Crisis, Environment

        if not crises:
            self.stdout.write("Crises de production (ouvertes et closes) :")
            for c in Crisis.objects.filter(environment=Environment.PROD).order_by("-start_date"):
                etat = "close" if c.end_date else "ouverte"
                self.stdout.write(f"  {c.id}  {c.name}  ({c.get_type_display()}, {etat}{', essai' if c.essai else ''}, "
                                  f"depuis le {c.start_date:%d/%m/%Y})")
            self.stdout.write("Relancez avec --crises ID,ID pour voir ce qui serait fait.")
            return

        identifiants = [i.strip() for i in crises.split(",") if i.strip()]
        choisies = list(Crisis.objects.filter(pk__in=identifiants, environment=Environment.PROD))
        if len(choisies) != len(identifiants):
            trouvees = {str(c.id) for c in choisies}
            raise CommandError("Introuvables en production : " + ", ".join(i for i in identifiants if i not in trouvees))

        plan = {c: collecter(c) for c in choisies}
        destinataires = responsables(choisies)
        for crise, a_deplacer in plan.items():
            self.stdout.write(f"\n« {crise.name} » ({crise.id})")
            for modele, ids in sorted(a_deplacer.items(), key=lambda m: m[0].__name__):
                perso = ", ".join(f.name for f in champs_personnels(modele))
                self.stdout.write(f"  {modele.__name__} : {len(ids)}" + (f"   — anonymisés : {perso}" if perso else ""))
        self.stdout.write(f"\nSeraient prévenus ({len(destinataires)}) :")
        for courriel, (nom, noms) in destinataires.items():
            self.stdout.write(f"  {nom or courriel} — {', '.join(noms)}")

        if not appliquer:
            self.stdout.write(self.style.WARNING("\nRien n'a été modifié. Ajoutez --appliquer pour agir, après une sauvegarde de la base."))
            return

        rang = 0
        with transaction.atomic():
            for crise, a_deplacer in plan.items():
                for modele, ids in a_deplacer.items():
                    personnels, fichiers, libres = champs_personnels(modele), champs_fichier(modele), textes_libres(modele)
                    if personnels or fichiers or libres:
                        for objet in modele.objects.filter(pk__in=ids):
                            rang += 1
                            for champ in personnels:
                                setattr(objet, champ.attname, valeur_anonyme(champ.name, getattr(objet, champ.attname), rang))
                            for champ in libres:
                                setattr(objet, champ.attname, _nettoyer_texte(getattr(objet, champ.attname)))
                            for champ in fichiers:
                                setattr(objet, champ.attname, "")       # la photo reste en production
                            # Écriture directe : ni signaux ni effets d'une création ; les index
                            # aveugles éventuels sont recalculés par save() du modèle si on l'appelle,
                            # d'où save(update_fields=…) quand le modèle en a.
                            noms = [c.attname for c in personnels + fichiers + libres]
                            noms += [c.attname for c in modele._meta.concrete_fields if c.attname.endswith("_bidx")]
                            objet.save(update_fields=sorted(set(noms)))
                    if any(f.name == "environment" for f in modele._meta.concrete_fields):
                        modele.objects.filter(pk__in=ids).update(environment=Environment.DEMO)
                Crisis.objects.filter(pk=crise.pk).update(environment=Environment.DEMO)
        self.stdout.write(self.style.SUCCESS(f"\n{len(plan)} crise(s) déplacée(s) en zone de démonstration, {rang} fiche(s) anonymisée(s)."))

        if sans_courriel:
            return
        from django.conf import settings

        from core.audit import send_mail_logged
        adresse = getattr(settings, "SERVER_URL", "").rstrip("/")
        partis = 0
        for courriel, (nom, noms) in destinataires.items():
            liste = "\n".join(f"  - {n}" for n in noms)
            corps = (
                f"Bonjour{(' ' + nom) if nom else ''},\n\n"
                f"Les crises suivantes, sur lesquelles votre institution est engagée, ont été déplacées dans la zone de "
                f"démonstration d'Assista-Crise :\n{liste}\n\n"
                "Pour les retrouver : connectez-vous, puis basculez sur « Démo » en haut de la page. Elles y sont avec leurs "
                "équipes, leurs dossiers et leurs signalements. Les données des habitants y ont été rendues anonymes : "
                "noms, coordonnées et adresses ont été remplacés.\n\n"
                f"{adresse}\n\nL'équipe Assista-Crise"
            )
            try:
                send_mail_logged(None, "Vos crises sont maintenant dans la zone de démonstration", corps, None, [courriel])
                partis += 1
            except Exception as erreur:  # noqa: BLE001 -- un courriel en échec n'annule rien
                self.stdout.write(self.style.ERROR(f"  Courriel non parti pour {courriel} : {erreur}"))
        self.stdout.write(f"{partis} courriel(s) envoyé(s) sur {len(destinataires)}.")
