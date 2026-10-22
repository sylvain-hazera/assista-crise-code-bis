"""Deux radios MeshCore servant les mêmes canaux (22/10/2026 : Bureau sur .114 et la radio du
satellite de la Loire) : chaque radio garde SON slot pour chaque canal (ProvisionCanalMeshCore),
plus de vol de canal en boucle, et chaque message n'est émis que par une radio, avec le slot de
celle-ci."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    CanalMeshCore,
    CompagnonMeshCore,
    Institution,
    InstitutionType,
    MessageCanalMeshCore,
    ProvisionCanalMeshCore,
    Team,
)


@pytest.fixture
def loire(db):
    itype, _ = InstitutionType.objects.get_or_create(code="DEPARTEMENT", defaults={"libelle": "Département"})
    return Institution.objects.create(nom="Conseil départemental - Loire", type=itype)


@pytest.fixture
def bureau(db):
    return CompagnonMeshCore.objects.create(nom="Bureau", connexion_type="TCP", dernier_etat="CONNECTE")


@pytest.fixture
def radio_loire(loire):
    return CompagnonMeshCore.objects.create(nom="Satellite Loire", institution=loire, connexion_type="SERIE", dernier_etat="CONNECTE")


@pytest.fixture
def canal_cai(loire):
    equipe = Team.objects.create(name="CAI", institution=loire)
    return CanalMeshCore.objects.create(equipe=equipe, institution=loire, nom="Équipe CAI", cle_partagee_hex="ab" * 16)


@pytest.fixture
def pont(create_user):
    compte = create_user(username="pont-2radios@assista-crise.local", email="pont-2radios@assista-crise.local", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=compte)
    return client


def _rapporter(pont, compagnon, canal, idx):
    reponse = pont.post(reverse('compagnonmeshcore-rapporter-canal-provisionne', args=[compagnon.id]),
                        {"canal_id": str(canal.id), "canal_idx": idx}, format="json")
    assert reponse.status_code == 200, reponse.data


def _a_provisionner(pont, compagnon):
    return {c["id"] for c in pont.get(reverse('compagnonmeshcore-canaux-a-provisionner', args=[compagnon.id])).data}


def _file(pont, compagnon=None):
    params = {"compagnon": str(compagnon.id)} if compagnon else {}
    return pont.get(reverse('messagecanalmeshcore-a-envoyer'), params).data


@pytest.mark.django_db
class TestDeuxRadios:

    def test_chaque_radio_garde_son_slot_sans_se_voler_le_canal(self, pont, bureau, radio_loire, canal_cai):
        _rapporter(pont, bureau, canal_cai, 11)
        _rapporter(pont, radio_loire, canal_cai, 10)

        assert dict(canal_cai.provisions.values_list('compagnon_id', 'canal_idx')) == {bureau.id: 11, radio_loire.id: 10}
        assert str(canal_cai.id) not in _a_provisionner(pont, bureau)       # plus de réinstallation
        assert str(canal_cai.id) not in _a_provisionner(pont, radio_loire)
        slots = pont.get(reverse('compagnonmeshcore-canaux-provisionnes', args=[bureau.id])).data
        assert slots == [{"id": str(canal_cai.id), "canal_idx": 11}]

    def test_message_emis_par_la_radio_de_l_institution_avec_son_slot(self, pont, bureau, radio_loire, canal_cai):
        _rapporter(pont, bureau, canal_cai, 11)
        _rapporter(pont, radio_loire, canal_cai, 10)
        message = MessageCanalMeshCore.objects.create(canal=canal_cai, direction="SORTANT", contenu="recois tu le mesh ?")

        assert [(m["id"], m["canal_idx"]) for m in _file(pont, radio_loire)] == [(str(message.id), 10)]
        assert _file(pont, bureau) == []                                     # un seul émetteur

    def test_radio_de_l_institution_deconnectee_le_central_prend_le_relais(self, pont, bureau, radio_loire, canal_cai):
        _rapporter(pont, bureau, canal_cai, 11)
        _rapporter(pont, radio_loire, canal_cai, 10)
        radio_loire.dernier_etat = "DECONNECTE"
        radio_loire.save()
        MessageCanalMeshCore.objects.create(canal=canal_cai, direction="SORTANT", contenu="recois tu le mesh ?")

        assert [m["canal_idx"] for m in _file(pont, bureau)] == [11]          # slot de Bureau, pas 10
        assert _file(pont, radio_loire) == []

    def test_ancien_pont_sans_radio_precisee_ne_recoit_rien(self, pont, bureau, canal_cai):
        _rapporter(pont, bureau, canal_cai, 11)
        MessageCanalMeshCore.objects.create(canal=canal_cai, direction="SORTANT", contenu="x")

        assert _file(pont) == []

    def test_canal_pas_installe_sur_la_radio_pas_servi(self, pont, bureau, radio_loire, canal_cai):
        _rapporter(pont, bureau, canal_cai, 11)
        MessageCanalMeshCore.objects.create(canal=canal_cai, direction="SORTANT", contenu="x")

        assert _file(pont, radio_loire) == []
        assert [m["canal_idx"] for m in _file(pont, bureau)] == [11]

    def test_radio_d_institution_n_installe_pas_les_equipes_des_autres(self, pont, bureau, radio_loire, canal_cai):
        autre = Institution.objects.create(nom="Mairie de Bordeaux", type=InstitutionType.objects.first())
        equipe = Team.objects.create(name="Les Cuves Pompes", institution=autre)
        canal_autre = CanalMeshCore.objects.create(equipe=equipe, institution=autre, nom="Équipe Cuves", cle_partagee_hex="cd" * 16)
        canal_public = CanalMeshCore.objects.create(nom="#gironde", cle_partagee_hex="ef" * 16)

        assert _a_provisionner(pont, radio_loire) == {str(canal_cai.id), str(canal_public.id)}
        assert _a_provisionner(pont, bureau) == {str(canal_cai.id), str(canal_autre.id), str(canal_public.id)}

    def test_slot_reutilise_par_un_autre_canal_remplace_l_ancien(self, pont, bureau, canal_cai):
        ancien = CanalMeshCore.objects.create(nom="#test", cle_partagee_hex="12" * 16)
        _rapporter(pont, bureau, ancien, 5)
        _rapporter(pont, bureau, canal_cai, 5)

        assert list(ProvisionCanalMeshCore.objects.filter(compagnon=bureau).values_list('canal_id', 'canal_idx')) == [(canal_cai.id, 5)]

    def test_canal_public_detecte_un_par_radio_au_slot_0(self, pont, bureau, radio_loire):
        hash_public = CanalMeshCore.chan_hash_pour_secret(CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT)
        for compagnon in (bureau, radio_loire, bureau):                     # 2e signalement : sans doublon
            reponse = pont.post(reverse('compagnonmeshcore-signaler-canaux-detectes', args=[compagnon.id]),
                                {"hashes": {hash_public: 3}}, format="json")
            assert reponse.status_code == 200, reponse.data

        provisions = ProvisionCanalMeshCore.objects.filter(canal__cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT)
        assert sorted((p.compagnon_id, p.canal_idx) for p in provisions) == sorted([(bureau.id, 0), (radio_loire.id, 0)])
        assert CanalMeshCore.objects.filter(nom="Public").count() == 2
