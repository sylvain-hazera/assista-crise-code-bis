"""Copie central -> satellite des équipes et de la radio (demande du 21/10/2026, retour de terrain
de la Loire : le companion MeshCore du satellite remontait au central mais restait invisible sur
l'instance locale, et les équipes n'y existaient pas).

Jusqu'ici SatelliteViewSet.donnees ne renvoyait que les crises et ce qui leur est rattaché
(annonces, dossiers, missions). Or hors ligne, le pont radio du satellite bascule sur le backend
LOCAL (meshcore-bridge/bridge.py, DjangoClient) et y appelle /compagnons-meshcore/<id>/... avec
l'identifiant de SON companion : sans copie locale de ce companion, de ses canaux et des nœuds
connus, aucun de ces appels ne pouvait aboutir -- le relais radio hors ligne ne fonctionnait pas.

Même régime que les annonces (sync_outbox.appliquer_payload_pull) : le central fait autorité,
copie à l'identique par identifiant, jamais renvoyée au central. Particularités :
- limitée à l'institution du satellite (ses équipes, ses companions, leurs canaux et contacts,
  les nœuds radio de ses membres ; répéteurs de l'institution et répéteurs communs) ;
- générique : chaque champ est lu sur le modèle lui-même, pas recopié à la main dans une liste
  -- un champ ajouté plus tard suit sans retouche ;
- écrit par QuerySet.update / bulk_create, sans save() : une équipe créée sur le satellite ne
  doit pas déclencher les effets d'une création (salon Matrix, notifications...) ;
- une clé étrangère vers un objet absent du satellite (institution tierce, zone, compte d'une
  autre institution) devient vide ; si le champ est obligatoire, l'objet est ignoré ;
- clé naturelle (pubkey, node_num...) déjà prise localement par une autre ligne, typiquement un
  contact découvert par le pont pendant une coupure : cette ligne locale est mise à jour au lieu
  d'en créer une seconde, qui violerait la contrainte d'unicité.

Les companions Meshtastic portent des secrets (mot de passe MQTT, clé privée PKI) : ils ne vont
qu'au compte de service de CE satellite, sur la machine de l'institution, qui les reçoit déjà en
ligne (CompagnonMeshtasticViewSet.actifs_avec_identifiants) -- sans eux, pas de déchiffrement
hors ligne.
"""
import uuid

from django.apps import apps
from django.contrib.gis.db.models import GeometryField
from django.contrib.gis.geos import GEOSGeometry
from django.db import transaction
from django.db.models import Q


# Ordre = ordre d'application : une équipe avant le canal qui la cite, un companion avant ses
# contacts. clés_naturelles : champs uniques autres que l'id (voir l'en-tête).
# m2m : relations copiées par identifiant (cibles déjà présentes localement seulement) ;
# m2m_catalogue : référentiels partagés, retrouvés par leur nom (ids différents d'une base à
# l'autre, comme pour Offer.competences dans sync_outbox).
SPEC = (
    ("Team", "equipes", {
        "cles_naturelles": (),
        "m2m": ("members", "assigned_crises", "assigned_offers", "assigned_requests", "assigned_informations"),
        "m2m_catalogue": {"competences": ("Competence", "nom"), "themes": ("Besoin", "nom")},
    }),
    ("CompagnonMeshCore", "compagnons_meshcore", {"cles_naturelles": ()}),
    ("CompagnonMeshtastic", "compagnons_meshtastic", {"cles_naturelles": (("node_num",),)}),
    ("RelaisMeshCore", "relais_meshcore", {"cles_naturelles": (("pubkey_hex",),)}),
    ("CanalMeshCore", "canaux_meshcore", {"cles_naturelles": (("equipe",),)}),
    ("CanalMeshtastic", "canaux_meshtastic", {"cles_naturelles": (("equipe",),)}),
    ("ContactMeshCore", "contacts_meshcore", {"cles_naturelles": (("compagnon", "pubkey_hex"),)}),
    ("ContactMeshtastic", "contacts_meshtastic", {"cles_naturelles": (("compagnon", "node_num"),)}),
    ("NoeudMeshUtilisateur", "noeuds_meshcore", {"cles_naturelles": (("pubkey_hex",),)}),
    ("NoeudUtilisateurMeshtastic", "noeuds_meshtastic", {"cles_naturelles": (("node_num",),)}),
)


def _modele(nom):
    return apps.get_model("core", nom)


# ── Côté central : sélection et sérialisation ─────────────────────────────────────────────

def selection(institution, environnement):
    """{clé JSON: queryset} de ce que reçoit un satellite de `institution`."""
    m = _modele
    compagnons_mc = m("CompagnonMeshCore").objects.filter(environment=environnement, institution=institution)
    compagnons_mt = m("CompagnonMeshtastic").objects.filter(environment=environnement, institution=institution)
    return {
        "equipes": m("Team").objects.filter(environment=environnement)
            .filter(Q(institution=institution) | Q(institution_delegataire=institution)).distinct(),
        "compagnons_meshcore": compagnons_mc,
        "compagnons_meshtastic": compagnons_mt,
        "relais_meshcore": m("RelaisMeshCore").objects.filter(environment=environnement)
            .filter(Q(institution=institution) | Q(institution__isnull=True)),
        "canaux_meshcore": m("CanalMeshCore").objects.filter(environment=environnement, institution=institution),
        "canaux_meshtastic": m("CanalMeshtastic").objects.filter(environment=environnement, institution=institution),
        "contacts_meshcore": m("ContactMeshCore").objects.filter(compagnon__in=compagnons_mc),
        "contacts_meshtastic": m("ContactMeshtastic").objects.filter(compagnon__in=compagnons_mt),
        "noeuds_meshcore": m("NoeudMeshUtilisateur").objects.filter(
            environment=environnement, utilisateur__institution=institution),
        "noeuds_meshtastic": m("NoeudUtilisateurMeshtastic").objects.filter(
            environment=environnement, utilisateur__institution=institution),
    }


