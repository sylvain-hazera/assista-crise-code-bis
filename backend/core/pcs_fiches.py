"""Fiches réflexes types du poste de commandement communal.

Reprises de la trame simplifiée du plan communal de sauvegarde diffusée par les préfectures
(annexe « Fiches réflexe »), fautes de frappe corrigées. Elles servent de point de départ : une
commune qui n'a rien écrit sort quand même un document avec des fiches, et ne réécrit que ce
qu'elle veut changer (`FonctionPCS.consignes`).
"""

# 18/11/2026 : chaque ligne dit aussi OÙ cela se fait dans l'application, entre crochets — une
# fiche réflexe qu'on lit à la première minute doit mener au bon écran. Vocabulaire du projet :
# on parle de « demande de mobilisation » (la commune ne signe pas de réquisition depuis
# l'application), et les arrêtés se prennent sur papier à en-tête de la mairie, hors application.
FICHES_TYPES = {
    "DOS": (
        "Déclenche le plan après évaluation de la situation, ou sur demande du préfet [Crises : déclarer la crise].",
        "Confirme la liste des interlocuteurs à prévenir, préparée à l'ouverture [Démarrage de la crise].",
        "Dirige les actions de son équipe municipale et décide des actions à mener [Cellule de crise].",
        "Valide les propositions du commandant des opérations de secours.",
        "S'assure que toute la population concernée est bien alertée [Alerter les habitants].",
        "Communique avec la population et les médias ; renseigne les autorités [Point de situation].",
        "Mobilise les moyens publics et privés [Demandes de mobilisation] ; requiert par arrêté s'il le faut.",
        "Prend les décisions administratives nécessaires, par arrêté sur papier à en-tête de la mairie.",
    ),
    "COORDINATION": (
        "S'assure de la mise en place du dispositif et des équipes [Cellule de crise, Équipes].",
        "Reste en lien permanent avec le maire et se tient informé des décisions prises.",
        "Anime la cellule de crise communale [salon de messagerie de la crise].",
        "Veille à ce que les actions décidées soient réalisées et transmet les ordres au terrain [Missions, Dossiers].",
        "Centralise les comptes rendus et les demandes du terrain ; élabore le point de situation [Point de situation].",
        "Fait remonter les informations à la préfecture.",
        "Prépare les demandes de mobilisation et les projets d'arrêté [Demandes de mobilisation].",
        "Organise les relèves : personne ne tient deux jours sans relais [Planning des équipes].",
    ),
    "ALERTE": (
        "Lance l'alerte avec les moyens que la commune a décrits [Alerter les habitants].",
        "Fait déclencher la sirène par la personne désignée, en suivant sa fiche de déclenchement.",
        "Organise le porte-à-porte et les personnes relais ; leur envoie le message à relayer.",
        "Rend compte à la cellule de crise de l'avancement de l'alerte et des difficultés rencontrées.",
        "En cas d'évacuation, indique à la population le lieu d'accueil, ou demande à la cellule "
        "de crise les moyens d'assurer l'évacuation.",
        "Prévient en priorité les personnes vulnérables, par ceux qui tiennent le registre.",
    ),
    "SOUTIEN": (
        "Ouvre le ou les centres d'accueil et de regroupement [Centres] ; un centre installé dans "
        "un lieu de la commune en reprend le stock (lits, tables, couvertures).",
        "Rend compte à la cellule de crise de leur ouverture et des difficultés rencontrées.",
        "Demande l'appui des associations agréées de sécurité civile ou de la réserve communale.",
        "Demande les moyens matériels nécessaires au fonctionnement des centres [Stocks].",
        "Tient le registre des personnes accueillies et le transmet à la cellule de crise.",
        "Évalue le nombre de repas à distribuer et en fait la demande.",
        "Suit les familles qui ne peuvent pas rentrer chez elles [Relogement des familles].",
    ),
    "LOGISTIQUE": (
        "Met à disposition les matériels recensés, nécessaires au bon déroulement des actions [Stocks].",
        "Anime sur le terrain les équipes chargées de la mise en place des matériels.",
        "Prend contact avec les détenteurs et propriétaires pour honorer les demandes ; fait acheminer le matériel.",
        "Tient à jour la liste des matériels utilisés, prêtés ou mobilisés [Stocks : prêts, mouvements].",
        "Ferme les voies et met en place les déviations.",
    ),
    "SECRETARIAT": (
        "Appelle les responsables, les membres du conseil municipal et les personnes ressources [Annuaire de crise].",
        "Prépare la cellule de crise (matériel de bureau, postes téléphoniques).",
        "Tient le standard : une fiche par appel, et la demande de l'appelant saisie pour lui [Standard de crise].",
        "Ouvre dès le début de la crise le journal de bord et le tient [Cellule de crise].",
        "Assiste le coordinateur des moyens et des actions.",
    ),
    "AUTRE": (),
}

