"""L'organisation d'une institution : elle, ses filles, et leurs équipes, en arbre (23/11/2026).

Demande de Sylvain : « un graphique des institutions et leurs filles ». Un arbre dépliable
plutôt qu'un organigramme dessiné : à l'échelle d'un département (plus de 550 collectivités en
Gironde), un dessin devient illisible, un arbre reste lisible et tient sur un téléphone.

**Périmètre** : celui de la personne.
- Un administrateur qui regarde toute la plateforme voit les institutions de tête qui ont des
  filles (les autres n'ont pas d'arbre à montrer), ou, avec une recherche, l'arbre de chaque
  institution trouvée.
- Un administrateur qui regarde une institution, et tout autre compte, voit l'arbre de son
  institution de travail (et de ses filles).

Trois requêtes pour tout l'arbre (institutions, effectifs, équipes), jamais une par nœud.
"""
from django.db.models import Count


def _environnements(request):
    from .models import Environment
    from .permissions import get_active_environment
    return [Environment.PROD, Environment.DEMO] if get_active_environment(request) == Environment.DEMO else [Environment.PROD]


def racines(request, recherche=""):
    """Les identifiants des institutions par lesquelles commencent les arbres à montrer."""
    from .models import Institution
    from .perimetre_admin import admin_voit_tout, est_administrateur, institution_regardee

    envs = _environnements(request)
    if est_administrateur(request) and admin_voit_tout(request):
        if recherche:
            trouvees = Institution.objects.filter(environment__in=envs, nom__icontains=recherche).values_list(
                "id", "institution_parente_id")[:50]
            parents = dict(Institution.objects.exclude(institution_parente_id=None).values_list("id", "institution_parente_id"))
            tetes = []
            for ident, parent in trouvees:
                vus = {ident}
                while parent and parent not in vus:      # remonte à la tête, sans boucle
                    vus.add(parent)
                    ident, parent = parent, parents.get(parent)
                tetes.append(ident)
            return list(dict.fromkeys(tetes))
        return list(Institution.objects.filter(
            environment__in=envs, institution_parente=None, actif=True, institutions_filles__isnull=False,
        ).distinct().values_list("id", flat=True))
    base = institution_regardee(request) if est_administrateur(request) else getattr(request.user, "institution", None)
    return [base.id] if base is not None else []


def arbre(request, recherche=""):
    """Les arbres : [{id, nom, type_code, type_libelle, actif, rcsc, membres, equipes, filles}]."""
    from .models import ContactInstitution, Institution, Team
    from .perimetre_admin import institutions_descendantes

    tetes = racines(request, (recherche or "").strip())
    if not tetes:
        return []
    ids = institutions_descendantes(tetes)
    envs = _environnements(request)
    institutions = {
        i.id: i for i in Institution.objects.filter(id__in=ids, environment__in=envs).select_related("type")
    }
    effectifs = dict(ContactInstitution.objects.filter(institution_id__in=institutions, actif=True)
                     .values("institution_id").annotate(n=Count("id")).values_list("institution_id", "n"))
    equipes = list(Team.objects.filter(institution_id__in=institutions)
                   .annotate(n=Count("members", distinct=True))
                   .values("id", "name", "institution_id", "equipe_parente_id", "est_equipe_rcsc", "n"))

    par_institution, sous = {}, {}
    par_id = {e["id"]: e for e in equipes}
    for e in equipes:
        parent = e["equipe_parente_id"]
        # Une équipe se range sous sa parente si celle-ci est de la MÊME institution ; l'équipe
        # d'une fille, accrochée à celle de la mère, se montre sous la fille.
        meme = parent in par_id and par_id[parent]["institution_id"] == e["institution_id"]
        (sous.setdefault(parent, []) if meme else par_institution.setdefault(e["institution_id"], [])).append(e)

    def noeud_equipe(e):
        return {"id": str(e["id"]), "nom": e["name"], "rcsc": e["est_equipe_rcsc"], "membres": e["n"],
                "sous_equipes": [noeud_equipe(s) for s in sorted(sous.get(e["id"], []), key=lambda s: s["name"])]}

    filles = {}
    for i in institutions.values():
        if i.institution_parente_id in institutions:
            filles.setdefault(i.institution_parente_id, []).append(i)

    def noeud(i):
        code = (i.type.code if i.type_id else "") or ""
        return {
            "id": str(i.id), "nom": i.nom_affichage or i.nom or "", "actif": i.actif,
            "type_code": code.lower(), "type_libelle": i.type.libelle if i.type_id else "",
            "rcsc": code.lower() == "rcsc", "commune": i.commune_nom or "",
            "membres": effectifs.get(i.id, 0),
            "equipes": [noeud_equipe(e) for e in sorted(par_institution.get(i.id, []), key=lambda e: e["name"])],
            "filles": [noeud(f) for f in sorted(filles.get(i.id, []), key=lambda f: (f.nom or ""))],
        }

    return [noeud(institutions[t]) for t in tetes if t in institutions]
