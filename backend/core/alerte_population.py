"""L'alerte de la commune à ses habitants : à qui, par quels canaux, et ce qu'elle est devenue.

Demande de Sylvain du 16/11/2026 : « prépare l'alerte aux habitants, par défaut via Matrix, via
l'application, prépare l'idée SMS ou mail, et aussi l'API vers IntraMuros (clé API propre à
chaque collectivité) ».

**Ce n'est pas l'alerte officielle.** FR-Alert relève du préfet. Ici, la commune écrit à ceux
qui ont demandé à recevoir ses alertes (`AbonnementAlerte`) et aux personnes déjà touchées par
la crise (`User.affected_crisis`). On n'écrit pas à quelqu'un parce qu'il habite là : le
consentement fait la liste.

**Sept canaux, sur le même registre que les campagnes** (`core/canaux_campagne.py`) :

| Canal | État | Par défaut |
|---|---|---|
| Messagerie (Matrix) | en service : un message privé à chaque personne qui s'y est connectée | oui |
| Application mobile | en service : une notification urgente, avec son suivi (reçue, vue, lue) | oui |
| Courriel | en service, à cocher : par l'adresse de la collectivité si elle en a une | non |
| SMS | en service, à cocher : seulement si la collectivité a un fournisseur, et il se paie | non |
| Radio MeshCore, radio Meshtastic | en service, à cocher : sur le canal radio de la commune, s'il existe | non |
| IntraMuros | **préparé, pas branché** : la clé de la collectivité se range, l'appel attend la documentation de leur API | non |

**IntraMuros n'est pas implémenté, et c'est volontaire** -- même position que pour Mobimel
(core/envoi_sms.py). Aucune documentation publique de leur API n'a pu être trouvée (recherche du
16/11/2026) : ni adresse, ni paramètres, ni forme d'authentification. Écrire l'appel sur des
suppositions donnerait du code qui a l'air juste, qui échoue au premier envoi réel, et qui
enverrait la clé d'une commune à une adresse inventée. Tout le reste est prêt : il manque une
fonction, `_envoyer_intramuros`, à écrire le jour où la documentation est là.

**Radio MeshCore et Meshtastic** : l'alerte peut aussi être diffusée sur le canal radio DE LA
COMMUNE (les canaux de la collectivité qui ne sont pas ceux d'une équipe). Elle passe alors sans
Internet ni réseau mobile ; on ne sait pas qui écoute, donc ce canal n'annonce aucun nombre.

**En zone de démonstration, l'alerte ne part qu'à celui qui l'envoie** (règle de Sylvain,
16/11/2026) : il constate le fonctionnement sans qu'aucun habitant reçoive une fausse alerte. La
radio ne part pas : une diffusion ne se limite pas à une personne.
"""
import logging

from django.db.models import Q

from .models import AbonnementAlerte, AlertePopulation, Environment, GenreNotification, User

logger = logging.getLogger(__name__)

MATRIX, APPLICATION, EMAIL, SMS, INTRAMUROS = "MATRIX", "APPLICATION", "EMAIL", "SMS", "INTRAMUROS"
MESHCORE, MESHTASTIC = "MESHCORE", "MESHTASTIC"

#: Un message radio tient en peu d'octets : au-delà, il part en plusieurs paquets, et chacun
#: occupe le canal de tout le monde. On dit l'essentiel.
LONGUEUR_RADIO = 200