#: Fiche type de chaque moyen d'alerte (18/11/2026) : ce qu'on fait quand on le déclenche. Elle
#: sort dans « Alerter les habitants » quand on coche le moyen, tant que la commune n'a pas écrit
#: la sienne (`MoyenAlertePCS.consignes`).
FICHES_MOYENS = {
    "SIRENE": (
        "Vérifier que la décision d'alerter est prise, et le signal attendu (début d'alerte ou fin d'alerte).",
        "Appeler la personne qui la déclenche ; à défaut, son suppléant.",
        "Signal national d'alerte : trois cycles d'une minute quarante et une seconde, séparés de cinq secondes. "
        "Fin d'alerte : un son continu de trente secondes.",
        "Doubler par un autre moyen : une sirène dit qu'il y a un danger, pas quoi faire.",
        "Noter l'heure du déclenchement ; elle est inscrite au journal de bord de la crise.",
    ),
    "VEHICULE": (
        "Remettre au conducteur le message à diffuser, court et répété : ce qui se passe, quoi faire, où aller.",
        "Suivre le circuit prévu ; rouler au pas et s'arrêter aux carrefours.",
        "Ne pas entrer dans une zone dangereuse (eau, fumées) : contourner et le signaler.",
        "Rendre compte à la fin du circuit : rues couvertes, rues impossibles, personnes rencontrées.",
    ),
    "AUTOMATE": (
        "Vérifier la liste des numéros à appeler et le message enregistré.",
        "Lancer l'envoi, puis suivre le taux de réponse.",
        "Faire rappeler à la main ceux qui n'ont pas répondu, en priorité les personnes vulnérables.",
    ),
    "RELAIS": (
        "Prévenir la personne relais du quartier et lui envoyer le message à relayer.",
        "Lui demander de prévenir ses voisins, en priorité les personnes isolées ou à mobilité réduite.",
        "Lui demander de rappeler la mairie pour signaler qui n'a pas été joint ou qui a besoin d'aide.",
    ),
    "PORTE_A_PORTE": (
        "Former des binômes ; leur remettre le message, la liste des rues et un moyen de joindre la cellule de crise.",
        "Frapper à chaque porte ; laisser un avis de passage là où personne ne répond.",
        "Noter les personnes qui refusent de partir, celles qui ont besoin d'aide, les logements vides.",
        "Commencer par les rues les plus exposées et par les personnes vulnérables connues.",
        "Rendre compte à la cellule de crise rue par rue.",
    ),
    "AFFICHAGE": (
        "Publier le même message sur le site, les réseaux et les panneaux de la commune.",
        "Dater chaque publication ; publier la fin d'alerte de la même façon.",
    ),
    "AUTRE": (),
}

#: Les fonctions sans lesquelles l'organigramme ne dit pas qui décide ni qui coordonne.
FONCTIONS_ATTENDUES = ("DOS", "COORDINATION")


def fiche_type(fonction: str) -> str:
    return "\n".join(f"• {ligne}" for ligne in FICHES_TYPES.get(fonction, ()))


def fiche_moyen(type_moyen: str) -> str:
    return "\n".join(f"• {ligne}" for ligne in FICHES_MOYENS.get(type_moyen, ()))


#: Les trois points proposés au démarrage d'une crise (voir crise-demarrage côté site) et les
#: fonctions du poste de commandement qui les tiennent, par ordre de préférence. C'est la même
#: organisation vue de deux côtés : l'organigramme dit QUI, le point dit OÙ. L'alerte de la
#: population n'a pas de point : elle se fait sur le terrain.
FONCTIONS_PAR_POINT = {
    "CELLULE_CRISE": ("COORDINATION", "DOS", "SECRETARIAT"),
    "HEBERGEMENT": ("SOUTIEN",),
    "REGROUPEMENT_MOYENS": ("LOGISTIQUE",),
}
