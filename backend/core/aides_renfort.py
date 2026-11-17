"""Ce qu'une institution propose quand elle vient en renfort sur une crise (17/11/2026).

« Ma commune peut aider » ne dit rien à celle qui pilote : aider avec quoi ? Le catalogue est
court et fermé, pour que les propositions se comparent et se comptent ; le détail (combien de
places, à partir de quand) va dans le message libre de la proposition.

Distinct des « thèmes à l'écoute » (`Besoin`), qui disent sur quels besoins des sinistrés une
institution reçoit les demandes. Ici on dit quels MOYENS elle met à disposition.
"""

AIDES = [
    ("CENTRE_ACCUEIL", "Ouvrir un centre d'accueil des civils",
     "Salle, gymnase ou équipement communal pour héberger ou accueillir des sinistrés."),
    ("POINT_REGROUPEMENT", "Point de regroupement des moyens",
     "Un lieu où rassembler équipes, véhicules et matériel avant leur engagement."),
    ("PERSONNEL", "Mise à disposition de personnel",
     "Agents communaux, réserve communale de sécurité civile, bénévoles encadrés."),
    ("MATERIEL", "Prêt de matériel et d'engins",
     "Groupes électrogènes, pompes, tronçonneuses, véhicules, barrières…"),
    ("RESTAURATION", "Restauration",
     "Cuisine centrale, repas préparés, de quoi nourrir sinistrés ou intervenants."),
    ("STOCKAGE", "Stockage et logistique",
     "Local pour recevoir des dons ou du matériel, transport, manutention."),
    ("AUTRE", "Autre aide", "À préciser dans le message."),
]

CODES = {code for code, _, _ in AIDES}
LIBELLES = {code: libelle for code, libelle, _ in AIDES}


def catalogue() -> list:
    return [{"code": c, "libelle": l, "description": d} for c, l, d in AIDES]


def nettoyer(codes) -> list:
    """Les codes reconnus, dans l'ordre du catalogue. Lève ValueError sur un code inconnu :
    une aide qu'on ne sait pas nommer ne se range pas en silence."""
    if codes in (None, ""):
        return []
    if not isinstance(codes, (list, tuple)):
        raise ValueError("Liste de codes d'aide attendue.")
    demandes = {str(c).strip() for c in codes if str(c).strip()}
    inconnus = sorted(demandes - CODES)
    if inconnus:
        raise ValueError("Aide inconnue : " + ", ".join(inconnus))
    return [code for code, _, _ in AIDES if code in demandes]


def libelles(codes) -> list:
    return [LIBELLES[c] for c in (codes or []) if c in LIBELLES]
