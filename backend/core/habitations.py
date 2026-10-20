"""Contrôle d'accès au référencement des dégâts (Habitation) -- réservé aux collectivités
locales sur leur propre commune, ou à une association ayant reçu une délégation explicite
(DelegationCompetence) sur la compétence "Évaluation des dégâts" pour la commune concernée.
Distinct de zone_scoping.py (qui ne couvre que le secteur naturel de l'institution de
l'appelant) : une association SECOURS n'a normalement AUCUN secteur géographique propre, sa
seule légitimité ici vient d'une délégation explicite reçue pour cette commune précise."""
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.db.models import Q
from django.utils import timezone

from .models import Competence, DelegationCompetence, UserRole

NOM_COMPETENCE_EVALUATION_DEGATS = "Évaluation des dégâts"


def _departement_code(commune_code: str) -> str:
    # Départements outre-mer (971-976) sur 3 chiffres, métropole (dont Corse 2A/2B) sur les
    # 2 premiers caractères -- même convention que le reste de l'appli (Commune.departement_code).
    if not commune_code:
        return ""
    if commune_code[:2] == "97" or commune_code[:2] == "98":
        return commune_code[:3]
    return commune_code[:2]


# Importée telle quelle par core/vulnerabilites.py (registre des personnes vulnérables, même
# logique de couverture géographique d'une délégation) -- un changement de signature ici doit
# être répercuté là-bas aussi.
def _delegation_couvre_commune(delegation: DelegationCompetence, commune_code: str) -> bool:
    if delegation.communes and commune_code in delegation.communes:
        return True
    if delegation.departements and _departement_code(commune_code) in delegation.departements:
        return True
    if not delegation.communes and not delegation.departements and delegation.zone_precise is None:
        # Aucune restriction posée sur la délégation = toute la crise associée (cohérent avec
        # le commentaire du modèle : "la mairie peut déléguer une compétence sur toute la
        # crise, ou la restreindre").
        return True
    if delegation.zone_precise is not None:
        from .models import Commune
        commune = Commune.objects.filter(code=commune_code).first()
        if commune and commune.centre_latitude is not None and commune.centre_longitude is not None:
            from django.contrib.gis.geos import Point
            point = Point(commune.centre_longitude, commune.centre_latitude, srid=4326)
            return delegation.zone_precise.contains(point)
    return False


def _institution_couvre_commune(institution, commune_code: str) -> bool:
    """Vrai si la commune tombe dans le SECTEUR effectif de l'institution (sa commune, son EPCI,
    son département ou sa région), pas seulement sa commune exacte -- même découpage que
    SECTEUR_CHAMP_PAR_NIVEAU (zone_scoping). Une AUT_LOCALE de niveau département (ex: Conseil
    départemental) couvre ainsi toutes les communes de son département."""
    niveau = institution.secteur_niveau_effectif
    if niveau == "national":
        return True
    if not niveau or niveau == "commune":
        return bool(institution.commune_code) and institution.commune_code == commune_code
    if niveau == "departement":
        # Pur calcul de chaîne (pas d'appel réseau) -- cas le plus courant.
        return bool(institution.departement_code) and institution.departement_code == _departement_code(commune_code)
    from .geo_lookup import commune_secteur_codes
    secteurs = commune_secteur_codes(commune_code)
    champ = {"epci": "epci_code", "region": "region_code"}.get(niveau)
    if champ is None:
        return False
    code_institution = getattr(institution, champ, None)
    return bool(code_institution) and code_institution == secteurs.get(champ)


def peut_simuler_commune(request, commune_code: str) -> bool:
    """Accès à l'outil « Simulation d'inondation » (planification préventive, PAS liée à une
    crise -- distinct d'institution_accede_commune, qui vise le référencement des dégâts commune
    par commune). Un acteur institutionnel couvre tout son SECTEUR (correctif du 20/10/2026 : un
    Conseil départemental voit toutes les communes de son département, pas seulement sa commune
    siège). En DEMO, il peut simuler n'importe quelle commune -- les jeux de démonstration sont
    répartis sur plusieurs départements, même raison que la portée nationale des SDIS en démo."""
    from .models import Environment, UserRole
    from .permissions import INSTITUTIONAL_TYPES, get_active_environment, get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return False
    role = get_effective_role(request)
    if role == UserRole.ADMINISTRATOR:
        return True
    if role not in INSTITUTIONAL_TYPES:
        return False
    if get_active_environment(request) == Environment.DEMO:
        return True
    institution = getattr(user, "institution", None)
    if institution is None:
        return False
    return _institution_couvre_commune(institution, commune_code)


