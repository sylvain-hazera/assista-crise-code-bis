"""« Tout doit être chiffré en base » (18/11/2026) : ce qui est saisi ou personnel est chiffré,
et aucune requête SQL ne filtre, ne cherche ni ne trie sur une colonne chiffrée."""
import importlib

import pytest
from django.apps import apps
from django.db import connection

from core.crypto_fields import EncryptedTextField, RequeteSurChampChiffre, empreinte_jeton

migration = importlib.import_module("core.migrations.0345_tout_chiffrer_donnees")


def _champ(nom_modele, nom_champ):
    return apps.get_model("core", nom_modele)._meta.get_field(nom_champ)


def test_chaque_champ_de_la_migration_est_chiffre_dans_le_modele():
    for nom, champs in list(migration.CHAMPS.items()) + list(migration.JETONS.items()):
        for champ in champs:
            assert isinstance(_champ(nom, champ), EncryptedTextField), f"{nom}.{champ}"
    for nom, jetons in migration.JETONS.items():
        for jeton in jetons:
            assert _champ(nom, f"{jeton}_empreinte").unique, f"{nom}.{jeton}_empreinte"


def _cible(modele, chemin):
    """Le champ final d'un chemin « relation__champ » (ou None s'il n'existe pas)."""
    champ = None
    for morceau in chemin.lstrip("-^=@").split("__"):
        try:
            champ = modele._meta.get_field(morceau)
        except Exception:  # noqa: BLE001 -- un lookup (icontains…) ou une annotation
            return champ
        if champ.is_relation and champ.related_model is not None:
            modele = champ.related_model
    return champ


def test_aucun_tri_par_defaut_sur_une_colonne_chiffree():
    fautes = [f"{modele.__name__}.Meta.ordering : {chemin}"
              for modele in apps.get_app_config("core").get_models()
              for chemin in (modele._meta.ordering or ())
              if isinstance(chemin, str) and isinstance(_cible(modele, chemin), EncryptedTextField)]
    assert not fautes, fautes


def test_aucune_vue_ne_cherche_ni_ne_trie_sur_une_colonne_chiffree():
    from django.urls import get_resolver

    def vues(motifs):
        for motif in motifs:
            if hasattr(motif, "url_patterns"):
                yield from vues(motif.url_patterns)
            else:
                classe = getattr(motif.callback, "cls", None)
                if classe is not None:
                    yield classe

    fautes = set()
    for classe in set(vues(get_resolver().url_patterns)):
        queryset = getattr(classe, "queryset", None)
        if queryset is None:
            continue
        modele = queryset.model
        chemins = list(getattr(classe, "search_fields", None) or ())
        chemins += [c for c in (getattr(classe, "ordering_fields", None) or ()) if c != "__all__"]
        ordre = getattr(classe, "ordering", None) or ()
        chemins += [ordre] if isinstance(ordre, str) else list(ordre)
        for chemin in chemins:
            if isinstance(_cible(modele, chemin), EncryptedTextField):
                fautes.add(f"{classe.__name__} : {chemin}")
    assert not fautes, sorted(fautes)


@pytest.mark.django_db
def test_un_filtre_sur_une_colonne_chiffree_est_arrete(create_user):
    from core.models import User
    with pytest.raises(RequeteSurChampChiffre):
        list(User.objects.filter(last_name="Durand"))
    with pytest.raises(RequeteSurChampChiffre):
        list(User.objects.filter(last_name__icontains="dur"))
    with pytest.raises(RequeteSurChampChiffre):
        list(User.objects.order_by("last_name"))
    # Le « non rempli » reste possible.
    list(User.objects.filter(last_name=""))
    list(User.objects.exclude(last_name__isnull=True))


@pytest.mark.django_db
def test_rien_en_clair_et_le_lien_par_jeton_fonctionne(create_user, request_type):
    from core.models import Request
    compte = create_user(username="jeanne@exemple.fr", email="jeanne@exemple.fr", first_name="Jeanne", last_name="Martin")
    demande = Request.objects.create(title="Cave inondée rue Haute", description="x", request_type=request_type,
                                     edition_token="Jeton-Secret-AbC123")
    with connection.cursor() as curseur:
        curseur.execute("SELECT username, first_name, last_name FROM core_user WHERE id = %s", [compte.id])
        assert not any(v and ("jeanne" in v.lower() or "martin" in v.lower()) for v in curseur.fetchone())
        curseur.execute("SELECT title, edition_token, edition_token_empreinte FROM core_request WHERE id = %s", [str(demande.id)])
        titre, jeton, empreinte = curseur.fetchone()
    assert "Cave" not in titre and "Jeton-Secret" not in jeton
    assert empreinte == empreinte_jeton("Jeton-Secret-AbC123")
    # La casse compte : un jeton n'est pas une adresse.
    assert empreinte != empreinte_jeton("jeton-secret-abc123")
    assert Request.objects.get(edition_token_empreinte=empreinte_jeton("Jeton-Secret-AbC123")).pk == demande.pk


@pytest.mark.django_db
def test_la_migration_chiffre_les_lignes_anciennes_et_se_rejoue(create_user):
    from core.models import User
    compte = create_user(username="ancien@exemple.fr", email="ancien@exemple.fr", first_name="Paul", last_name="Ancien")
    with connection.cursor() as curseur:   # une ligne d'avant : en clair
        curseur.execute("UPDATE core_user SET last_name = 'Ancien', username = 'ancien@exemple.fr' WHERE id = %s", [compte.id])
    migration.chiffrer(apps, None)
    migration.chiffrer(apps, None)         # réexécutable
    with connection.cursor() as curseur:
        curseur.execute("SELECT last_name, username FROM core_user WHERE id = %s", [compte.id])
        nom, identifiant = curseur.fetchone()
    assert "Ancien" not in nom and "ancien@" not in identifiant
    compte.refresh_from_db()
    assert (compte.last_name, compte.username) == ("Ancien", "ancien@exemple.fr")
    migration.dechiffrer(apps, None)       # et réversible
    with connection.cursor() as curseur:
        curseur.execute("SELECT last_name FROM core_user WHERE id = %s", [compte.id])
        assert curseur.fetchone()[0] == "Ancien"