#: Dans l'ordre où l'écran les propose. `defaut` : coché d'office.
CANAUX = [
    {"code": MATRIX, "libelle": "Messagerie (Matrix)", "defaut": True,
     "detail": "Gratuit et immédiat. Ne touche que les personnes qui se sont déjà connectées à la messagerie."},
    {"code": APPLICATION, "libelle": "Application mobile", "defaut": True,
     "detail": "Gratuit, et le seul canal qui dit ce que le message est devenu : reçu, vu, lu. "
               "Application fermée, la notification peut mettre jusqu'à un quart d'heure à sonner."},
    {"code": EMAIL, "libelle": "Courriel", "defaut": False,
     "detail": "Part à tous ceux qui ont une adresse. Lu moins vite : en complément, pas en premier."},
    {"code": SMS, "libelle": "SMS", "defaut": False,
     "detail": "Lu presque à coup sûr, et sans connexion. Il se paie : il faut un fournisseur SMS configuré pour la collectivité."},
    {"code": MESHCORE, "libelle": "Radio MeshCore", "defaut": False,
     "detail": "Diffusé sur le canal radio de la commune : il passe sans Internet ni réseau mobile, pour qui a un appareil à l'écoute."},
    {"code": MESHTASTIC, "libelle": "Radio Meshtastic", "defaut": False,
     "detail": "Diffusé sur le canal radio de la commune : il passe sans Internet ni réseau mobile, pour qui a un appareil à l'écoute."},
    {"code": INTRAMUROS, "libelle": "IntraMuros", "defaut": False,
     "detail": "Publierait l'alerte dans l'application IntraMuros de la collectivité, avec sa propre clé."},
]
CODES = [c["code"] for c in CANAUX]
PAR_DEFAUT = [c["code"] for c in CANAUX if c["defaut"]]

INTRAMUROS_PAS_BRANCHE = ("IntraMuros n'est pas encore branché : la clé de la collectivité est rangée, mais l'envoi "
                          "attend la documentation de leur API.")


def destinataires(institution, crise, environment):
    """Qui reçoit l'alerte : les abonnés de la collectivité, et les personnes touchées par la
    crise. Comptes actifs seulement, chacun une fois."""
    filtre = Q(abonnements_alerte__institution=institution, abonnements_alerte__actif=True,
               abonnements_alerte__environment=environment)
    if crise is not None:
        filtre |= Q(affected_crisis=crise)
    return User.objects.filter(filtre, is_active=True).distinct()


def _configuration(institution):
    from .envoi_institution import configuration_envoi
    return configuration_envoi(institution)


def canaux_radio(institution, crise, environment):
    """Les canaux radio de la COMMUNE : ceux de la collectivité qui ne sont pas le canal d'une
    équipe -- une alerte aux habitants n'a rien à faire sur le canal de travail d'une équipe.
    Un canal ouvert pour une crise ne sert qu'à cette crise. Rend `(meshcore, meshtastic)`."""
    from .models import CanalMeshCore, CanalMeshtastic

    def de_la_commune(modele):
        canaux = modele.objects.filter(institution=institution, environment=environment, actif=True, equipe__isnull=True)
        return canaux.filter(Q(crise__isnull=True) | Q(crise=crise)) if crise is not None else canaux.filter(crise__isnull=True)

    return de_la_commune(CanalMeshCore), de_la_commune(CanalMeshtastic)


def disponibilite(institution, crise=None, environment=None) -> dict:
    """Pour chaque canal : peut-on s'en servir pour cette collectivité, et sinon pourquoi."""
    config = _configuration(institution)
    etat = {MATRIX: (True, ""), APPLICATION: (True, ""), EMAIL: (True, "")}
    meshcore, meshtastic = canaux_radio(institution, crise, environment or Environment.PROD)
    for code, canaux, nom in ((MESHCORE, meshcore, "MeshCore"), (MESHTASTIC, meshtastic, "Meshtastic")):
        present = canaux.exists()
        etat[code] = (present, "" if present else f"La commune n'a pas de canal {nom} à elle (hors canaux d'équipe).")
    sms_pret = bool(config is not None and getattr(config, "sms_configure", False))
    etat[SMS] = (sms_pret, "" if sms_pret else "Aucun fournisseur SMS n'est configuré pour la collectivité.")
    cle = bool(config is not None and config.intramuros_cle_api)
    etat[INTRAMUROS] = (False, INTRAMUROS_PAS_BRANCHE if cle else
                        "La clé IntraMuros de la collectivité n'est pas renseignée, et l'envoi n'est pas encore branché.")
    return etat


