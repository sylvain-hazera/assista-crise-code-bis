"""Canal radio et indicatif de chaque équipe (25/11/2026).

Demande de Sylvain : « chaque équipe doit avoir son canal d'équipe, son indicatif, créé par
défaut » ; « les canaux d'équipes doivent pouvoir être personnalisés (les ADRASEC ont souvent
déjà leurs canaux) », avec leur propre clé, ou en reprenant un canal déjà installé sur la
passerelle de l'entité.

- **Indicatif** : proposé depuis le nom à la création, unique dans l'environnement.
- **Canal par défaut** : `AC-<INDICATIF>`, un par protocole (Meshtastic et MeshCore), clé
  aléatoire de 16 octets, chiffrée au repos. Il vit sur les radios des membres (l'application
  l'installe) ; il ne prend **pas** d'emplacement sur les radios des passerelles
  (`sur_passerelle` faux), qui le lisent en décodage logiciel.
- **Personnalisé** : nom choisi, clé de la structure (`cle_fournie`, jamais régénérée par la
  plateforme) ou générée ; ou **repris** d'une passerelle de l'institution de l'équipe.

La clé ne sort que vers les radios des membres (`canaux_pour_membre`) et les ponts ; jamais dans
la liste des équipes ni dans un journal. Les noms de canaux et les indicatifs sont publics par
nature (ils passent en clair sur l'air) : on peut filtrer dessus en SQL.
"""
import base64
import hashlib
import re
import secrets
import unicodedata

from django.db import transaction

MESHTASTIC = "MESHTASTIC"
MESHCORE = "MESHCORE"
PROTOCOLES = (MESHTASTIC, MESHCORE)
PREFIXE = "AC-"
NOM_MESHTASTIC_MAX = 11   # octets, limite du firmware (ChannelSettings.name)
NOM_MESHCORE_MAX = 31


class CanalInvalide(ValueError):
    """Saisie refusée : le message est montré tel quel à l'utilisateur."""


# ══ Indicatif ═════════════════════════════════════════════════════════════════

def indicatifs_pris(equipe):
    from .models import Team
    from .routage_canaux import ADRESSES_CELLULE

    pris = {(i or "").upper() for i in Team.objects.filter(environment=equipe.environment)
            .exclude(pk=equipe.pk).exclude(indicatif="").values_list("indicatif", flat=True)}
    return pris | ADRESSES_CELLULE


def equipe_de_l_indicatif(equipe, indicatif):
    """L'autre équipe de l'environnement qui porte déjà cet indicatif, ou None."""
    from .models import Team

    if not indicatif:
        return None
    return Team.objects.filter(environment=equipe.environment, indicatif__iexact=indicatif).exclude(pk=equipe.pk).first()


def assurer_indicatif(equipe):
    """Donne un indicatif à l'équipe qui n'en a pas (sans repasser par save : pas de signal)."""
    from .models import Team
    from .routage_canaux import proposer_indicatif

    if equipe.indicatif:
        return equipe.indicatif
    equipe.indicatif = proposer_indicatif(equipe.name, indicatifs_pris(equipe))
    Team.objects.filter(pk=equipe.pk).update(indicatif=equipe.indicatif)
    return equipe.indicatif


# ══ Canal par défaut ══════════════════════════════════════════════════════════

def _nom_radio(nom, maximum):
    ascii_ = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode()
    compact = "".join(ch for ch in ascii_ if ch.isalnum() or ch in "-_")
    return compact[:maximum]


def nom_par_defaut(equipe):
    return _nom_radio(PREFIXE + (equipe.indicatif or "EQ"), NOM_MESHTASTIC_MAX)


def modele(protocole):
    from .models import CanalMeshCore, CanalMeshtastic

    if protocole == MESHTASTIC:
        return CanalMeshtastic
    if protocole == MESHCORE:
        return CanalMeshCore
    raise CanalInvalide("Protocole inconnu : MESHTASTIC ou MESHCORE.")


