"""Formulaires de terrain : composer un questionnaire, le faire remplir, relire les réponses.

Demande du 17/11/2026, après comparaison avec KoboToolbox (l'outil de collecte de la
Croix-Rouge et de MSF) : « porte la fonctionnalité dans l'application, mais pas visible de
tous — compte collectivité seulement, ou délégué seulement ».

Ce qu'on reprend de l'idée, et rien de plus :

- **un questionnaire que la collectivité compose elle-même**, sans développeur : une liste de
  questions typées, avec caractère obligatoire, bornes, et une condition d'affichage simple
  (« seulement si telle réponse vaut telle valeur ») ;
- **une saisie qui survit à l'absence de réseau** : chaque réponse porte un identifiant tiré
  sur l'appareil, de sorte qu'un renvoi après coupure ne crée pas de doublon ;
- **des réponses qu'on relit et qu'on exporte** (CSV pour un tableur, GeoJSON pour une carte).

Ce qu'on ne reprend pas : le standard XLSForm, les groupes répétés, les calculs. Un
questionnaire d'évaluation de dégâts ou de recensement de besoins tient sans eux.

**Qui y accède.** La collectivité compose, lit et exporte. Une institution à qui elle a
délégué une compétence (convention active, `DelegationCompetence`) voit ses questionnaires et
y répond, mais ne relit que ses propres réponses. Personne d'autre.

**Rien en clair** : les réponses sont chiffrées en base. Seule la position reste lisible, comme
partout dans l'application, parce que PostGIS doit pouvoir la lire.
"""
import csv
import io
import json
import re
from datetime import date

TYPES = {
    "TEXTE": "Texte court",
    "TEXTE_LONG": "Texte long",
    "NOMBRE": "Nombre",
    "OUI_NON": "Oui / non",
    "CHOIX": "Un choix dans une liste",
    "CHOIX_MULTIPLE": "Plusieurs choix dans une liste",
    "DATE": "Date",
}
MAX_QUESTIONS = 60
MAX_OPTIONS = 40
_CLE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class ErreurFormulaire(ValueError):
    """Questionnaire ou réponse refusés ; le message est fait pour être lu."""


def _cle_depuis(libelle, prises):
    base = re.sub(r"[^a-z0-9]+", "_", _sans_accents(libelle).lower()).strip("_")[:30] or "question"
    if not base[0].isalpha():
        base = "q_" + base
    cle, n = base, 2
    while cle in prises:
        cle, n = f"{base[:36]}_{n}", n + 1
    return cle


def _sans_accents(texte):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(texte)) if unicodedata.category(c) != "Mn")


def nettoyer_questions(questions) -> list:
    """Le questionnaire tel qu'on le range, ou ErreurFormulaire.

    Les clés sont générées depuis les libellés quand elles manquent, et ne changent plus
    ensuite : ce sont elles qui rattachent une réponse déjà saisie à sa question."""
    if not isinstance(questions, list) or not questions:
        raise ErreurFormulaire("Un questionnaire contient au moins une question.")
    if len(questions) > MAX_QUESTIONS:
        raise ErreurFormulaire(f"Un questionnaire ne dépasse pas {MAX_QUESTIONS} questions.")

    propres, prises = [], set()
    for rang, brute in enumerate(questions, start=1):
        if not isinstance(brute, dict):
            raise ErreurFormulaire(f"Question {rang} : format inattendu.")
        libelle = str(brute.get("libelle") or "").strip()[:200]
        if not libelle:
            raise ErreurFormulaire(f"Question {rang} : il manque son intitulé.")
        type_question = brute.get("type")
        if type_question not in TYPES:
            raise ErreurFormulaire(f"« {libelle} » : type de question inconnu.")
        cle = str(brute.get("cle") or "").strip()
        if not cle:
            cle = _cle_depuis(libelle, prises)
        if not _CLE.match(cle) or cle in prises:
            raise ErreurFormulaire(f"« {libelle} » : identifiant de question invalide ou en double.")
        prises.add(cle)

        question = {"cle": cle, "libelle": libelle, "type": type_question,
                    "obligatoire": bool(brute.get("obligatoire"))}
        aide = str(brute.get("aide") or "").strip()[:300]
        if aide:
            question["aide"] = aide

        if type_question in ("CHOIX", "CHOIX_MULTIPLE"):
            options = [str(o).strip()[:100] for o in (brute.get("options") or []) if str(o).strip()]
            options = list(dict.fromkeys(options))
            if len(options) < 2:
                raise ErreurFormulaire(f"« {libelle} » : une liste propose au moins deux choix.")
            if len(options) > MAX_OPTIONS:
                raise ErreurFormulaire(f"« {libelle} » : pas plus de {MAX_OPTIONS} choix.")
            question["options"] = options

        if type_question == "NOMBRE":
            for borne in ("min", "max"):
                valeur = brute.get(borne)
                if valeur not in (None, ""):
                    try:
                        question[borne] = float(valeur)
                    except (TypeError, ValueError):
                        raise ErreurFormulaire(f"« {libelle} » : la borne {borne} n'est pas un nombre.")
            if "min" in question and "max" in question and question["min"] > question["max"]:
                raise ErreurFormulaire(f"« {libelle} » : le minimum dépasse le maximum.")

        condition = brute.get("si")
        if condition:
            # Une question ne dépend que d'une question PRÉCÉDENTE : c'est ce qui garantit
            # qu'aucune boucle de conditions ne peut se former.
            source = next((q for q in propres if q["cle"] == condition.get("cle")), None)
            if source is None:
                raise ErreurFormulaire(
                    f"« {libelle} » : sa condition doit porter sur une question placée avant elle.")
            question["si"] = {"cle": source["cle"], "valeur": condition.get("valeur")}
        propres.append(question)
    return propres