def moyens_de_terrain(institution, environment) -> list:
    """Les moyens d'alerte de terrain que la commune a décrits dans son plan (« Alerte de la
    population ») : c'est ICI qu'on les déclenche, c'est LÀ-BAS qu'on les décrit.

    Pour chacun : qui le déclenche ou le relaie, et si le message peut lui être envoyé par SMS
    (il faut son numéro, et un fournisseur SMS configuré pour la collectivité)."""
    from .models import DossierPCS, MoyenAlertePCS
    from .pcs_fiches import fiche_moyen

    dossier = DossierPCS.objects.filter(institution=institution, environment=environment).first()
    if dossier is None:
        return []
    config = _configuration(institution)
    sms_pret = bool(config is not None and getattr(config, "sms_configure", False))
    moyens = []
    for moyen in MoyenAlertePCS.objects.filter(dossier=dossier).select_related("zone").prefetch_related("pieces"):
        telephone = (moyen.personne_telephone or "").strip()
        if not telephone:
            motif = "Aucun numéro n'est noté pour ce moyen : appelez la personne, ou complétez sa fiche."
        elif not sms_pret:
            motif = "Aucun fournisseur SMS n'est configuré pour la collectivité : appelez-la."
        else:
            motif = ""
        moyens.append({
            "id": str(moyen.id), "type": moyen.type, "type_libelle": moyen.get_type_display(),
            "description": moyen.description, "zone_nom": moyen.zone.nom if moyen.zone_id else "",
            "personne": moyen.personne or "", "personne_telephone": telephone,
            "peut_relayer": bool(telephone and sms_pret), "motif_relais": motif,
            # Ce qu'on fait quand on le déclenche : la fiche de la commune, sinon la fiche type.
            "consignes": (moyen.consignes or "").strip() or fiche_moyen(moyen.type),
            "fiche_propre": bool((moyen.consignes or "").strip()),
            "pieces": len(moyen.pieces.all()),
        })
    return moyens


def declencher_sur_le_terrain(request, institution, crise, titre, message, identifiants, relayer, environment) -> list:
    """Inscrit la demande de déclenchement de chaque moyen coché, et envoie le message à relayer
    à ceux pour qui on l'a demandé.

    On ne déclenche pas une sirène depuis un écran : on DEMANDE son déclenchement à quelqu'un,
    et on en garde la trace. Chaque demande va à la main courante et, s'il y a une crise, à son
    journal de bord — c'est ce qu'on relira pour savoir qui a été prévenu, et quand."""
    from .audit import audit_log
    from .envoi_sms import envoyer_sms_pour_institution
    from .models import JournalCollectivite

    demonstration = environment == Environment.DEMO
    choisis = {m["id"]: m for m in moyens_de_terrain(institution, environment)}
    actions = []
    for identifiant in [str(i) for i in (identifiants or [])]:
        moyen = choisis.get(identifiant)
        if moyen is None:
            continue                        # un moyen d'une autre commune, ou retiré entre-temps
        action = {"moyen": identifiant, "type": moyen["type"], "type_libelle": moyen["type_libelle"],
                  "description": moyen["description"], "personne": moyen["personne"], "relais": "", "note": ""}
        if identifiant in {str(r) for r in (relayer or [])}:
            if demonstration:
                action["note"] = "Zone de démonstration : aucun SMS n'est parti."
            elif not moyen["peut_relayer"]:
                action["note"] = moyen["motif_relais"]
            else:
                reussi, detail = envoyer_sms_pour_institution(institution, moyen["personne_telephone"], f"{titre} — {message}"[:160])
                action["relais"] = "message envoyé par SMS" if reussi else ""
                if not reussi:
                    action["note"] = f"Le SMS n'est pas parti ({detail}) : appelez la personne."
        actions.append(action)
        # Ni le texte de l'alerte ni un numéro : le fait, le moyen, et s'il a été relayé.
        fait = f"Alerte « {titre} » : {moyen['type_libelle']}" + (f" ({moyen['description']})" if moyen["description"] else "") \
            + " — déclenchement demandé" + (f", {action['relais']}" if action["relais"] else "")
        audit_log(request=request, action_code="MODIFICATION", objet_type="MoyenAlertePCS", objet_id=identifiant,
                  crise=crise, commentaire=fait)
        if crise is not None:
            JournalCollectivite.objects.create(
                institution=institution, crise=crise, auteur=request.user, environment=environment,
                contenu=fait + (f" à {moyen['personne']}" if moyen["personne"] else "") + ".")
    return actions


