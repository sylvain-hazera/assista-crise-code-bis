"""Quelle pièce on demande, pourquoi, et combien de temps on la garde.

Demande de Sylvain du 13/11/2026 : afficher la politique de conservation **sur la page de
dépôt et sur la page de validation**, avec le texte de loi applicable et le pourquoi.

Cette table est une **donnée du logiciel** et non un texte recopié dans deux gabarits. Le
motif est de fond : c'est elle qui décide si le fichier est détruit à la validation
(`regime == VERIFIER_DETRUIRE`). Un tableau d'information qui dirait autre chose que ce que le
code fait serait pire que pas de tableau — il ferait croire à une destruction qui n'a pas lieu.
Elle est donc lue à la fois par l'écran et par `core/pieces_conformite.py`.

**Les trois régimes.**

- `VERIFIER_DETRUIRE` — la pièce prouve un fait ponctuel (cette personne est bien elle, elle a
  le permis). Une fois le fait établi et consigné (qui a vérifié, quand, jusqu'à quand c'est
  valable), la copie n'ajoute plus rien : elle ne fait qu'augmenter le préjudice en cas de
  fuite. On la détruit. **Et jamais le numéro de la pièce** : il est aussi identifiant que la
  copie elle-même.
- `CONSERVER_ENGAGEMENT` — il faut pouvoir **re**produire la pièce à un tiers (préfecture au
  renouvellement d'agrément, assureur, juge), pas seulement l'avoir vue. On la garde tant que
  la personne est engagée, puis le délai de prescription.
- `DUREE_LEGALE` — un texte impose la durée ; elle ne dépend ni de l'appartenance de la
  personne ni de notre appréciation.

**Sur les durées.** Celles du régime `DUREE_LEGALE` portent une référence d'article et sont
fermes. Les autres sont des durées **recommandées**, alignées sur les délais de prescription :
c'est l'association qui doit prouver, après coup, que l'intervenant envoyé était qualifié. Le
champ `ferme` dit lequel est lequel, et l'écran l'affiche — présenter une recommandation comme
une obligation est une faute symétrique de l'inverse.

Le registre des traitements de l'association reste à valider par son DPO : cette table est un
point de départ documenté, pas un avis juridique.
"""

REGIME_VERIFIER_DETRUIRE = "VERIFIER_DETRUIRE"
REGIME_CONSERVER_ENGAGEMENT = "CONSERVER_ENGAGEMENT"
REGIME_DUREE_LEGALE = "DUREE_LEGALE"

REGIMES = [
    {
        "code": REGIME_VERIFIER_DETRUIRE,
        "libelle": "Vérifier, puis détruire la copie",
        "resume": "La copie disparaît dès la validation. Il reste qui a vérifié, quand, et "
                  "jusqu'à quand la pièce est valable.",
        "pourquoi": "La pièce prouve un fait ponctuel. Une fois ce fait établi et consigné, "
                    "garder la copie n'apporte rien et augmente seulement ce qui serait perdu "
                    "en cas de fuite.",
    },
    {
        "code": REGIME_CONSERVER_ENGAGEMENT,
        "libelle": "Conserver le temps de l'engagement",
        "resume": "La pièce est gardée tant que la personne est engagée, puis le délai de "
                  "prescription, avant destruction.",
        "pourquoi": "Il faut pouvoir re-produire la pièce à un tiers — préfecture au "
                    "renouvellement de l'agrément, assureur, juge — et pas seulement l'avoir "
                    "vue une fois.",
    },
    {
        "code": REGIME_DUREE_LEGALE,
        "libelle": "Durée imposée par la loi",
        "resume": "La durée est fixée par un texte ; elle ne dépend pas de l'appartenance de "
                  "la personne à l'association.",
        "pourquoi": "Ces pièces servent à un contrôle extérieur — comptable, social, "
                    "judiciaire — dont le calendrier n'est pas le nôtre.",
    },
]

FAMILLE_PERSONNE = "PERSONNE"
FAMILLE_TITRES = "TITRES"
FAMILLE_ASSOCIATION = "ASSOCIATION"
FAMILLE_OPERATIONNEL = "OPERATIONNEL"