def institution_accede_commune(request, commune_code: str, crise=None) -> bool:
    """True si l'institution de l'appelant peut gérer les habitations de `commune_code` --
    ADMINISTRATOR voit toujours tout, une AUT_LOCALE sur sa propre commune, une institution
    (association comprise) avec une délégation active sur cette compétence pour cette commune.

    `crise`, si fourni, ajoute une condition supplémentaire : le module "Estimation des dégâts"
    doit avoir été explicitement activé (ModuleDegatsCrise.actif=True) par CETTE institution
    POUR CETTE crise -- désactivé par défaut, voir ModuleDegatsCrise.__doc__. ADMINISTRATOR
    reste exempté (il doit pouvoir dépanner même un module non activé)."""
    from .permissions import get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return False

    role = get_effective_role(request)
    if role == UserRole.ADMINISTRATOR:
        return True
    if not commune_code:
        return False

    institution = getattr(user, "institution", None)
    if institution is None:
        return False

    if crise is not None:
        from .models import ModuleDegatsCrise
        if not ModuleDegatsCrise.objects.filter(crise=crise, institution=institution, actif=True).exists():
            return False

    if role == UserRole.LOCAL_AUTHORITY and institution.commune_code == commune_code:
        return True

    delegations = DelegationCompetence.objects.filter(
        institution_cible=institution,
        competence__nom=NOM_COMPETENCE_EVALUATION_DEGATS,
        active=True,
    ).filter(Q(date_fin__isnull=True) | Q(date_fin__gt=timezone.now()))
    return any(_delegation_couvre_commune(d, commune_code) for d in delegations)


def commune_dans_zone_module(commune_code: str, location, module) -> bool:
    """True si `commune_code`/`location` tombe dans la zone que `module` (ModuleDegatsCrise) a
    définie pour restreindre où charger des points -- True si `module.zone` est vide (aucune
    restriction posée, seule institution_accede_commune s'applique). Même logique de
    containment que _delegation_couvre_commune (liste de communes, ou polygone dessiné avec le
    point de l'habitation ou, à défaut, le centre de la commune)."""
    zone = module.zone
    if zone is None:
        return True
    if zone.communes and commune_code in zone.communes:
        return True
    polygone = perimetre_zone_nommee(zone)
    if polygone is not None:
        if location is not None:
            return polygone.contains(location)
        from .models import Commune
        commune = Commune.objects.filter(code=commune_code).first()
        if commune and commune.centre_latitude is not None and commune.centre_longitude is not None:
            from django.contrib.gis.geos import Point
            point = Point(commune.centre_longitude, commune.centre_latitude, srid=4326)
            return polygone.contains(point)
    return False


def communes_accessibles(request) -> list | None:
    """Liste des codes commune gérables par l'appelant, pour filtrer un queryset Habitation --
    `None` signifie "toutes" (ADMINISTRATOR). Liste vide = aucun accès."""
    from .permissions import get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return []

    role = get_effective_role(request)
    if role == UserRole.ADMINISTRATOR:
        return None

    institution = getattr(user, "institution", None)
    if institution is None:
        return []

    communes = set()
    if role == UserRole.LOCAL_AUTHORITY and institution.commune_code:
        communes.add(institution.commune_code)

    delegations = DelegationCompetence.objects.filter(
        institution_cible=institution,
        competence__nom=NOM_COMPETENCE_EVALUATION_DEGATS,
        active=True,
    ).filter(Q(date_fin__isnull=True) | Q(date_fin__gt=timezone.now()))
    for d in delegations:
        communes.update(d.communes or [])
        # Un département délégué ne peut pas être listé exhaustivement en codes commune ici
        # sans requêter le référentiel Commune ; filter_habitations_queryset gère ce cas à part
        # via une condition OR sur le préfixe département, voir plus bas.

    return list(communes)


def filter_habitations_queryset(request, queryset):
    """Réduit `queryset` (Habitation) aux communes accessibles à l'appelant -- gère aussi les
    délégations posées au niveau département (préfixe de commune_code) sans lister toutes les
    communes du département une par une."""
    from .permissions import get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return queryset.none()

    role = get_effective_role(request)
    if role == UserRole.ADMINISTRATOR:
        return queryset

    institution = getattr(user, "institution", None)
    if institution is None:
        return queryset.none()

    filtre = Q(pk__in=[])  # base vide, complétée ci-dessous

    if role == UserRole.LOCAL_AUTHORITY and institution.commune_code:
        filtre |= Q(commune_code=institution.commune_code)

    delegations = DelegationCompetence.objects.filter(
        institution_cible=institution,
        competence__nom=NOM_COMPETENCE_EVALUATION_DEGATS,
        active=True,
    ).filter(Q(date_fin__isnull=True) | Q(date_fin__gt=timezone.now()))
    for d in delegations:
        if not d.communes and not d.departements and d.zone_precise is None:
            return queryset  # délégation sans restriction = accès à tout (rare, cas "toute la crise")
        if d.communes:
            filtre |= Q(commune_code__in=d.communes)
        for dep in d.departements or []:
            filtre |= Q(commune_code__startswith=dep)

    return queryset.filter(filtre)