def apercu(institution, crise, environment) -> dict:
    """Ce que l'écran montre AVANT d'envoyer : combien de personnes, et combien par canal."""
    from .notifications_application import joignables_par_application

    personnes = list(destinataires(institution, crise, environment).only("id", "email", "phone_number"))
    par_application = joignables_par_application([p.id for p in personnes])
    joignables = {
        # Estimation haute, comme pour les campagnes : savoir qui s'est connecté à la messagerie
        # demanderait un appel réseau par personne.
        MATRIX: len(personnes),
        APPLICATION: len(par_application),
        EMAIL: sum(1 for p in personnes if p.email),
        SMS: sum(1 for p in personnes if p.phone_number),
        INTRAMUROS: None,   # IntraMuros publie à ses propres abonnés : nous ne les comptons pas
        MESHCORE: None,     # la radio est une diffusion : on ne sait pas qui écoute
        MESHTASTIC: None,
    }
    etat = disponibilite(institution, crise, environment)
    return {
        "destinataires": len(personnes),
        "canaux": [
            {**canal, "disponible": etat[canal["code"]][0], "motif": etat[canal["code"]][1],
             "joignables": joignables[canal["code"]]}
            for canal in CANAUX
        ],
        "terrain": moyens_de_terrain(institution, environment),
    }


def _envoyer_intramuros(cle_api, titre, message):
    """À écrire avec la documentation de l'API IntraMuros. Voir le module : aucun appel n'est
    fait sur des suppositions."""
    raise NotImplementedError(INTRAMUROS_PAS_BRANCHE)


def envoyer(request, institution, crise, titre, message, canaux, urgent=True, terrain=None, relayer=None) -> AlertePopulation:
    """Envoie l'alerte sur les canaux retenus et enregistre ce qu'elle est devenue.

    Un canal qui échoue pour une personne n'arrête ni les autres canaux ni les autres
    personnes : une alerte doit partir par ce qui marche.

    **En zone de démonstration, l'alerte ne part qu'à celui qui l'envoie** : il constate que
    tout fonctionne -- la notification sonne, le message arrive -- sans qu'aucun habitant ne
    reçoive une fausse alerte. La radio, elle, ne part pas du tout : une diffusion ne se limite
    pas à une personne."""
    from .permissions import get_active_environment

    environment = get_active_environment(request)
    demonstration = environment == Environment.DEMO
    canaux = [c for c in CODES if c in set(canaux)]
    personnes = list(destinataires(institution, crise, environment))
    etat = disponibilite(institution, crise, environment)
    bilan = {code: {"partis": 0, "echecs": 0, "note": ""} for code in canaux}
    texte = f"{titre}\n\n{message}"

    for code in canaux:
        if not etat[code][0]:
            bilan[code]["note"] = etat[code][1]
    actifs = [code for code in canaux if etat[code][0]]

    for code in [c for c in actifs if c in (MESHCORE, MESHTASTIC)]:
        if demonstration:
            bilan[code]["note"] = "Zone de démonstration : la radio ne part pas (une diffusion ne se limite pas à vous)."
            continue
        try:
            bilan[code]["partis"] = _diffuser_radio(request, institution, crise, code, titre, message, environment)
        except Exception:  # noqa: BLE001 -- un canal en panne ne doit pas arrêter l'alerte
            logger.exception("Alerte aux habitants : échec du canal %s", code)
            bilan[code]["echecs"] += 1

    # En démonstration, un seul destinataire réel : l'expéditeur.
    a_joindre = [request.user] if demonstration else personnes
    for personne in a_joindre:
        for code in [c for c in actifs if c not in (MESHCORE, MESHTASTIC)]:
            try:
                if _envoyer_a(request, institution, personne, code, titre, message, texte, urgent, environment):
                    bilan[code]["partis"] += 1
            except Exception:  # noqa: BLE001 -- un canal en panne ne doit pas arrêter l'alerte
                logger.exception("Alerte aux habitants : échec du canal %s", code)
                bilan[code]["echecs"] += 1
    if demonstration:
        for code in [c for c in actifs if c not in (MESHCORE, MESHTASTIC)]:
            bilan[code]["note"] = "Zone de démonstration : envoyé à vous seul, pour constater le fonctionnement."

    actions = declencher_sur_le_terrain(request, institution, crise, titre, message, terrain, relayer, environment)
    alerte = AlertePopulation.objects.create(
        institution=institution, crise=crise, titre=titre, message=message, urgent=urgent, canaux=canaux,
        bilan=bilan, destinataires=len(personnes), auteur=request.user, environment=environment, terrain=actions,
    )
    if crise is not None and canaux:
        # Le journal de bord de la crise garde aussi l'envoi lui-même, pas seulement le terrain.
        from .models import JournalCollectivite
        JournalCollectivite.objects.create(
            institution=institution, crise=crise, auteur=request.user, environment=environment,
            contenu=f"Alerte « {titre} » envoyée à {len(personnes)} destinataire(s) par : "
                    + ", ".join(f"{code} ({bilan[code]['partis']})" for code in canaux) + ".")
    from .audit import audit_log
    audit_log(
        request=request, action_code="ENVOI_MASSE", objet_type="AlertePopulation", objet_id=alerte.id, crise=crise,
        # Ni le texte ni les destinataires : le fait, le nombre, les canaux.
        commentaire=f"Alerte aux habitants de « {institution.nom} » : {len(personnes)} destinataire(s), "
                    + ", ".join(f"{code} {bilan[code]['partis']}" for code in canaux),
    )
    return alerte