def canal_de(equipe, protocole):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return getattr(equipe, "canal_meshtastic" if protocole == MESHTASTIC else "canal_meshcore")
    except ObjectDoesNotExist:
        return None


def cle(canal):
    """La clé du canal en hexadécimal, quel que soit le protocole."""
    from .models import CanalMeshtastic

    return (canal.psk_hex if isinstance(canal, CanalMeshtastic) else canal.cle_partagee_hex) or ""


def _creer_par_defaut(equipe, protocole):
    champs = dict(equipe=equipe, institution=equipe.institution, nom=nom_par_defaut(equipe),
                  actif=equipe.actif, environment=equipe.environment)
    if protocole == MESHTASTIC:
        champs["psk_hex"] = secrets.token_hex(16)
    else:
        champs["cle_partagee_hex"] = secrets.token_hex(16)
    return modele(protocole).objects.create(**champs)


def assurer_canaux(equipe):
    """Crée les canaux manquants ; un canal par défaut suit l'indicatif et l'état de l'équipe."""
    for protocole in PROTOCOLES:
        canal = canal_de(equipe, protocole)
        if canal is None:
            _creer_par_defaut(equipe, protocole)
            continue
        if canal.personnalise:
            continue
        maj = {}
        if canal.nom != nom_par_defaut(equipe):
            maj["nom"] = nom_par_defaut(equipe)
        if canal.actif != equipe.actif:
            maj["actif"] = equipe.actif
        if maj:
            type(canal).objects.filter(pk=canal.pk).update(**maj)
            for k, v in maj.items():
                setattr(canal, k, v)


def equipe_enregistree(sender, instance, raw=False, **kwargs):
    """Signal post_save de Team : indicatif et canaux par défaut, dès la création."""
    from django.conf import settings

    if raw or not getattr(settings, "CANAUX_EQUIPE_AUTO", True):
        return
    try:
        with transaction.atomic():
            assurer_indicatif(instance)
            assurer_canaux(instance)
    except Exception:   # ne jamais empêcher l'enregistrement d'une équipe
        import logging
        logging.getLogger(__name__).exception("Canal radio de l'équipe %s non créé", instance.pk)


# ══ Clés saisies ══════════════════════════════════════════════════════════════

def _varint(donnees, i):
    valeur, decalage = 0, 0
    while True:
        if i >= len(donnees):
            raise CanalInvalide("Lien de canal Meshtastic illisible.")
        octet = donnees[i]
        i += 1
        valeur |= (octet & 0x7F) << decalage
        if not octet & 0x80:
            return valeur, i
        decalage += 7


def _champs_protobuf(donnees):
    """(numéro, valeur) des champs d'un message protobuf : varints et octets seulement."""
    i = 0
    while i < len(donnees):
        entete, i = _varint(donnees, i)
        numero, genre = entete >> 3, entete & 7
        if genre == 0:
            valeur, i = _varint(donnees, i)
        elif genre == 2:
            longueur, i = _varint(donnees, i)
            valeur, i = donnees[i:i + longueur], i + longueur
        elif genre == 5:
            valeur, i = donnees[i:i + 4], i + 4
        elif genre == 1:
            valeur, i = donnees[i:i + 8], i + 8
        else:
            raise CanalInvalide("Lien de canal Meshtastic illisible.")
        yield numero, valeur


def _b64(texte):
    texte = texte.strip().replace("-", "+").replace("_", "/")
    texte += "=" * (-len(texte) % 4)
    try:
        return base64.b64decode(texte, validate=True)
    except Exception:
        raise CanalInvalide("Clé illisible : base64, hexadécimal ou lien de canal Meshtastic.")


