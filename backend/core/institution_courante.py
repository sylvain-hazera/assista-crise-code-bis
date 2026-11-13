"""Pour quelle institution cette personne travaille en ce moment.

Demande de Sylvain du 13/11/2026 : *« attention, un utilisateur peut être membre de plusieurs
institutions. Une mairie et une asso. »*

**Deux questions différentes, deux sources différentes.**

- « De qui est-il membre ? » → `ContactInstitution`, une table de liaison : autant de lignes
  que d'appartenances. C'est la vérité.
- « Pour qui travaille-t-il en ce moment ? » → `User.institution`, un champ unique. C'est un
  **contexte**, pas une appartenance.

Confondre les deux est le piège que ce module existe pour fermer. Le contexte pilote le
périmètre territorial (`core/zone_scoping.py`), la « Vue Ma Collectivité » et le branding des
emails. Jusqu'ici il était posé au **premier** rattachement et ne bougeait plus : un agent de
la mairie de Saint-Étienne également adhérent d'une association nationale voyait donc son
périmètre dépendre de l'ordre de ses inscriptions — un ordre que personne ne connaît et que
rien n'affiche.

**Ce que ce module ajoute** : la possibilité de changer de contexte, et la garantie qu'on ne
peut en choisir qu'un où l'on est réellement membre. Sans cette vérification, le champ
deviendrait une porte d'entrée vers le périmètre de n'importe quelle institution — il décide
d'un contrôle d'accès, pas d'un affichage.
"""


def institutions_de(utilisateur):
    """Les institutions dont la personne est membre ACTIF, par ordre alphabétique.

    `actif=False` est exclu : un rattachement désactivé n'ouvre plus de droits, et proposer de
    basculer dessus rendrait un périmètre à quelqu'un qu'on vient d'en sortir."""
    from .models import ContactInstitution, Institution

    ids = (ContactInstitution.objects
           .filter(utilisateur=utilisateur, actif=True, institution__actif=True)
           .values_list("institution_id", flat=True))
    return list(Institution.objects.filter(id__in=list(ids)).order_by("nom"))


def est_membre(utilisateur, institution_id):
    """La personne est-elle membre actif de cette institution ?

    La SEULE façon correcte de répondre : lire `User.institution` donnerait « non » pour la
    deuxième institution d'un compte multi-appartenance."""
    from .models import ContactInstitution

    if not institution_id:
        return False
    return ContactInstitution.objects.filter(
        utilisateur=utilisateur, institution_id=institution_id, actif=True,
    ).exists()


def definir_institution_active(utilisateur, institution_id):
    """Change le contexte de travail. Renvoie `(institution, erreur)`.

    Vérifie l'appartenance avant d'écrire : ce champ décide d'un périmètre territorial, donc
    accepter un identifiant sans contrôle reviendrait à laisser n'importe qui s'attribuer la
    zone de n'importe quelle institution."""
    from .models import Institution

    institution = Institution.objects.filter(pk=institution_id, actif=True).first()
    if institution is None:
        return None, "Institution inconnue."
    if not est_membre(utilisateur, institution.id):
        return None, ("Vous n'êtes pas membre de cette institution. Seules celles où vous "
                      "avez un rattachement actif peuvent devenir votre contexte de travail.")
    if utilisateur.institution_id == institution.id:
        return institution, None
    utilisateur.institution = institution
    utilisateur.save(update_fields=["institution"])
    return institution, None


def institution_courante(utilisateur):
    """Le contexte actif, avec un repli utile.

    Repli sur l'unique appartenance quand le raccourci est vide : un compte rattaché une seule
    fois n'a aucune raison d'être aveugle à sa propre commune parce qu'un chemin de création
    ancien a oublié de poser le champ. Avec plusieurs appartenances et aucun choix, on ne
    devine PAS — choisir à la place de quelqu'un son périmètre territorial serait pire que de
    lui demander."""
    if getattr(utilisateur, "institution_id", None):
        return utilisateur.institution
    institutions = institutions_de(utilisateur)
    return institutions[0] if len(institutions) == 1 else None