FAMILLES = [
    {"code": FAMILLE_PERSONNE, "libelle": "Pièces de la personne"},
    {"code": FAMILLE_TITRES, "libelle": "Titres et qualifications"},
    {"code": FAMILLE_ASSOCIATION, "libelle": "Pièces de l'association"},
    {"code": FAMILLE_OPERATIONNEL, "libelle": "Pièces opérationnelles"},
]

#: Délai au-delà duquel une pièce déposée que personne n'a validée est détruite.
#: Trente jours : assez pour qu'un bureau bénévole ait le temps de relire, assez court pour
#: qu'un dépôt oublié ne devienne pas un stock de permis de conduire conservés sans raison.
JOURS_AVANT_PURGE_NON_VALIDEE = 30

#: Combien de jours avant la purge on prévient la personne et l'encadrement. Détruire sans
#: prévenir ferait redéposer dans le vide : c'est l'encadrement qui n'a pas regardé, pas le
#: bénévole qui a mal fait.
JOURS_AVANT_RAPPEL_PURGE = 7


def _entree(cle, libelle, famille, regime, duree, base_legale, pourquoi, ferme=False,
            deposable=False):
    return {
        "cle": cle, "libelle": libelle, "famille": famille, "regime": regime,
        "duree": duree, "base_legale": base_legale, "pourquoi": pourquoi,
        # True = une référence de texte impose la durée ; False = durée recommandée.
        "ferme": ferme,
        # True = c'est une pièce qu'un bénévole dépose lui-même sur la plateforme. Les autres
        # sont là pour que l'association ait la table complète, pas parce qu'on les collecte.
        "deposable": deposable,
    }


