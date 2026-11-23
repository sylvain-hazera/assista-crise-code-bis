"""La réserve communale de sécurité civile (RCSC), institution fille de sa mairie (23/11/2026).

Décision de Sylvain, à partir du cas d'un réserviste de la RCSC du Porge qui testait
l'application : une RCSC est une **institution fille de la mairie** (comme un CCAS), et ses
réservistes ont **tous les droits de la mairie** -- sauf le registre des personnes
vulnérables, qui exige une désignation nominative du maire (art. R. 121-7 CASF, voir
core/vulnerabilites.py) et n'est jamais ouvert par l'appartenance à la réserve.

**Comment les droits passent.** Une trentaine de contrôles lisent l'institution de travail du
compte (`User.institution`) : sa commune, ses modules, ses crises. Plutôt que de leur
apprendre à remonter d'une fille à sa mère, l'institution de travail d'un réserviste EST la
mairie mère, et son compte est « autorité locale ». Son appartenance à la réserve est portée
par sa fiche de contact dans l'institution RCSC (fonction « Réserviste ») et par l'équipe de
la RCSC, marquée `est_equipe_rcsc`. C'est `grant_institution_and_demo_access`, passage obligé
de tout rattachement, qui applique cette règle.

**Une RCSC par mairie**, créée sous elle (jamais à côté) ; elle prend la commune de sa mère.
"""
CODE_TYPE = "rcsc"
LIBELLE_TYPE = "Réserve communale de sécurité civile (RCSC)"
FONCTION_RESERVISTE = "Réserviste"


def est_rcsc(institution) -> bool:
    type_ = getattr(institution, "type", None)
    return bool(type_ and (type_.code or "").lower() == CODE_TYPE)


def est_mairie(institution) -> bool:
    type_ = getattr(institution, "type", None)
    return bool(type_ and (type_.code or "").lower() == "mairie")


def type_rcsc():
    from .models import InstitutionType
    return (InstitutionType.objects.filter(code__iexact=CODE_TYPE).first()
            or InstitutionType.objects.create(code=CODE_TYPE, libelle=LIBELLE_TYPE))


def rcsc_de(mairie):
    """La RCSC (active) de cette mairie, ou None."""
    from .models import Institution
    if mairie is None:
        return None
    return Institution.objects.filter(institution_parente=mairie, type__code__iexact=CODE_TYPE, actif=True).first()


def mairie_d_exercice(institution):
    """L'institution dont les droits s'exercent : la mairie mère pour une RCSC, elle-même sinon."""
    if est_rcsc(institution) and institution.institution_parente_id:
        return institution.institution_parente
    return institution


def verifier_creation_rcsc(mere):
    """Lève ValueError si une RCSC ne peut pas naître sous `mere`."""
    if mere is None or not est_mairie(mere):
        raise ValueError("Une réserve communale de sécurité civile se crée sous sa mairie.")
    if rcsc_de(mere) is not None:
        raise ValueError(f"{mere.nom} a déjà sa réserve communale : ajoutez-y les réservistes.")


def completer(rcsc):
    """Après création : la commune de la mère, et l'équipe marquée RCSC."""
    from .models import Team
    mere = rcsc.institution_parente
    champs = []
    for champ in ("commune_code", "commune_nom", "commune_code_postal"):
        if mere is not None and not getattr(rcsc, champ) and getattr(mere, champ):
            setattr(rcsc, champ, getattr(mere, champ))
            champs.append(champ)
    if champs:
        rcsc.save()   # save() recalcule EPCI, département et région depuis la commune
    Team.objects.filter(institution=rcsc).update(est_equipe_rcsc=True)


def de_la_commune(nom):
    """« du Porge », « de La Teste-de-Buch », « des Eglisottes », « d'Arcachon », « de Mérignac »."""
    nom = (nom or "").strip()
    if nom.startswith("Le "):
        return "du " + nom[3:]
    if nom.startswith("Les "):
        return "des " + nom[4:]
    if nom[:1].upper() in "AEIOUYHÂÉÈÊÎÔÛ":
        return "d'" + nom
    return "de " + nom


def creer_pour(mairie, environment=None):
    """Crée la RCSC d'une mairie (inscription d'un réserviste dont la mairie n'a pas encore la
    sienne, script d'exploitation). Rend la RCSC existante si elle existe déjà."""
    from .creation_institution import creer_equipe_fille
    from .models import Institution
    existante = rcsc_de(mairie)
    if existante is not None:
        return existante
    environnement = environment or mairie.environment
    rcsc = Institution.objects.create(
        nom=f"Réserve communale {de_la_commune(mairie.commune_nom or mairie.nom)}", type=type_rcsc(),
        institution_parente=mairie, environment=environnement, actif=True,
    )
    creer_equipe_fille(rcsc, mairie, None, environnement)
    completer(rcsc)
    return rcsc
