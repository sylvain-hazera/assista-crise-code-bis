"""Fiches réflexes types du poste de commandement communal.

Reprises de la trame simplifiée du plan communal de sauvegarde diffusée par les préfectures
(annexe « Fiches réflexe »), fautes de frappe corrigées. Elles servent de point de départ : une
commune qui n'a rien écrit sort quand même un document avec des fiches, et ne réécrit que ce
qu'elle veut changer (`FonctionPCS.consignes`).
"""

FICHES_TYPES = {
    "DOS": (
        "Déclenche le plan après évaluation de la situation, ou sur demande du préfet.",
        "Dirige les actions de son équipe municipale et décide des actions à mener.",
        "Valide les propositions du commandant des opérations de secours.",
        "S'assure que toute la population concernée est bien alertée.",
        "Communique avec la population et les médias ; renseigne les autorités.",
        "Mobilise les moyens publics et privés, si nécessaire par voie de réquisition.",
        "Prend les mesures administratives nécessaires, sous forme d'arrêté.",
    ),
    "COORDINATION": (
        "S'assure de la mise en place du dispositif.",
        "Reste en lien permanent avec le maire et se tient informé des décisions prises.",
        "Anime la cellule de crise communale.",
        "Veille à ce que les actions décidées soient réalisées et transmet les ordres au terrain.",
        "Centralise les comptes rendus et les demandes du terrain ; élabore le point de situation.",
        "Fait remonter les informations à la préfecture.",
        "Prépare les demandes de réquisition et les arrêtés d'interdiction.",
    ),
    "ALERTE": (
        "Dirige et organise sur le terrain les équipes qui assurent l'alerte de la population.",
        "Rend compte à la cellule de crise de l'avancement de l'alerte et des difficultés rencontrées.",
        "En cas d'évacuation, indique à la population le lieu d'accueil, ou demande à la cellule "
        "de crise les moyens d'assurer l'évacuation.",
    ),
    "SOUTIEN": (
        "Met en place le ou les centres d'accueil et de regroupement.",
        "Rend compte à la cellule de crise de leur ouverture et des difficultés rencontrées.",
        "Demande l'appui des associations agréées de sécurité civile ou de la réserve communale.",
        "Demande les moyens matériels nécessaires au fonctionnement des centres.",
        "Transmet régulièrement à la cellule de crise la liste des personnes accueillies.",
        "Évalue le nombre de repas à distribuer et en fait la demande.",
    ),
    "LOGISTIQUE": (
        "Met à disposition les matériels recensés, nécessaires au bon déroulement des actions.",
        "Anime sur le terrain les équipes chargées de la mise en place des matériels.",
        "Prend contact avec les détenteurs et propriétaires pour honorer les demandes ; fait acheminer le matériel.",
        "Tient à jour, avec la cellule de crise, la liste des matériels utilisés, empruntés ou réquisitionnés.",
        "Ferme les voies et met en place les déviations.",
    ),
    "SECRETARIAT": (
        "Appelle les responsables, les membres du conseil municipal et les personnes ressources.",
        "Prépare la cellule de crise (matériel de bureau, postes téléphoniques).",
        "Assure l'accueil téléphonique.",
        "Ouvre dès le début de la crise le journal de bord et le tient.",
        "Assiste le coordinateur des moyens et des actions.",
    ),
    "AUTRE": (),
}

#: Les fonctions sans lesquelles l'organigramme ne dit pas qui décide ni qui coordonne.
FONCTIONS_ATTENDUES = ("DOS", "COORDINATION")


def fiche_type(fonction: str) -> str:
    return "\n".join(f"• {ligne}" for ligne in FICHES_TYPES.get(fonction, ()))


#: Les trois points proposés au démarrage d'une crise (voir crise-demarrage côté site) et les
#: fonctions du poste de commandement qui les tiennent, par ordre de préférence. C'est la même
#: organisation vue de deux côtés : l'organigramme dit QUI, le point dit OÙ. L'alerte de la
#: population n'a pas de point : elle se fait sur le terrain.
FONCTIONS_PAR_POINT = {
    "CELLULE_CRISE": ("COORDINATION", "DOS", "SECRETARIAT"),
    "HEBERGEMENT": ("SOUTIEN",),
    "REGROUPEMENT_MOYENS": ("LOGISTIQUE",),
}