#: La table complète. L'ordre est celui de lecture, pas un ordre technique.
PIECES = [
    # ── Pièces de la personne ────────────────────────────────────────────────────────────
    _entree(
        "IDENTITE", "Pièce d'identité (CNI, passeport)", FAMILLE_PERSONNE,
        REGIME_VERIFIER_DETRUIRE, "Copie détruite dès la validation",
        "RGPD art. 5.1.c et 5.1.e (minimisation des données et de leur durée). La CNIL "
        "rappelle qu'une copie de pièce d'identité ne doit pas être conservée au-delà du "
        "besoin qui l'a justifiée.",
        "Vérifier que la personne est bien celle qu'elle dit être, à l'adhésion. Une fois "
        "cette vérification faite et consignée, la copie ne prouve plus rien de nouveau.",
        deposable=True,
    ),
    _entree(
        "PERMIS", "Permis de conduire", FAMILLE_PERSONNE,
        REGIME_VERIFIER_DETRUIRE, "Copie détruite dès la validation ; à revérifier au "
                                  "renouvellement",
        "RGPD art. 5.1.e. Exigence de l'assureur du parc de véhicules.",
        "Vous confier un véhicule de l'association suppose de vérifier que vous avez le "
        "permis et la catégorie qui convient. Ce contrôle fait, la photo du permis n'a plus "
        "d'utilité et devient un risque.",
        deposable=True,
    ),
    _entree(
        "TITRE_SEJOUR", "Titre de séjour", FAMILLE_PERSONNE,
        REGIME_VERIFIER_DETRUIRE, "Copie détruite dès la validation ; seule la date de fin "
                                  "est conservée",
        "RGPD art. 5.1.e.",
        "Même logique que la pièce d'identité : le fait à établir est ponctuel.",
        deposable=True,
    ),
    _entree(
        "DOMICILE", "Justificatif de domicile", FAMILLE_PERSONNE,
        REGIME_VERIFIER_DETRUIRE, "Copie détruite dès la validation ; seule l'adresse est "
                                  "conservée",
        "RGPD art. 5.1.c.",
        "Votre adresse détermine votre rattachement territorial. C'est l'adresse qui sert, "
        "pas la facture qui la prouve.",
        deposable=True,
    ),
    _entree(
        "HONORABILITE", "Attestation d'honorabilité / bulletin n° 3", FAMILLE_PERSONNE,
        REGIME_VERIFIER_DETRUIRE, "Aucune copie, à aucun moment",
        "RGPD art. 10 (données relatives aux condamnations pénales) : leur traitement est "
        "strictement encadré.",
        "Obligatoire pour l'encadrement de mineurs. Le bulletin se consulte, il ne "
        "s'archive pas : seules la date de consultation et la mention « sans observation » "
        "sont conservées.",
    ),
    _entree(
        "AUTORISATION_PARENTALE", "Autorisation parentale (bénévole mineur)", FAMILLE_PERSONNE,
        REGIME_CONSERVER_ENGAGEMENT, "Jusqu'à la majorité, puis 5 ans",
        "Prescription de droit commun : art. 2224 du code civil (5 ans).",
        "C'est la pièce qui établit que les parents ont consenti. Elle doit survivre à la "
        "minorité, puisque c'est après coup qu'elle sera demandée.",
        deposable=True,
    ),
    _entree(
        "MEDICAL", "Certificat médical d'aptitude", FAMILLE_PERSONNE,
        REGIME_CONSERVER_ENGAGEMENT, "Durée de validité + 1 an",
        "RGPD art. 9 (données de santé) : accès restreint au seul responsable désigné.",
        "L'aptitude conditionne certaines missions et la conduite de véhicules de secours. "
        "C'est une donnée de santé : elle n'est lue que par la personne désignée pour cela, "
        "jamais par l'ensemble de l'encadrement.",
        deposable=True,
    ),
    _entree(
        "PHOTO", "Photo d'identité", FAMILLE_PERSONNE,
        REGIME_CONSERVER_ENGAGEMENT, "Fin de l'engagement",
        "RGPD art. 5.1.e.",
        "Carte de membre et identification sur le terrain.",
        deposable=True,
    ),
    _entree(
        "RIB", "RIB", FAMILLE_PERSONNE,
        REGIME_DUREE_LEGALE, "10 ans",
        "Art. L123-22 du code de commerce : les pièces justificatives comptables sont "
        "conservées 10 ans.",
        "Un remboursement de frais est une écriture comptable ; son justificatif suit la "
        "même durée que la comptabilité.",
        # Déposable : c'est bien le bénévole qui fournit son RIB. Il manquait dans la liste
        # des pièces proposables, ce qui l'aurait rendu absent du choix « Type de document »
        # alors qu'on le demande à tout le monde.
        ferme=True, deposable=True,
    ),
    _entree(
        "ASSURANCE_PERSONNELLE", "Attestation d'assurance personnelle", FAMILLE_PERSONNE,
        REGIME_CONSERVER_ENGAGEMENT, "Durée de validité + 1 an",
        "RGPD art. 5.1.e.",
        "Couverture complémentaire à celle de l'association.",
        deposable=True,
    ),

    # ── Titres et qualifications ─────────────────────────────────────────────────────────
    _entree(
        "SECOURISME", "PSC1, PSE1, PSE2, BNSSA", FAMILLE_TITRES,
        REGIME_CONSERVER_ENGAGEMENT, "Engagement + 5 ans",
        "Prescription de droit commun : art. 2224 du code civil. Pièces exigibles au "
        "renouvellement de l'agrément de sécurité civile.",
        "C'est la pièce qui prouve, après coup, que l'équipe envoyée était qualifiée. Si un "
        "engagement est contesté, c'est à l'association de le démontrer.",
        deposable=True,
    ),
    _entree(
        "FORMATION_CONTINUE", "Attestation de formation continue annuelle", FAMILLE_TITRES,
        REGIME_CONSERVER_ENGAGEMENT, "Engagement + 5 ans",
        "Obligation de maintien et d'actualisation des acquis pour les titulaires PSE. "
        "Art. 2224 du code civil pour la durée.",
        "Un PSE non recyclé ne vaut plus rien le jour de la mobilisation. L'attestation "
        "prouve que le recyclage a bien eu lieu.",
        deposable=True,
    ),
    _entree(
        "FORMATEUR", "Titres de formateur (PAE FPS, PAE FPSC)", FAMILLE_TITRES,
        REGIME_CONSERVER_ENGAGEMENT, "Engagement + 5 ans",
        "Art. 2224 du code civil.",
        "Habilite à former d'autres secouristes : la chaîne entière des qualifications "
        "délivrées en dépend.",
        deposable=True,
    ),
    _entree(
        "HABILITATION", "CACES, permis bateau, CRR (radio)", FAMILLE_TITRES,
        REGIME_CONSERVER_ENGAGEMENT, "Engagement + 5 ans",
        "Art. 2224 du code civil.",
        "Habilitations spécifiques exigées pour certains matériels et moyens.",
        deposable=True,
    ),

    # ── Pièces de l'association ──────────────────────────────────────────────────────────
    _entree(
        "STATUTS", "Statuts, récépissé de préfecture, parution au JO", FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "Illimitée",
        "Loi du 1er juillet 1901 et son décret d'application.",
        "Ce sont les actes constitutifs : ils ne se périment pas.",
        ferme=True,
    ),
    _entree(
        "AGREMENT", "Agrément de sécurité civile (A, B, C, D) et dossier de demande",
        FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "Durée de l'agrément + le cycle de renouvellement suivant",
        "Art. L725-1 et suivants du code de la sécurité intérieure ; décret n° 2006-237 du "
        "27 février 2006 relatif à la procédure d'agrément de sécurité civile.",
        "Le dossier du cycle précédent sert à instruire le renouvellement : le détruire "
        "oblige à tout reconstituer.",
        ferme=True,
    ),
    _entree(
        "AG", "PV d'assemblée générale, rapports moral et financier", FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "Illimitée",
        "Loi du 1er juillet 1901.",
        "Mémoire des décisions de l'association et de la régularité de sa gouvernance.",
        ferme=True,
    ),
    _entree(
        "DIRIGEANTS", "Liste des dirigeants déclarée en préfecture", FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "Illimitée (historique)",
        "Art. 5 de la loi du 1er juillet 1901 (déclaration des changements).",
        "Savoir qui engageait l'association à une date donnée.",
        ferme=True,
    ),
    _entree(
        "ASSURANCE_ASSOCIATION", "Assurance responsabilité civile de l'association",
        FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "10 ans après la fin du contrat",
        "Art. 2226 du code civil : l'action en responsabilité pour dommage corporel se "
        "prescrit par 10 ans.",
        "Un dommage corporel peut être invoqué longtemps après les faits ; il faut alors "
        "pouvoir produire le contrat en vigueur ce jour-là.",
        ferme=True,
    ),
    _entree(
        "COMPTABILITE", "Comptes annuels, pièces comptables, notes de frais",
        FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "10 ans",
        "Art. L123-22 du code de commerce.",
        "Contrôle comptable et fiscal.",
        ferme=True,
    ),
    _entree(
        "PAIE", "Bulletins de paie (si salariés)", FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "5 ans",
        "Art. L3243-4 du code du travail.",
        "Contrôle et reconstitution de carrière.",
        ferme=True,
    ),
    _entree(
        "REGISTRE_PERSONNEL", "Registre unique du personnel", FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "5 ans après le départ du salarié",
        "Art. R1221-26 du code du travail.",
        "Contrôle de l'inspection du travail.",
        ferme=True,
    ),
    _entree(
        "CONVENTIONS", "Conventions (mairie, préfecture, opérateurs)", FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "Durée de la convention + 5 ans",
        "Art. 2224 du code civil.",
        "Établit ce que l'association s'était engagée à faire, et pour qui.",
        ferme=True,
    ),
    _entree(
        "ACCIDENT", "Déclarations d'accident (salarié ou bénévole)", FAMILLE_ASSOCIATION,
        REGIME_DUREE_LEGALE, "5 ans, et 10 ans en cas de dommage corporel",
        "Art. 2224 et 2226 du code civil.",
        "Les suites d'un accident se manifestent parfois des années plus tard.",
        ferme=True,
    ),

    # ── Pièces opérationnelles ───────────────────────────────────────────────────────────
    _entree(
        "ORDRE_MISSION", "Ordre de mission / ordre d'engagement", FAMILLE_OPERATIONNEL,
        REGIME_DUREE_LEGALE, "10 ans",
        "Art. 2226 du code civil (dommage corporel).",
        "C'est la pièce qui rattache un intervenant nommé à un fait daté.",
        ferme=True,
    ),
    _entree(
        "EMARGEMENT", "Feuille d'émargement, main courante", FAMILLE_OPERATIONNEL,
        REGIME_DUREE_LEGALE, "10 ans",
        "Art. 2226 du code civil.",
        "Qui était présent, et ce qui a été décidé à quelle heure.",
        ferme=True,
    ),
    _entree(
        "RAPPORT", "Rapport d'intervention, rapport d'incident", FAMILLE_OPERATIONNEL,
        REGIME_DUREE_LEGALE, "10 ans",
        "Art. 2226 du code civil.",
        "Le récit des faits, écrit à chaud, est la meilleure défense de l'association.",
        ferme=True,
    ),
    _entree(
        "BILAN_SECOURISTE", "Fiche bilan secouriste (victime)", FAMILLE_OPERATIONNEL,
        REGIME_DUREE_LEGALE, "10 ans, hors plateforme et sous accès nominatif restreint",
        "RGPD art. 9 (données de santé) ; art. 2226 du code civil pour la durée.",
        "Donnée de santé d'un tiers, qui n'est pas membre de l'association et n'a pas "
        "choisi d'y figurer. Elle n'a pas sa place dans un outil de gestion d'équipes.",
        ferme=True,
    ),
    _entree(
        "PRET_MATERIEL", "Fiche de prêt / restitution de matériel", FAMILLE_OPERATIONNEL,
        REGIME_CONSERVER_ENGAGEMENT, "Restitution + 3 ans",
        "Art. 2224 du code civil.",
        "Établit qui détenait quoi, en cas de perte ou de litige.",
    ),
    _entree(
        "VEHICULE", "Carte grise, contrôle technique, assurance du véhicule",
        FAMILLE_OPERATIONNEL,
        REGIME_DUREE_LEGALE, "Durée de détention + 5 ans",
        "Art. 2224 du code civil ; code de la route pour le contrôle technique.",
        "Prouve que le véhicule engagé était en règle ce jour-là.",
        ferme=True,
    ),
    _entree(
        "DISPOSITIF_MEDICAL", "Traçabilité des dispositifs médicaux (O₂, DAE)",
        FAMILLE_OPERATIONNEL,
        REGIME_DUREE_LEGALE, "Durée de vie du dispositif + 5 ans",
        "Obligation de matériovigilance : art. L5212-1 et R5212-12 du code de la santé "
        "publique.",
        "Permet de retrouver quel appareil a été utilisé sur qui, en cas de rappel ou "
        "d'incident.",
        ferme=True,
    ),
]