def _diffuser_radio(request, institution, crise, code, titre, message, environment) -> int:
    """Dépose l'alerte sur les canaux radio de la commune ; les ponts l'émettent. Rend le nombre
    de canaux servis. Le texte est raccourci : la radio se paie en temps d'antenne."""
    from .models import DirectionMessageMesh, MessageCanalMeshCore, MessageCanalMeshtastic, StatutMessageMesh

    meshcore, meshtastic = canaux_radio(institution, crise, environment)
    canaux, modele = (meshcore, MessageCanalMeshCore) if code == MESHCORE else (meshtastic, MessageCanalMeshtastic)
    texte = f"ALERTE {titre} : {' '.join(message.split())}"[:LONGUEUR_RADIO]
    servis = 0
    for canal in canaux:
        modele.objects.create(canal=canal, direction=DirectionMessageMesh.SORTANT, expediteur=request.user,
                              contenu=texte, statut=StatutMessageMesh.EN_ATTENTE, environment=canal.environment)
        servis += 1
    return servis


def _envoyer_a(request, institution, personne, code, titre, message, texte, urgent, environment) -> bool:
    """Un message, à une personne, par un canal. Vrai s'il est parti."""
    if code == MATRIX:
        from .matrix import envoyer_dm
        # Silencieux si la personne ne s'est jamais connectée à la messagerie : c'est pourquoi
        # ce canal est annoncé comme une estimation haute.
        envoyer_dm(personne, texte)
        return True
    if code == APPLICATION:
        from .notifications_application import notifier
        return notifier(personne, GenreNotification.INFORMATION, titre, message, urgent=urgent,
                        institution=institution, environment=environment) is not None
    if code == EMAIL:
        if not personne.email:
            return False
        from .branding import send_branded_mail
        send_branded_mail(request, institution, titre, message + "\n\n{signature}", [personne.email], fail_silently=False)
        return True
    if code == SMS:
        if not personne.phone_number:
            return False
        from .envoi_sms import envoyer_sms_pour_institution
        # 160 caractères : au-delà, l'opérateur facture un second message.
        parti, _motif = envoyer_sms_pour_institution(institution, personne.phone_number, texte[:160])
        return bool(parti)
    return False