def lire_lien_meshtastic(lien):
    """Lien « https://meshtastic.org/e/#… » (ChannelSet) → [(nom, clé en octets)]."""
    fragment = lien.split("#", 1)[1] if "#" in lien else lien
    canaux = []
    for numero, valeur in _champs_protobuf(_b64(fragment)):
        if numero == 1 and isinstance(valeur, (bytes, bytearray)):   # ChannelSettings
            nom, psk = "", b""
            for n, v in _champs_protobuf(bytes(valeur)):
                if n == 2:
                    psk = bytes(v)
                elif n == 3:
                    nom = bytes(v).decode("utf-8", "replace")
            canaux.append((nom, psk))
    if not canaux:
        raise CanalInvalide("Ce lien ne contient aucun canal Meshtastic.")
    return canaux


def lire_cle(protocole, texte, *, en_clair=False):
    """Clé saisie (hexadécimal, base64, ou lien Meshtastic) → (hex, nom du lien ou None)."""
    texte = (texte or "").strip()
    nom_lien = None
    if "meshtastic.org/e/" in texte or texte.startswith("#") and protocole == MESHTASTIC:
        nom_lien, octets = lire_lien_meshtastic(texte)[0]
    elif re.fullmatch(r"(?:[0-9a-fA-F]{2})+", texte) and len(texte) in (32, 64):
        octets = bytes.fromhex(texte)
    else:
        octets = _b64(texte)
    if protocole == MESHTASTIC:
        if len(octets) in (16, 32):
            pass
        elif len(octets) <= 1:
            if not en_clair:
                raise CanalInvalide("Cette clé est la clé publique par défaut : le canal serait lisible par "
                                    "tous. Cochez « canal en clair » si c'est voulu.")
        else:
            raise CanalInvalide("Une clé Meshtastic fait 16 ou 32 octets (24 ou 44 caractères en base64).")
    elif len(octets) != 16:
        raise CanalInvalide("Une clé MeshCore fait 16 octets (32 caractères hexadécimaux).")
    return octets.hex(), nom_lien


def empreinte(cle_hex):
    """Empreinte courte d'une clé, pour vérifier qu'elle concorde sans la montrer."""
    if not cle_hex:
        return ""
    return hashlib.sha256(bytes.fromhex(cle_hex) if re.fullmatch(r"[0-9a-fA-F]*", cle_hex) else cle_hex.encode()).hexdigest()[:8].upper()


def version(canal):
    return hashlib.sha256(f"{canal.nom}|{cle(canal)}".encode()).hexdigest()[:12] if canal else ""


# ══ Personnaliser, reprendre, revenir au défaut ═══════════════════════════════

def _normaliser(nom):
    return (nom or "").strip().lstrip("#").lower()


def _verifier_nom_libre(equipe, protocole, nom, exclure=None):
    for autre in modele(protocole).objects.filter(environment=equipe.environment, actif=True,
                                                  equipe__isnull=False, nom__iendswith=_normaliser(nom)):
        if _normaliser(autre.nom) == _normaliser(nom) and autre.pk != getattr(exclure, "pk", None) \
                and autre.equipe_id != equipe.pk:
            raise CanalInvalide(f"Le canal « {autre.nom} » est déjà celui d'une autre équipe.")


def _nom_saisi(protocole, nom):
    nom = (nom or "").strip()
    if protocole == MESHTASTIC:
        propre = _nom_radio(nom, NOM_MESHTASTIC_MAX)
        if not propre:
            raise CanalInvalide("Nom de canal vide (lettres, chiffres, - et _ ; 11 caractères au plus).")
        if propre != nom:
            raise CanalInvalide(f"Sur Meshtastic, le nom doit tenir en 11 caractères sans espace ni accent "
                                f"(par exemple « {propre} »).")
        return propre
    if not nom or len(nom.encode("utf-8")) > NOM_MESHCORE_MAX:
        raise CanalInvalide("Nom de canal MeshCore : 1 à 31 caractères.")
    return nom


