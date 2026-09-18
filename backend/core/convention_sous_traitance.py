"""Convention de sous-traitance RGPD (article 28) exigée des collectivités (mairie/EPCI/SDIS)
à l'activation de leur compte — voir /rgpd (section 1, modèle à deux niveaux) et la page
publique /convention-sous-traitance (frontend/src/app/public/legal/convention-sous-traitance/).

`CONVENTION_VERSION` DOIT rester synchronisée avec `CONVENTION_VERSION` côté frontend
(convention-sous-traitance.component.ts) : c'est cette valeur qui est enregistrée sur
`Institution.convention_sous_traitance_version` à chaque acceptation, pour ne jamais prétendre
couvrir une future révision du texte sans nouvelle acceptation explicite."""

CONVENTION_VERSION = "2026-09-18"

# Types d'institution considérés comme "collectivité" au sens de la page RGPD ("mairie, EPCI,
# service de secours") — DISTINCT de _institution_est_autorite_locale (mairie/EPCI seulement,
# utilisé pour d'autres décisions comme la validation des déclarations ACTEUR) : le SDIS est un
# service de secours, pas une autorité locale au sens de ce cadrage, mais reste une collectivité
# devant signer la convention.
CODES_TYPES_COLLECTIVITE = {"mairie", "epci", "sdis"}


def institution_necessite_convention(institution) -> bool:
    """True si cette institution doit accepter la convention avant que son compte ne soit
    pleinement actif — jamais si déjà acceptée (voir Institution.convention_sous_traitance_
    acceptee_le), une convention déjà signée par un premier membre ne se re-signe pas à chaque
    nouveau membre rejoignant la même collectivité."""
    if institution is None:
        return False
    if institution.convention_sous_traitance_acceptee_le is not None:
        return False
    code = (getattr(institution.type, "code", "") or "").lower()
    return code in CODES_TYPES_COLLECTIVITE


