"""Revue des droits des contacts d'une institution et de ses filles (23/11/2026).

Demande de Sylvain : « une matrice des rôles des contacts d'une institution et de ses filles,
permettant aussi la revue des droits ». Les droits d'une personne étaient répartis en sept
endroits (type de compte, institution de travail, rôles opérationnels, bureau, encadrement
d'équipe, habilitation au registre et engagement au secret, accès à la formation) ; aucun
écran ne les réunissait.

**La matrice** : une ligne par fiche de contact, toutes les colonnes de droits, et les
anomalies relevées. **La revue** : pour chaque fiche, confirmer, ou retirer un droit (bureau,
rôle opérationnel, fiche de l'institution) -- daté, signé, journalisé (`RevueDroits` et la main
courante). Une fiche se revoit tous les six mois ; un compte sans connexion depuis 90 jours
qui garde des droits est signalé.

**Ce que la revue ne touche pas** : l'habilitation au registre des personnes vulnérables, qui
est un acte nominatif du maire avec sa propre page (« Habilitations registre ») -- la matrice
la montre et y renvoie, elle ne la retire pas.

**Qui fait la revue** : un administrateur ; le bureau ou le contact principal de l'institution
(ou de sa mère : une mairie répond de sa réserve et de son CCAS) ; une personne qui y tient un
rôle de responsable (Responsable, RAC, DOS).

Les noms des personnes sont chiffrés en base : ils sont lus et triés ici, en mémoire, jamais
filtrés par une requête SQL.
"""
import datetime

from django.utils import timezone

PERIODE_REVUE = datetime.timedelta(days=183)          # six mois
SEUIL_INACTIVITE = datetime.timedelta(days=90)
ROLES_RESPONSABLES = {"RESPONSABLE", "RAC", "DOS"}

ANOMALIES = {
    "INACTIF_AVEC_DROITS": "Aucune connexion depuis plus de 90 jours, des droits conservés",
    "JAMAIS_CONNECTE": "Ne s'est jamais connecté",
    "HABILITATION_SANS_ENGAGEMENT": "Habilité au registre sans avoir signé l'engagement au secret",
    "COMPTE_DESACTIVE": "Compte désactivé, fiche de contact encore active",
    "FICHE_INACTIVE_EN_EQUIPE": "Retiré de l'institution, encore membre d'une de ses équipes",
    "REVUE_ECHUE": "Pas revu depuis plus de six mois",
    "JAMAIS_REVU": "Jamais revu",
}


def _environnements(request):
    from .models import Environment
    from .permissions import get_active_environment
    return [Environment.PROD, Environment.DEMO] if get_active_environment(request) == Environment.DEMO else [Environment.PROD]


def peut_revoir(user, institution) -> bool:
    from .models import AffectationRoleOperationnel, ContactInstitution, UserRole

    if not getattr(user, "is_authenticated", False) or institution is None:
        return False
    if user.type == UserRole.ADMINISTRATOR:
        return True
    cibles = [institution.id] + ([institution.institution_parente_id] if institution.institution_parente_id else [])
    if ContactInstitution.objects.filter(institution_id__in=cibles, utilisateur=user, actif=True).filter(
            membre_bureau=True).exists() or ContactInstitution.objects.filter(
            institution_id__in=cibles, utilisateur=user, actif=True, contact_principal=True).exists():
        return True
    return AffectationRoleOperationnel.objects.filter(
        institution_id__in=cibles, utilisateur=user, actif=True, role__code__in=ROLES_RESPONSABLES).exists()


def institutions_revisables(user):
    """Les institutions dont ce compte peut faire la revue (hors administrateur : toutes)."""
    from .models import AffectationRoleOperationnel, ContactInstitution
    from .perimetre_admin import institutions_descendantes

    meres = set(ContactInstitution.objects.filter(utilisateur=user, actif=True).filter(
        membre_bureau=True).values_list("institution_id", flat=True))
    meres |= set(ContactInstitution.objects.filter(utilisateur=user, actif=True, contact_principal=True)
                 .values_list("institution_id", flat=True))
    meres |= set(AffectationRoleOperationnel.objects.filter(utilisateur=user, actif=True, role__code__in=ROLES_RESPONSABLES)
                 .values_list("institution_id", flat=True))
    return institutions_descendantes(meres)