def _visible(question, reponses) -> bool:
    condition = question.get("si")
    if not condition:
        return True
    valeur = reponses.get(condition["cle"])
    attendue = condition.get("valeur")
    if isinstance(valeur, list):
        return attendue in valeur
    return valeur == attendue


def nettoyer_reponses(questions, donnees) -> dict:
    """Les réponses telles qu'on les range, ou ErreurFormulaire.

    Une question masquée par sa condition n'est pas exigée, et ce qu'on y aurait répondu est
    écarté : on ne garde pas une réponse à une question qui n'a pas été posée."""
    if not isinstance(donnees, dict):
        raise ErreurFormulaire("Réponses illisibles.")
    connues = {q["cle"] for q in questions}
    inconnues = sorted(set(donnees) - connues)
    if inconnues:
        raise ErreurFormulaire("Réponse à une question inconnue : " + ", ".join(inconnues))

    propres = {}
    for question in questions:
        if not _visible(question, propres):
            continue
        cle, libelle, brute = question["cle"], question["libelle"], donnees.get(question["cle"])
        vide = brute is None or brute == "" or brute == []
        if vide:
            if question["obligatoire"]:
                raise ErreurFormulaire(f"« {libelle} » attend une réponse.")
            continue
        type_question = question["type"]
        if type_question in ("TEXTE", "TEXTE_LONG"):
            propres[cle] = str(brute).strip()[: 200 if type_question == "TEXTE" else 4000]
        elif type_question == "NOMBRE":
            try:
                nombre = float(str(brute).replace(",", "."))
            except (TypeError, ValueError):
                raise ErreurFormulaire(f"« {libelle} » attend un nombre.")
            if "min" in question and nombre < question["min"]:
                raise ErreurFormulaire(f"« {libelle} » : au moins {question['min']:g}.")
            if "max" in question and nombre > question["max"]:
                raise ErreurFormulaire(f"« {libelle} » : au plus {question['max']:g}.")
            propres[cle] = int(nombre) if nombre.is_integer() else nombre
        elif type_question == "OUI_NON":
            if not isinstance(brute, bool):
                raise ErreurFormulaire(f"« {libelle} » attend oui ou non.")
            propres[cle] = brute
        elif type_question == "CHOIX":
            if brute not in question["options"]:
                raise ErreurFormulaire(f"« {libelle} » : choix inconnu.")
            propres[cle] = brute
        elif type_question == "CHOIX_MULTIPLE":
            if not isinstance(brute, list) or any(b not in question["options"] for b in brute):
                raise ErreurFormulaire(f"« {libelle} » : choix inconnu.")
            propres[cle] = [o for o in question["options"] if o in brute]
        elif type_question == "DATE":
            try:
                propres[cle] = date.fromisoformat(str(brute)[:10]).isoformat()
            except ValueError:
                raise ErreurFormulaire(f"« {libelle} » attend une date.")
    return propres


