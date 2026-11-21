"""« Rejoindre votre collectivité » (21/11/2026) : l'AASC invite les mairies et EPCI du
département délégué, chacun ouvre son compte par le lien puis complète son plan."""
import datetime
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, DelegationGestion, Institution, InstitutionType, InvitationCollectivite, Team, User,
)


def _type(code):
    return InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})[0]


@pytest.fixture
def monde(db):
    cg = Institution.objects.create(nom="Conseil départemental — Loire", type=_type("cg"), commune_code="42218",
                                    departement_code="42", secteur_override="departement")
    aasc = Institution.objects.create(nom="Réserve essai", type=_type("aasc"))
    cadre = User.objects.create_user(username="cadre@test.fr", email="cadre@test.fr", password="x", type="SECOURS")
    ContactInstitution.objects.create(institution=aasc, utilisateur=cadre, actif=True)
    loire = Team.objects.create(name="Coordination Loire", institution=aasc, echelon="DEPARTEMENTAL",
                                territoire_code="42", environment="PROD")
    loire.membres_encadrement.add(cadre)
    d = DelegationGestion.objects.create(collectivite=cg, aasc=aasc, convention_signee_le="2026-10-01", environment="PROD")
    mairie = Institution.objects.create(nom="Mairie - Rive-de-Gier", type=_type("mairie"), commune_code="42186",
                                        email="mairie@ville.exemple")
    muette = Institution.objects.create(nom="Mairie - Sans adresse", type=_type("mairie"), commune_code="42001")
    ailleurs = Institution.objects.create(nom="Mairie - Lyon", type=_type("mairie"), commune_code="69123",
                                          email="mairie@lyon.exemple")
    return dict(d=d, cadre=cadre, mairie=mairie, muette=muette, ailleurs=ailleurs)


def _client(u=None):
    c = APIClient()
    if u:
        c.force_authenticate(user=u)
    return c


def _inviter(monde, *institutions):
    with mock.patch("core.branding.send_branded_mail") as envoi:
        r = _client(monde["cadre"]).post(reverse("delegationgestion-inviter-collectivites", args=[monde["d"].id]),
                                         {"institutions": [str(i.id) for i in institutions]}, format="json")
    return r, envoi


@pytest.mark.django_db
def test_invite_les_mairies_du_departement_seulement(monde):
    r, envoi = _inviter(monde, monde["mairie"], monde["muette"], monde["ailleurs"])
    assert r.status_code == 200, r.data
    assert r.data["envoyees"] == 1
    assert r.data["sans_email"] == ["Mairie - Sans adresse"]
    assert r.data["hors_territoire"] == 1
    assert InvitationCollectivite.objects.filter(institution=monde["mairie"]).count() == 1
    assert envoi.call_args.kwargs["recipient_list"] == ["mairie@ville.exemple"]


@pytest.mark.django_db
def test_relancer_garde_le_meme_lien(monde):
    _inviter(monde, monde["mairie"])
    _inviter(monde, monde["mairie"])
    inv = InvitationCollectivite.objects.get()
    assert inv.date_relance is not None


@pytest.mark.django_db
def test_rejoindre_ouvre_un_compte_rattache_et_demande_la_convention(monde):
    _inviter(monde, monde["mairie"])
    jeton = InvitationCollectivite.objects.get().jeton
    url = reverse("rejoindre_collectivite", args=[jeton])
    anonyme = _client()
    info = anonyme.get(url).data
    assert info["institution"] == "Mairie - Rive-de-Gier" and info["convention_requise"] is True
    corps = {"prenom": "Claire", "nom": "Fontaine", "email": "claire@ville.exemple", "fonction": "Maire"}
    with mock.patch("core.branding.send_branded_mail"), mock.patch("core.views.send_mail_logged"):
        assert anonyme.post(url, corps, format="json").status_code == 400  # convention non acceptée
        r = anonyme.post(url, {**corps, "convention_acceptee": True}, format="json")
    assert r.status_code == 201, r.data
    user = next(u for u in User.objects.all() if u.email == "claire@ville.exemple")
    assert user.type == "AUT_LOCALE" and user.is_active is False
    assert ContactInstitution.objects.filter(institution=monde["mairie"], utilisateur=user, actif=True).exists()
    monde["mairie"].refresh_from_db()
    assert monde["mairie"].convention_sous_traitance_acceptee_le is not None
    assert InvitationCollectivite.objects.get().comptes_crees == 1