# --- Estimation automatique via la BAN (Phase 2 -- voir doc de conception "référencement des
# dégâts") -----------------------------------------------------------------------------------
#
# Périmètre borné DÉLIBÉRÉMENT à une seule commune par appel, quoi qu'il arrive -- jamais un
# balayage multi-communes (un département peut en compter plusieurs centaines, un scan pareil
# exploserait le budget d'appels externes et le timeout gunicorn). Quand l'appelant précise une
# crise dont la zone est dessinée (Crisis.zone_secteurs), ce polygone RESTREINT encore le
# résultat (les adresses hors polygone sont écartées) -- il ne l'élargit jamais au-delà de la
# commune demandée. Sans crise (ou crise sans zone dessinée) : la commune entière fait foi, seul
# plafond par défaut demandé explicitement par Sylvain le 23/09.


def _fetch_json_ban(url: str, timeout: int = 5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _adresses_voie(voie_id: str) -> list[dict]:
    data = _fetch_json_ban(f"https://plateforme.adresse.data.gouv.fr/lookup/{urllib.parse.quote(voie_id)}")
    if not data:
        return []
    resultats = []
    for numero in data.get("numeros", []):
        position = numero.get("position") or {}
        coords = position.get("coordinates")
        if not coords or len(coords) != 2:
            continue
        lon, lat = coords
        numero_str = str(numero.get("numero") or "").strip()
        suffixe = (numero.get("suffixe") or "").strip()
        nom_voie = data.get("nomVoie") or ""
        code_postal = numero.get("codePostal") or ""
        commune_nom = (data.get("commune") or {}).get("nom") or ""
        adresse = f"{numero_str}{suffixe} {nom_voie}, {code_postal} {commune_nom}".strip()
        parcelles = numero.get("parcelles") or []
        resultats.append({
            "adresse": adresse,
            "lat": lat,
            "lon": lon,
            "parcelle_cadastrale": parcelles[0] if parcelles else None,
            "ban_id": numero.get("id") or numero.get("banId"),
        })
    return resultats


def perimetre_zone_crise(crise) -> "object | None":
    """Polygone (GEOSGeometry) restreignant le scan à la zone dessinée de la crise, si elle en a
    une -- None sinon (la commune entière fait alors foi, voir scanner_ban_commune)."""
    if crise is not None and crise.zone_secteurs is not None and not crise.zone_secteurs.empty:
        return crise.zone_secteurs
    return None


def perimetre_zone_nommee(zone) -> "object | None":
    """Polygone d'une Zone nommée (ex: "Quartier Nord" dessinée à la main dans le catalogue de
    l'institution, voir Zone.zone_precise) -- restriction À L'INTÉRIEUR d'une commune/crise,
    distincte de Crisis.zone_secteurs (qui couvre la zone entière de la crise, ex: plusieurs
    communes). None si la zone n'a pas de géométrie dessinée."""
    if zone is not None and zone.zone_precise is not None and not zone.zone_precise.empty:
        return zone.zone_precise
    return None


def perimetre_scan(crise, zone) -> "object | None":
    """Combine la zone dessinée de la crise et une Zone nommée optionnelle (ex: "commune
    impactée : Le Porge, zone de recherche : Quartier Nord") : l'intersection des deux si les
    deux sont dessinées -- ne restreint jamais moins qu'une des deux, jamais n'élargit au-delà
    de la commune demandée à scanner_ban_commune."""
    poly_crise = perimetre_zone_crise(crise)
    poly_zone = perimetre_zone_nommee(zone)
    if poly_crise is not None and poly_zone is not None:
        return poly_crise.intersection(poly_zone)
    return poly_zone if poly_zone is not None else poly_crise


def scanner_ban_commune(commune_code: str, polygone_limite=None, max_workers: int = 8) -> dict:
    """Balaie la BAN pour UNE commune (voir bandeau ci-dessus pour la justification du
    plafond) : liste des voies (1 appel), puis les numéros de chaque voie (1 appel par voie,
    parallélisés -- une commune de la taille du Porge en compte ~80, du séquentiel dépasserait
    largement le timeout gunicorn par défaut). `polygone_limite`, s'il est fourni, filtre les
    adresses en dehors (point-in-polygon, en Python -- ces adresses ne viennent pas de la base,
    rien à requêter côté DB ici)."""
    commune = _fetch_json_ban(f"https://plateforme.adresse.data.gouv.fr/lookup/{urllib.parse.quote(commune_code)}")
    if not commune:
        return {"adresses": [], "voies_totales": 0, "voies_en_echec": 0, "erreur": "Commune introuvable via la BAN."}

    voies = commune.get("voies", [])
    adresses: list[dict] = []
    echecs = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_adresses_voie, v["id"]): v["id"] for v in voies if v.get("id")}
        for future in as_completed(futures):
            resultat = future.result()
            if not resultat:
                echecs += 1
                continue
            adresses.extend(resultat)

    if polygone_limite is not None:
        from django.contrib.gis.geos import Point
        adresses = [
            a for a in adresses
            if polygone_limite.contains(Point(a["lon"], a["lat"], srid=4326))
        ]

    return {"adresses": adresses, "voies_totales": len(voies), "voies_en_echec": echecs, "erreur": None}