def _en_texte(valeur) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, bool):
        return "oui" if valeur else "non"
    if isinstance(valeur, list):
        return " ; ".join(str(v) for v in valeur)
    return str(valeur)


def lignes(formulaire, reponses, nommer) -> list:
    """Les réponses déchiffrées, une par ligne, prêtes à afficher ou à exporter."""
    resultat = []
    for reponse in reponses:
        try:
            donnees = json.loads(reponse.donnees or "{}")
        except ValueError:
            donnees = {}
        resultat.append({
            "id": str(reponse.id),
            "saisie_le": reponse.saisie_le or reponse.date_reception,
            "recue_le": reponse.date_reception,
            "auteur": nommer(reponse.auteur) if reponse.auteur_id else "",
            "institution": reponse.institution_auteur.nom if reponse.institution_auteur_id else "",
            "latitude": reponse.location.y if reponse.location else None,
            "longitude": reponse.location.x if reponse.location else None,
            "donnees": donnees,
        })
    return resultat


def en_csv(formulaire, tableau) -> str:
    """Pour un tableur : point-virgule et BOM, ce qu'Excel et LibreOffice ouvrent sans réglage."""
    sortie = io.StringIO()
    ecrire = csv.writer(sortie, delimiter=";")
    ecrire.writerow(["Saisie le", "Par", "Institution", "Latitude", "Longitude"]
                    + [q["libelle"] for q in formulaire.questions])
    for ligne in tableau:
        saisie = ligne["saisie_le"]
        ecrire.writerow(
            [saisie.strftime("%d/%m/%Y %H:%M") if saisie else "", ligne["auteur"], ligne["institution"],
             ligne["latitude"] if ligne["latitude"] is not None else "",
             ligne["longitude"] if ligne["longitude"] is not None else ""]
            + [_en_texte(ligne["donnees"].get(q["cle"])) for q in formulaire.questions]
        )
    return "﻿" + sortie.getvalue()


def en_geojson(formulaire, tableau) -> dict:
    """Pour une carte (QGIS, uMap) : seules les réponses situées, avec les intitulés en clair."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [ligne["longitude"], ligne["latitude"]]},
                "properties": {
                    "saisie_le": ligne["saisie_le"].isoformat() if ligne["saisie_le"] else None,
                    "par": ligne["auteur"],
                    **{q["libelle"]: _en_texte(ligne["donnees"].get(q["cle"])) for q in formulaire.questions},
                },
            }
            for ligne in tableau if ligne["latitude"] is not None
        ],
    }


# ── Qui y accède ───────────────────────────────────────────────────────────────────────────

def institutions_gerees(request) -> set:
    """Les collectivités dont l'appelant compose et relit les questionnaires."""
    from .models import TYPES_COLLECTIVITE_TERRITORIALE, Institution, UserRole
    from .perimetre_admin import institution_regardee, institutions_visibles
    from .permissions import effective_role_or_none

    role = effective_role_or_none(request)
    if role == UserRole.ADMINISTRATOR:
        visibles = institutions_visibles(request)
        institutions = Institution.objects.all() if visibles is None else Institution.objects.filter(id__in=visibles)
    elif role == UserRole.LOCAL_AUTHORITY:
        institution = institution_regardee(request)
        institutions = Institution.objects.filter(id=institution.id) if institution else Institution.objects.none()
    else:
        return set()
    return {
        i.id for i in institutions.select_related("type")
        if (getattr(i.type, "code", "") or "").upper() in TYPES_COLLECTIVITE_TERRITORIALE
    }


def institutions_delegantes(request) -> set:
    """Les collectivités qui ont délégué une compétence à l'institution de l'appelant
    (convention active) : il voit leurs questionnaires et y répond."""
    from django.db.models import Q
    from django.utils import timezone

    from .models import DelegationCompetence
    from .perimetre_admin import institution_regardee

    institution = institution_regardee(request)
    if institution is None:
        return set()
    return set(
        DelegationCompetence.objects.filter(institution_cible=institution, active=True)
        .filter(Q(date_fin__isnull=True) | Q(date_fin__gt=timezone.now()))
        .exclude(institution_source=institution)
        .values_list("institution_source_id", flat=True)
    )