PIECES_PAR_CLE = {p["cle"]: p for p in PIECES}

#: Les catégories qu'un bénévole dépose lui-même : ce sont les seules proposées au catalogue
#: des qualifications. Les autres figurent dans la table pour que l'association ait la vue
#: complète, pas parce qu'on les collecte ici.
CLES_DEPOSABLES = [p["cle"] for p in PIECES if p["deposable"]]

#: Catégorie par défaut d'une entrée du catalogue : un titre de secourisme. C'est ce que sont
#: la quasi-totalité des qualifications déjà saisies, et le régime le moins destructeur — se
#: tromper dans ce sens fait garder une pièce de trop, jamais perdre une pièce qu'il fallait.
CLE_PAR_DEFAUT = "SECOURISME"


def piece(cle):
    """La ligne de la table, ou celle par défaut si la clé est inconnue (catalogue importé
    avant cette table, entrée créée par une institution)."""
    return PIECES_PAR_CLE.get(cle) or PIECES_PAR_CLE[CLE_PAR_DEFAUT]


def regime_de(cle):
    return piece(cle)["regime"]


def detruire_apres_validation(cle):
    """Le seul appel qui décide d'une suppression de fichier. Voir core/pieces_conformite.py."""
    return regime_de(cle) == REGIME_VERIFIER_DETRUIRE


def table():
    """La table complète, pour l'API : familles, régimes et pièces, prêts à afficher."""
    return {
        "regimes": REGIMES,
        "familles": FAMILLES,
        "pieces": PIECES,
        "jours_avant_purge_non_validee": JOURS_AVANT_PURGE_NON_VALIDEE,
        "jours_avant_rappel_purge": JOURS_AVANT_RAPPEL_PURGE,
    }