def _valeur(valeur):
    if isinstance(valeur, GEOSGeometry):
        return valeur.geojson
    if hasattr(valeur, "isoformat"):
        return valeur.isoformat()
    if isinstance(valeur, uuid.UUID):
        return str(valeur)
    return valeur


def construire(objet, options):
    """Tous les champs concrets de l'objet (clés étrangères par identifiant), plus ses M2M."""
    payload = {}
    for champ in objet._meta.concrete_fields:
        payload[champ.attname] = _valeur(getattr(objet, champ.attname))
    for nom in options.get("m2m", ()):
        payload[nom] = [str(i) for i in getattr(objet, nom).values_list("pk", flat=True)]
    for nom, (_cat, cle) in options.get("m2m_catalogue", {}).items():
        payload[nom] = list(getattr(objet, nom).values_list(cle, flat=True))
    return payload


def referentiel_pour_satellite(institution, environnement):
    options = {cle: opts for _nom, cle, opts in SPEC}
    return {
        cle: [construire(objet, options[cle]) for objet in qs]
        for cle, qs in selection(institution, environnement).items()
    }


# ── Côté satellite : application ──────────────────────────────────────────────────────────

def _valeurs_locales(Modele, item):
    """Champs de `item` prêts à écrire localement ; None si une clé étrangère obligatoire vise un
    objet absent du satellite (l'objet entier est alors ignoré)."""
    valeurs = {}
    for champ in Modele._meta.concrete_fields:
        if champ.primary_key or champ.attname not in item:
            continue
        valeur = item[champ.attname]
        if champ.is_relation:
            if valeur is not None and not champ.related_model.objects.filter(pk=valeur).exists():
                valeur = None
            if valeur is None and not champ.null:
                return None
        elif isinstance(champ, GeometryField):
            valeur = GEOSGeometry(valeur) if valeur else None
        valeurs[champ.attname] = valeur
    return valeurs


def _existant(Modele, item, valeurs, options):
    """Ligne locale à mettre à jour : même identifiant, sinon même clé naturelle."""
    objet = Modele.objects.filter(pk=item["id"]).first()
    if objet is not None:
        return objet
    for cle in options.get("cles_naturelles", ()):
        criteres = {}
        for nom in cle:
            attname = Modele._meta.get_field(nom).attname
            if valeurs.get(attname) is None:
                break
            criteres[attname] = valeurs[attname]
        else:
            objet = Modele.objects.filter(**criteres).first()
            if objet is not None:
                return objet
    return None


def _appliquer_un(Modele, item, options):
    valeurs = _valeurs_locales(Modele, item)
    if valeurs is None:
        return "ignore"
    with transaction.atomic():
        existant = _existant(Modele, item, valeurs, options)
        if existant is not None:
            Modele.objects.filter(pk=existant.pk).update(**valeurs)
            pk = existant.pk
        else:
            Modele.objects.bulk_create([Modele(id=item["id"], **valeurs)])
            pk = item["id"]
            # bulk_create applique auto_now_add (date_creation = maintenant) : on remet les
            # dates du central.
            Modele.objects.filter(pk=pk).update(**valeurs)
        if options.get("m2m") or options.get("m2m_catalogue"):
            objet = Modele.objects.get(pk=pk)
            for nom in options.get("m2m", ()):
                cible = Modele._meta.get_field(nom).related_model
                ids = [i for i in item.get(nom, []) if cible.objects.filter(pk=i).exists()]
                getattr(objet, nom).set(ids)
            for nom, (nom_cat, cle) in options.get("m2m_catalogue", {}).items():
                Cat = _modele(nom_cat)
                ids = [Cat.objects.get_or_create(**{cle: v})[0].pk for v in item.get(nom, []) if v]
                getattr(objet, nom).set(ids)
    return "applique"


def appliquer_referentiel(donnees):
    """Applique la partie `referentiel` d'une réponse SatelliteViewSet.donnees. Jamais tout ou
    rien : une ligne en erreur est comptée et n'empêche pas les autres.
    Renvoie {"applique": n, "ignore": n, "erreur": n}."""
    import logging
    logger = logging.getLogger(__name__)

    compteurs = {"applique": 0, "ignore": 0, "erreur": 0}
    for nom_modele, cle, options in SPEC:
        Modele = _modele(nom_modele)
        items = donnees.get(cle) or []
        # Équipes en deux passes : une équipe peut citer comme parente une équipe qui arrive
        # après elle dans la liste.
        passes = 2 if nom_modele == "Team" else 1
        for passe in range(passes):
            for item in items:
                try:
                    resultat = _appliquer_un(Modele, item, options)
                except Exception:
                    logger.exception("Échec application référentiel %s %s", nom_modele, item.get("id"))
                    resultat = "erreur"
                if passe == passes - 1:
                    compteurs[resultat] += 1
    return compteurs