def _nom(u):
    return (f"{u.first_name} {u.last_name}".strip() or u.username or "") if u else ""


def matrice(request, institution):
    """{institution, institutions, lignes, resume} pour l'institution et toutes ses filles."""
    from .models import (
        AffectationRoleOperationnel, ContactInstitution, HabilitationRegistreVulnerables, Institution,
        RevueDroits, Team,
    )
    from .perimetre_admin import institutions_descendantes

    maintenant = timezone.now()
    envs = _environnements(request)
    ids = institutions_descendantes([institution.id])
    institutions = {i.id: i for i in Institution.objects.filter(id__in=ids).select_related("type")}
    contacts = list(ContactInstitution.objects.filter(institution_id__in=ids, environment__in=envs)
                    .select_related("utilisateur", "utilisateur__institution", "institution"))
    utilisateurs = {c.utilisateur_id for c in contacts if c.utilisateur_id}

    roles = {}
    for a in AffectationRoleOperationnel.objects.filter(institution_id__in=ids, utilisateur_id__in=utilisateurs, actif=True).select_related("role"):
        roles.setdefault((a.utilisateur_id, a.institution_id), []).append({"id": str(a.id), "code": a.role.code, "libelle": a.role.libelle})
    habilitations = {}
    for h in HabilitationRegistreVulnerables.objects.filter(utilisateur_id__in=utilisateurs, actif=True):
        habilitations.setdefault(h.utilisateur_id, []).append(h.institution_id)
    equipes = list(Team.objects.filter(institution_id__in=ids).prefetch_related("members", "membres_encadrement"))
    dans_equipes, encadre = {}, {}
    for t in equipes:
        for m in t.members.all():
            dans_equipes.setdefault((m.id, t.institution_id), []).append(t.name)
        for m in t.membres_encadrement.all():
            encadre.setdefault(m.id, []).append(t.name)
    dernieres = {}
    for r in RevueDroits.objects.filter(contact__in=contacts).select_related("revu_par").order_by("revu_le"):
        dernieres[r.contact_id] = r          # la plus récente l'emporte

    lignes = []
    for c in contacts:
        u = c.utilisateur
        if u is None:
            continue
        ses_roles = roles.get((u.id, c.institution_id), [])
        ses_equipes = dans_equipes.get((u.id, c.institution_id), [])
        habilite = c.institution_id in habilitations.get(u.id, []) or (
            institutions[c.institution_id].institution_parente_id in habilitations.get(u.id, []))
        a_des_droits = c.actif and (c.membre_bureau or c.contact_principal or ses_roles or habilite
                                    or u.type in ("AUT_LOCALE", "ADMIN"))
        anomalies = []
        if u.last_login is None:
            anomalies.append("JAMAIS_CONNECTE")
        elif a_des_droits and maintenant - u.last_login > SEUIL_INACTIVITE:
            anomalies.append("INACTIF_AVEC_DROITS")
        if habilite and not u.engagement_secret_registre_le:
            anomalies.append("HABILITATION_SANS_ENGAGEMENT")
        if not u.is_active and c.actif:
            anomalies.append("COMPTE_DESACTIVE")
        if not c.actif and ses_equipes:
            anomalies.append("FICHE_INACTIVE_EN_EQUIPE")
        revue = dernieres.get(c.id)
        if c.actif:
            if revue is None:
                anomalies.append("JAMAIS_REVU")
            elif maintenant - revue.revu_le > PERIODE_REVUE:
                anomalies.append("REVUE_ECHUE")
        inst = institutions[c.institution_id]
        lignes.append({
            "contact": str(c.id), "utilisateur": str(u.id), "nom": _nom(u), "email": u.email or "",
            "institution": str(inst.id), "institution_nom": inst.nom_affichage or inst.nom or "",
            "fonction": c.fonction or "", "actif": c.actif, "contact_principal": c.contact_principal,
            "membre_bureau": c.membre_bureau, "type_compte": u.type, "type_compte_libelle": u.get_type_display(),
            "institution_travail": (u.institution.nom_affichage or u.institution.nom) if u.institution_id else "",
            "roles": ses_roles, "equipes": sorted(ses_equipes), "encadre": sorted(encadre.get(u.id, [])),
            "habilite_registre": habilite, "engagement_signe": bool(u.engagement_secret_registre_le),
            "acces_formation": bool(u.demo_role), "compte_actif": u.is_active,
            "derniere_connexion": u.last_login.isoformat() if u.last_login else None,
            "derniere_revue": ({"le": revue.revu_le.isoformat(), "par": _nom(revue.revu_par),
                                "decision": revue.get_decision_display()} if revue else None),
            "anomalies": [{"code": a, "libelle": ANOMALIES[a]} for a in anomalies],
        })
    lignes.sort(key=lambda l: (l["institution_nom"].lower(), not l["actif"], l["nom"].lower()))

    actives = [l for l in lignes if l["actif"]]
    revues = [l for l in actives if l["derniere_revue"]]
    plus_ancienne = min((l["derniere_revue"]["le"] for l in revues), default=None) if len(revues) == len(actives) else None
    echeance = None
    if plus_ancienne:
        echeance = (datetime.datetime.fromisoformat(plus_ancienne) + PERIODE_REVUE).isoformat()
    sans_responsable = [
        i.nom_affichage or i.nom for i in institutions.values()
        if not any(l["actif"] and (l["contact_principal"] or l["membre_bureau"] or any(r["code"] in ROLES_RESPONSABLES for r in l["roles"]))
                   for l in lignes if l["institution"] == str(i.id))
    ]
    return {
        "institution": {"id": str(institution.id), "nom": institution.nom_affichage or institution.nom},
        "institutions": [{"id": str(i.id), "nom": i.nom_affichage or i.nom, "type_libelle": i.type.libelle if i.type_id else ""}
                         for i in sorted(institutions.values(), key=lambda i: (i.institution_parente_id is not None, i.nom or ""))],
        "lignes": lignes,
        "resume": {
            "fiches": len(lignes), "actives": len(actives),
            "a_revoir": sum(1 for l in actives if any(a["code"] in ("JAMAIS_REVU", "REVUE_ECHUE") for a in l["anomalies"])),
            "anomalies": sum(1 for l in lignes if any(a["code"] not in ("JAMAIS_REVU", "REVUE_ECHUE") for a in l["anomalies"])),
            "prochaine_echeance": echeance,
            "sans_responsable": sans_responsable,
            "periode_jours": PERIODE_REVUE.days, "seuil_inactivite_jours": SEUIL_INACTIVITE.days,
        },
    }