def _liberer(equipe, protocole, garder=None):
    """Retire à l'équipe son canal actuel : un canal repris est rendu à l'entité, un canal
    à elle est supprimé (sa clé ne sert plus à rien)."""
    canal = canal_de(equipe, protocole)
    if canal is None or canal == garder:
        return
    if canal.repris:
        type(canal).objects.filter(pk=canal.pk).update(equipe=None, personnalise=False, repris=False)
    else:
        canal.delete()
    _oublier_cache(equipe, protocole)


def _oublier_cache(equipe, protocole):
    champ = "canal_meshtastic" if protocole == MESHTASTIC else "canal_meshcore"
    try:
        equipe._state.fields_cache.pop(champ, None)
    except AttributeError:
        pass


@transaction.atomic
def personnaliser(equipe, protocole, nom, cle_saisie=None, *, en_clair=False):
    """Nom choisi ; clé de la structure si fournie, sinon clé générée (ou dérivée pour un
    canal MeshCore public « #nom »)."""
    nom = _nom_saisi(protocole, nom)
    cle_hex, fournie = None, False
    if cle_saisie:
        cle_hex, _nom_lien = lire_cle(protocole, cle_saisie, en_clair=en_clair)
        fournie = True
    elif protocole == MESHCORE and nom.startswith("#"):
        from .models import CanalMeshCore
        cle_hex, fournie = CanalMeshCore.derive_cle_publique(nom), True
    else:
        cle_hex = secrets.token_hex(16)
    _verifier_nom_libre(equipe, protocole, nom, exclure=canal_de(equipe, protocole))

    canal = canal_de(equipe, protocole)
    if canal is not None and canal.repris:
        _liberer(equipe, protocole)
        canal = None
    if canal is None:
        canal = _creer_par_defaut(equipe, protocole)
    elif protocole == MESHCORE:
        _retirer_des_passerelles(canal)
    canal.nom = nom
    canal.personnalise = True
    canal.cle_fournie = fournie
    canal.actif = True
    if protocole == MESHTASTIC:
        canal.psk_hex = cle_hex
        canal.save(update_fields=["nom", "personnalise", "cle_fournie", "actif", "psk_hex"])
    else:
        canal.cle_partagee_hex = cle_hex
        canal.save(update_fields=["nom", "personnalise", "cle_fournie", "actif", "cle_partagee_hex"])
    return canal


def _retirer_des_passerelles(canal):
    """La clé ou le nom change : les emplacements des passerelles ne valent plus rien."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import CanalMeshCoreObsolete

    for provision in canal.provisions.all():
        CanalMeshCoreObsolete.objects.create(
            canal=canal, compagnon_id=provision.compagnon_id, canal_idx=provision.canal_idx,
            supprimer_apres=timezone.now() + timedelta(hours=48), environment=canal.environment)
    canal.provisions.all().delete()


def _sur_passerelles_de(institution_id, protocole):
    """Les canaux installés sur une passerelle de l'institution, clé connue."""
    from .canaux_locaux import CANAUX_COMMUNAUTAIRES, PSK_PUBLIQUE
    from .models import CanalMeshCore, CanalMeshtastic

    communautaires = {c.lower() for c in CANAUX_COMMUNAUTAIRES}
    if protocole == MESHTASTIC:
        candidats = CanalMeshtastic.objects.filter(actif=True, crise__isnull=True,
                                                   compagnon__institution_id=institution_id).select_related("compagnon")
    else:
        candidats = CanalMeshCore.objects.filter(actif=True, crise__isnull=True,
                                                 provisions__compagnon__institution_id=institution_id).distinct()
    resultat = []
    for canal in candidats:
        cle_hex = cle(canal)
        if not cle_hex or _normaliser(canal.nom) in communautaires or _normaliser(canal.nom) == "public":
            continue
        if cle_hex in (PSK_PUBLIQUE, CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT):
            continue
        resultat.append(canal)
    return resultat


