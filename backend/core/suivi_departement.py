"""Suivi départemental (21/11/2026) : pour un comité départemental, l'état de chaque
intercommunalité et de chaque commune — l'enrôlement sur la plateforme, et la préparation du
plan (PCS pour une commune, PICS pour une intercommunalité).

L'avancement d'un plan, c'est la part des parties du document qui n'ont plus rien à compléter
(`document_pcs.PARTIES`, mêmes vérifications que l'encadré « Ce qui reste à compléter »).
Calculé à la demande, intercommunalité par intercommunalité : `rassembler` lit une dizaine de
tables par institution, le faire pour tout un département d'un coup prendrait des dizaines de
secondes.
"""


def avancement(institution, environment) -> dict:
    from . import document_pcs
    from .models import DossierPCS

    contenu = document_pcs.rassembler(institution, environment)
    restantes = []
    for m in contenu.get("manques", []):
        if m["partie"] not in restantes:
            restantes.append(m["partie"])
    total = len(document_pcs.PARTIES)
    faites = total - len([p for p in restantes if p in document_pcs.PARTIES])
    dossier = DossierPCS.objects.filter(institution=institution, environment=environment).first()
    return {
        "parties_faites": faites, "parties_total": total,
        "pourcentage": round(100 * faites / total) if total else 0,
        "restantes": restantes,
        "arrete_date": dossier.arrete_date if dossier else None,
        "date_maj": dossier.date_maj if dossier else None,
    }


def enrolement(fiche: dict | None) -> str:
    """Où en est la collectivité sur la plateforme."""
    if fiche is None:
        return "non_creee"
    if fiche.get("membres"):
        return "a_rejoint"
    if fiche.get("invitee_le"):
        return "invitee"
    if not fiche.get("email") and not (fiche.get("referent") or {}).get("email"):
        return "pas_d_adresse"
    return "non_invitee"