def decider(request, contact, decision, commentaire="", role_affectation=None):
    """Applique une décision de revue, la trace (RevueDroits + main courante). Rend la revue."""
    from .audit import audit_log
    from .models import RevueDroits

    D = RevueDroits.Decision
    detail = ""
    if decision == D.BUREAU_RETIRE:
        contact.membre_bureau = False
        contact.save(update_fields=["membre_bureau"])
    elif decision == D.CONTACT_DESACTIVE:
        contact.actif = False
        contact.save(update_fields=["actif"])
    elif decision == D.ROLE_RETIRE:
        if role_affectation is None:
            raise ValueError("Quel rôle retirer ?")
        detail = role_affectation.role.code
        role_affectation.actif = False
        role_affectation.date_fin = timezone.now()
        role_affectation.save(update_fields=["actif", "date_fin"])
    elif decision != D.CONFIRME:
        raise ValueError("Décision inconnue.")
    revue = RevueDroits.objects.create(
        contact=contact, institution=contact.institution, utilisateur=contact.utilisateur,
        revu_par=request.user, decision=decision, detail=detail, commentaire=(commentaire or "")[:2000],
        environment=contact.environment,
    )
    audit_log(request=request, action_code="MODIFICATION", objet_type="RevueDroits", objet_id=revue.id,
              commentaire=f"Revue des droits — {_nom(contact.utilisateur)} ({contact.institution.nom}) : "
                          f"{revue.get_decision_display()}{' ' + detail if detail else ''}")
    return revue