def canaux_passerelle(equipe):
    """Ce qu'on peut reprendre, par protocole : jamais la clé."""
    from .models import CanalMeshCoreDetecte

    if not equipe.institution_id:
        return {"canaux": [], "entendus_sans_cle": 0}
    canaux = []
    for protocole in PROTOCOLES:
        for canal in _sur_passerelles_de(equipe.institution_id, protocole):
            if canal.equipe_id and canal.equipe_id != equipe.pk:
                continue
            if protocole == MESHTASTIC:
                passerelle = canal.compagnon.nom if canal.compagnon_id else ""
            else:
                p = canal.provisions.select_related("compagnon").filter(compagnon__institution_id=equipe.institution_id).first()
                passerelle = p.compagnon.nom if p else ""
            canaux.append({
                "id": str(canal.pk), "protocole": protocole, "nom": canal.nom, "passerelle": passerelle,
                "public": protocole == MESHCORE and canal.nom.startswith("#"),
                "deja_le_notre": canal.equipe_id == equipe.pk,
                "empreinte": empreinte(cle(canal)),
            })
    entendus = CanalMeshCoreDetecte.objects.filter(compagnon__institution_id=equipe.institution_id).count()
    return {"canaux": canaux, "entendus_sans_cle": entendus}


@transaction.atomic
def reprendre(equipe, protocole, canal_id):
    """Le canal de la passerelle de l'entité devient celui de l'équipe."""
    canal = next((c for c in _sur_passerelles_de(equipe.institution_id, protocole) if str(c.pk) == str(canal_id)), None) \
        if equipe.institution_id else None
    if canal is None:
        raise CanalInvalide("Ce canal n'est pas sur une passerelle de votre structure.")
    if canal.equipe_id and canal.equipe_id != equipe.pk:
        raise CanalInvalide("Ce canal est déjà celui d'une autre équipe.")
    if canal.equipe_id == equipe.pk:
        return canal
    _liberer(equipe, protocole)
    champs = dict(equipe=equipe, personnalise=True, cle_fournie=True, repris=True)
    if protocole == MESHCORE:
        champs["sur_passerelle"] = True
    type(canal).objects.filter(pk=canal.pk).update(**champs)
    canal.refresh_from_db()
    _oublier_cache(equipe, protocole)
    return canal


@transaction.atomic
def revenir_au_defaut(equipe, protocole):
    _liberer(equipe, protocole)
    return _creer_par_defaut(equipe, protocole)


# ══ Ce que voient le site et l'application ════════════════════════════════════

def etat(equipe):
    """Pour la fiche équipe du site : jamais la clé."""
    sortie = {}
    for protocole in PROTOCOLES:
        canal = canal_de(equipe, protocole)
        sortie[protocole.lower()] = None if canal is None else {
            "nom": canal.nom, "personnalise": canal.personnalise, "cle_fournie": canal.cle_fournie,
            "repris": canal.repris, "empreinte": empreinte(cle(canal)), "actif": canal.actif,
            "sur_passerelle": bool(getattr(canal, "sur_passerelle", False) or getattr(canal, "compagnon_id", None)),
        }
    return sortie


def canaux_pour_membre(utilisateur, environnement):
    """Les canaux des équipes actives de l'utilisateur, AVEC leurs clés : pour sa radio."""
    from django.db.models import Q

    from .models import Team

    equipes = Team.objects.filter(environment=environnement, actif=True).filter(
        Q(members=utilisateur) | Q(leader=utilisateur) | Q(regulateur=utilisateur)).distinct()
    sortie = []
    for equipe in equipes:
        mt, mc = canal_de(equipe, MESHTASTIC), canal_de(equipe, MESHCORE)
        mt = mt if mt is not None and mt.actif else None
        mc = mc if mc is not None and mc.actif else None
        sortie.append({
            "equipe": str(equipe.pk), "nom_equipe": equipe.name, "indicatif": equipe.indicatif,
            "meshtastic": {"nom": mt.nom, "psk_hex": mt.psk_hex or "", "version": version(mt)} if mt else None,
            "meshcore": {"nom": mc.nom, "cle_hex": mc.cle_partagee_hex or "", "version": version(mc)} if mc else None,
        })
    return sortie