# Rendu en texte brut (pas de gabarit d'email HTML dans ce projet à ce jour, voir
# send_mail_logged) — reflète le contenu de la page /convention-sous-traitance ; toute
# modification de fond doit être répercutée aux deux endroits et la version incrémentée aux deux
# endroits.
TEXTE_CONVENTION = """CONVENTION DE SOUS-TRAITANCE (ARTICLE 28 DU RGPD)
Version du {version}

Cette convention est conclue entre :
- {institution_nom} (« le responsable de traitement »), qui active un compte institutionnel
  sur la plateforme Assista Crise ;
- {sous_traitant_nom}, {sous_traitant_adresse}, {sous_traitant_email}, qui développe et héberge
  la plateforme (« le sous-traitant »).

L'acceptation de cette convention par {acceptee_par}, au nom de {institution_nom}, le
{acceptee_le}, vaut signature électronique des deux parties au sens des présentes.

I. OBJET
La présente convention définit les conditions dans lesquelles le sous-traitant s'engage à
effectuer, pour le compte du responsable de traitement, les opérations de traitement de
données à caractère personnel définies ci-après.

II. DESCRIPTION DU TRAITEMENT
- Prestation : mise à disposition et hébergement de la plateforme Assista Crise, utilisée par
  le responsable de traitement pour coordonner la réponse à une ou plusieurs crises sur son
  territoire.
- Nature des opérations : collecte, enregistrement, conservation, consultation, modification et
  suppression des données décrites ci-dessous.
- Finalité(s) : coordination opérationnelle de la réponse à une crise (demandes d'aide, offres
  d'aide, signalements, déclarations "je suis en sécurité", recherches de personnes évacuées,
  gestion des équipes et des missions).
- Catégories de données : identité, coordonnées (email, téléphone), localisation,
  photographies, composition du foyer, indicateur de régime alimentaire spécifique, commentaires
  saisis par les personnes concernées ou par les opérateurs de la collectivité, données
  relatives à une personne recherchée (photographie, description physique).
- Catégories de personnes concernées : citoyens du territoire sollicitant ou proposant de
  l'aide, signalant un événement, se déclarant en sécurité ou recherchés ; agents, élus et
  bénévoles de la collectivité utilisant la plateforme.

III. DURÉE
La convention prend effet à la date d'acceptation ci-dessus et reste applicable tant que la
collectivité dispose d'un compte actif sur la plateforme.

IV. OBLIGATIONS DU SOUS-TRAITANT
Le sous-traitant s'engage à :
 1. traiter les données uniquement pour la ou les finalités décrites en II ;
 2. traiter les données conformément aux instructions documentées du responsable de traitement ;
 3. garantir la confidentialité des données ;
 4. veiller à ce que toute personne autorisée à les traiter s'engage à la confidentialité ;
 5. prendre en compte les principes de protection des données dès la conception et par défaut ;
 6. ne recourir à aucun sous-traitant ultérieur sans autorisation préalable écrite — à ce jour,
    aucun sous-traitant ultérieur : l'hébergement est assuré directement par le sous-traitant
    lui-même (voir /mentions-legales) ;
 7. laisser au responsable de traitement la charge d'informer les personnes concernées, le
    sous-traitant mettant à disposition une mention d'information sur chaque formulaire
    concerné ;
 8. assister le responsable de traitement pour répondre aux demandes d'exercice des droits des
    personnes concernées ;
 9. notifier toute violation de données dans un délai maximum de 72 heures après en avoir eu
    connaissance ;
10. assister le responsable de traitement dans la réalisation d'analyses d'impact, le cas
    échéant ;
11. mettre en œuvre les mesures de sécurité décrites dans la politique de confidentialité
    (HTTPS, mots de passe hachés, accès restreints par rôle, sauvegardes à accès restreint) ;
12. au choix du responsable de traitement en fin de relation contractuelle, détruire ou
    restituer les données de ses crises ;
13. communiquer les coordonnées du délégué à la protection des données (voir /rgpd) ;
14. tenir un registre des catégories d'activités de traitement réalisées pour le compte du
    responsable de traitement ;
15. mettre à disposition la documentation nécessaire pour démontrer le respect de ces
    obligations et permettre un audit.

V. OBLIGATIONS DU RESPONSABLE DE TRAITEMENT
Le responsable de traitement s'engage à :
 1. fournir au sous-traitant les données décrites en II ;
 2. documenter par écrit toute instruction concernant le traitement ;
 3. veiller au respect du RGPD par le sous-traitant ;
 4. pouvoir procéder à des audits/vérifications.

VI. SORT DES DONNÉES ET FIN DE LA CONVENTION
À la fin de la relation contractuelle, le sous-traitant, selon le choix du responsable de
traitement, détruit ou restitue l'ensemble des données traitées pour son compte.

VII. RESPONSABILITÉ ET DROIT APPLICABLE
Chaque partie est responsable des dommages causés par un manquement à ses obligations. Les
présentes sont soumises au droit français.

---
Texte consultable et mis à jour en ligne : {url_convention}
Politique de confidentialité : {url_rgpd}
Mentions légales : {url_mentions_legales}

[Ce texte est construit à partir des clauses contractuelles types proposées par la CNIL pour la
sous-traitance (article 28.3 du RGPD) et n'a pas été relu par un juriste — voir l'avertissement
affiché sur la page en ligne.]
"""


def construire_texte_convention(institution, utilisateur, acceptee_le, base_url):
    """`base_url` : racine du site (ex. https://assista-crise.fr), pour construire les liens
    vers les pages légales dans le corps de l'email."""
    from django.conf import settings as django_settings

    sous_traitant_nom = getattr(django_settings, "CONVENTION_SOUS_TRAITANT_NOM", "[À COMPLÉTER]")
    sous_traitant_adresse = getattr(django_settings, "CONVENTION_SOUS_TRAITANT_ADRESSE", "[À COMPLÉTER]")
    sous_traitant_email = getattr(django_settings, "CONVENTION_SOUS_TRAITANT_EMAIL", "[À COMPLÉTER]")

    return TEXTE_CONVENTION.format(
        version=CONVENTION_VERSION,
        institution_nom=institution.nom,
        sous_traitant_nom=sous_traitant_nom,
        sous_traitant_adresse=sous_traitant_adresse,
        sous_traitant_email=sous_traitant_email,
        acceptee_par=f"{utilisateur.first_name} {utilisateur.last_name}".strip() or utilisateur.email,
        acceptee_le=acceptee_le.strftime("%d/%m/%Y à %H:%M"),
        url_convention=f"{base_url.rstrip('/')}/convention-sous-traitance",
        url_rgpd=f"{base_url.rstrip('/')}/rgpd",
        url_mentions_legales=f"{base_url.rstrip('/')}/mentions-legales",
    )