@pytest.mark.django_db
def test_un_lien_expire_ou_epuise_ne_sert_plus(monde):
    _inviter(monde, monde["mairie"])
    inv = InvitationCollectivite.objects.get()
    url = reverse("rejoindre_collectivite", args=[inv.jeton])
    inv.comptes_crees = InvitationCollectivite.MAX_COMPTES
    inv.save()
    assert _client().get(url).status_code == 404
    inv.comptes_crees = 0
    inv.date_expiration = timezone.localdate() - datetime.timedelta(days=1)
    inv.save()
    assert _client().get(url).status_code == 404
    assert _client().get(reverse("rejoindre_collectivite", args=["nimporte"])).status_code == 404


@pytest.mark.django_db
def test_seuls_ceux_qui_agissent_invitent(monde, create_user):
    intrus = create_user(username="intrus@test.fr", email="intrus@test.fr", type="SECOURS")
    r = _client(intrus).post(reverse("delegationgestion-inviter-collectivites", args=[monde["d"].id]),
                             {"institutions": [str(monde["mairie"].id)]}, format="json")
    assert r.status_code in (403, 404)
    assert not InvitationCollectivite.objects.exists()


@pytest.mark.django_db
def test_le_jeton_est_chiffre_en_base(monde):
    from django.db import connection
    _inviter(monde, monde["mairie"])
    inv = InvitationCollectivite.objects.get()
    with connection.cursor() as cur:
        cur.execute("select jeton from core_invitationcollectivite where id=%s", [str(inv.id)])
        assert inv.jeton not in cur.fetchone()[0]


@pytest.mark.django_db
def test_le_referent_indique_recoit_l_invitation(monde):
    c = _client(monde["cadre"])
    url = reverse("delegationgestion-coordonnees", args=[monde["d"].id])
    r = c.post(url, {"institution": str(monde["muette"].id),
                     "referent": {"nom": "Julie Martin", "fonction": "Secrétaire de mairie", "email": "j.martin@commune.exemple"}},
               format="json")
    assert r.status_code == 200, r.data
    r, envoi = _inviter(monde, monde["muette"])
    assert r.data["envoyees"] == 1 and r.data["sans_email"] == []
    assert envoi.call_args.kwargs["recipient_list"] == ["j.martin@commune.exemple"]
    assert envoi.call_args.kwargs["message"].startswith("Bonjour Julie Martin,")


@pytest.mark.django_db
def test_corriger_les_coordonnees_officielles_et_retirer_le_referent(monde):
    from core.models import ReferentCollectivite
    c = _client(monde["cadre"])
    url = reverse("delegationgestion-coordonnees", args=[monde["d"].id])
    c.post(url, {"institution": str(monde["mairie"].id), "officiel": {"telephone": "04 77 00 00 00"},
                 "referent": {"nom": "Paul", "email": "paul@ville.exemple"}}, format="json")
    monde["mairie"].refresh_from_db()
    assert monde["mairie"].telephone == "04 77 00 00 00"
    assert ReferentCollectivite.objects.filter(institution=monde["mairie"]).exists()
    c.post(url, {"institution": str(monde["mairie"].id), "referent": {"nom": "", "email": ""}}, format="json")
    assert not ReferentCollectivite.objects.filter(institution=monde["mairie"]).exists()


@pytest.mark.django_db
def test_coordonnees_hors_territoire_refusees(monde):
    r = _client(monde["cadre"]).post(reverse("delegationgestion-coordonnees", args=[monde["d"].id]),
                                     {"institution": str(monde["ailleurs"].id), "referent": {"nom": "X"}}, format="json")
    assert r.status_code == 400