# ══ Plan d'urgence : emplacements 5, 6, 7 (25/11/2026) ════════════════════════
#
# Vision d'Olivier F4GLD et de Sylvain : sur la radio d'un intervenant, les emplacements 5, 6 et
# 7 servent en cas d'urgence — 5 = canal de la crise, 6 = canal de l'équipe, 7 = canal de la
# commune. L'application les propose (modifiables), sauvegarde ce qu'elle remplace et le
# restaure en fin de crise ; un canal déjà présent ailleurs sur la radio est utilisé tel quel.

ROLES_URGENCE = ("crise", "equipe", "commune")


def _canal_commune_meshcore(institution):
    from .models import CanalMeshCore

    return CanalMeshCore.objects.filter(institution=institution, crise__isnull=True, equipe__isnull=True,
                                        actif=True, nom__startswith="#").order_by("date_creation").first()


def plan_urgence(equipe, environnement):
    """Par protocole, les canaux à mettre en 5, 6, 7, avec leurs clés (hex)."""
    from .canaux_locaux import canal_commune, canaux_de_crise
    from .salons_de_crise import crise_du_contexte

    crise = crise_du_contexte(equipe)
    mt_crise = mc_crise = None
    if crise is not None:
        mt_crise, mc_crise = canaux_de_crise(crise, environnement)
    mt_commune = mc_commune = None
    if equipe.institution_id:
        mt_commune = canal_commune(equipe.institution, environnement)[0]
        mc_commune = _canal_commune_meshcore(equipe.institution)
    mt_equipe, mc_equipe = canal_de(equipe, MESHTASTIC), canal_de(equipe, MESHCORE)

    def entree(role, canal):
        if canal is None or not canal.actif:
            return None
        return {"role": role, "nom": canal.nom, "cle_hex": cle(canal), "version": version(canal)}

    meshtastic = [e for e in (entree("crise", mt_crise), entree("equipe", mt_equipe), entree("commune", mt_commune)) if e]
    meshcore = [e for e in (entree("crise", mc_crise), entree("equipe", mc_equipe), entree("commune", mc_commune)) if e]
    empreinte_plan = hashlib.sha256(repr((meshtastic, meshcore)).encode()).hexdigest()[:12]
    return {
        "equipe": str(equipe.pk), "nom_equipe": equipe.name, "indicatif": equipe.indicatif,
        "crise": str(crise.pk) if crise else None, "nom_crise": crise.name if crise else None,
        "version": empreinte_plan, "meshtastic": meshtastic, "meshcore": meshcore,
    }


# ══ Lien de canal Meshtastic (QR code) ════════════════════════════════════════

def _varint_octets(valeur):
    sortie = bytearray()
    while valeur >= 0x80:
        sortie.append((valeur & 0x7F) | 0x80)
        valeur >>= 7
    sortie.append(valeur)
    return bytes(sortie)


def _champ_octets(numero, donnees):
    return _varint_octets((numero << 3) | 2) + _varint_octets(len(donnees)) + donnees


def lien_meshtastic(canaux, ajouter=True):
    """[(nom, clé hex)] → lien « https://meshtastic.org/e/#… » (ChannelSet), lisible par
    l'application Meshtastic officielle. `ajouter` : mode « ajouter », qui n'efface pas les
    canaux de la radio de l'intervenant."""
    corps = b""
    for nom, cle_hex in canaux:
        reglages = b""
        if cle_hex:
            reglages += _champ_octets(2, bytes.fromhex(cle_hex))
        reglages += _champ_octets(3, nom.encode("utf-8"))
        corps += _champ_octets(1, reglages)
    fragment = base64.urlsafe_b64encode(corps).decode().rstrip("=")
    return "https://meshtastic.org/e/" + ("?add=true" if ajouter else "") + "#" + fragment
