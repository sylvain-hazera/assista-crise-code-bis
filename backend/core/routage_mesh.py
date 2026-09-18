"""Sélection du meilleur companion MeshCore pour joindre un contact donné — voir la discussion
du 2026-09-18 sur les régions/ACL MeshCore en France.

Clarification actée à cette occasion (recherchée, pas supposée) : MeshCore n'a AUCUNE notion
protocolaire de région. L'« ACL » du firmware est une table de permissions par infrastructure
(répéteur/room server/capteur — qui a le droit de l'administrer), sans aucun rapport avec la
géographie. Les « régions » françaises (ex. `#fr-naq` pour la Nouvelle-Aquitaine) sont une pure
convention communautaire de nom de canal, non appliquée par le firmware — voir
`CompagnonMeshCore.region_tag`/`ContactMeshCore.region_tag`, deux étiquettes texte libres,
posées à la main par un administrateur.

Ordre de préférence, du plus fiable au plus incertain :
  1. Un companion qui a RÉELLEMENT entendu ce contact (un `ContactMeshCore` existe pour ce
     pubkey_hex) — à recense égale, celui avec le MOINS de sauts connus
     (`nombre_sauts`, voir sa docstring : reflète `out_path_len` de la lib meshcore, capturé par
     `meshcore-bridge/bridge.py:boucle_contacts`), puis le contact le plus RÉCEMMENT entendu.
  2. À défaut de contact direct connu, un companion dont `region_tag` correspond à la région
     demandée — on émettra alors "à l'aveugle" (canal régional plutôt qu'un DM ciblé, à la
     charge de l'appelant : ce module ne décide que DU COMPAGNON, pas du mode d'envoi).
  3. À défaut, le companion `principal=True` de l'institution.
  4. À défaut, n'importe quel companion actif.

Jamais un choix totalement opaque : le résultat porte toujours une `raison` explicite,
affichée côté frontend pour que l'utilisateur comprenne le choix fait à sa place (et puisse le
forcer autrement, voir MessageMeshLogSerializer — le champ `compagnon` reste overridable)."""
from django.db.models import F

from .models import CompagnonMeshCore, ContactMeshCore


class ResultatSelectionCompagnon:
    def __init__(self, compagnon, raison, region_tag=None):
        self.compagnon = compagnon
        self.raison = raison
        self.region_tag = region_tag

    def as_dict(self):
        return {
            "compagnon_id": str(self.compagnon.id) if self.compagnon else None,
            "compagnon_nom": self.compagnon.nom if self.compagnon else None,
            "raison": self.raison,
            "region_tag": self.region_tag,
        }


def meilleur_compagnon_pour_contact(pubkey_hex=None, region_tag=None, institution=None, environment=None):
    """`institution`/`environment` restreignent la recherche (jamais choisir le companion d'une
    autre institution) — omis (None) pour une recherche non restreinte (ex. compte
    administrateur global). Renvoie toujours un `ResultatSelectionCompagnon`, dont
    `.compagnon` peut être None si aucun companion actif n'existe du tout."""
    compagnons_eligibles = CompagnonMeshCore.objects.filter(actif=True)
    if institution is not None:
        compagnons_eligibles = compagnons_eligibles.filter(institution=institution)
    if environment is not None:
        compagnons_eligibles = compagnons_eligibles.filter(environment=environment)

    if pubkey_hex:
        meilleur_contact = (
            ContactMeshCore.objects
            .filter(pubkey_hex=pubkey_hex, compagnon__in=compagnons_eligibles)
            .select_related('compagnon')
            .order_by(F('nombre_sauts').asc(nulls_last=True), '-dernier_advert')
            .first()
        )
        if meilleur_contact is not None:
            if meilleur_contact.nombre_sauts is not None:
                raison = f"contact déjà entendu via ce companion ({meilleur_contact.nombre_sauts} saut(s) connu(s))"
            else:
                raison = "contact déjà entendu via ce companion (chemin non confirmé)"
            return ResultatSelectionCompagnon(
                meilleur_contact.compagnon, raison, meilleur_contact.region_tag or None
            )

    if region_tag:
        compagnon_region = compagnons_eligibles.filter(region_tag=region_tag).order_by('-principal').first()
        if compagnon_region is not None:
            return ResultatSelectionCompagnon(
                compagnon_region, f"aucun contact direct connu — companion couvrant la région {region_tag}", region_tag,
            )

    compagnon_principal = compagnons_eligibles.filter(principal=True).first()
    if compagnon_principal is not None:
        return ResultatSelectionCompagnon(compagnon_principal, "companion principal (aucun contact ni région connus)")

    compagnon_quelconque = compagnons_eligibles.first()
    if compagnon_quelconque is not None:
        return ResultatSelectionCompagnon(compagnon_quelconque, "aucun companion principal — premier companion actif disponible")

    return ResultatSelectionCompagnon(None, "aucun companion actif disponible")
