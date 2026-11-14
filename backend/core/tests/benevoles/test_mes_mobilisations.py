"""« Mon QR code » : le bénévole mobilisé lit SA demande, et elle seule.

Le ViewSet des demandes de mobilisation est réservé aux acteurs institutionnels ; c'est
pourtant le bénévole qui doit présenter l'attestation. Ce que ces tests verrouillent : il lit
les siennes, jamais celles d'un autre, et le verdict d'un QR code ne dit le nom qu'à un compte."""
import secrets

import pytest
from rest_framework.test import APIClient

from core.models import Crisis, DemandeMobilisation, Institution, InstitutionType


def _client(utilisateur=None):
    client = APIClient()
    if utilisateur is not None:
        client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def mobilisation(db, create_user):
    itype = InstitutionType.objects.create(code="AASC", libelle="Association agréée")
    asso = Institution.objects.create(nom="Reserve essai QR", type=itype)
    crise = Crisis.objects.create(name="Crue QR", type="INCENDIE", location="POINT (5.72 45.18)")
    mobilise = create_user(username="mobilise@qr.test", email="mobilise@qr.test", type="UTIL_SIMPLE",
                           first_name="Camille", last_name="Durand")
    autre = create_user(username="autre@qr.test", email="autre@qr.test", type="UTIL_SIMPLE")
    demande = DemandeMobilisation.objects.create(
        crise=crise, institution_emettrice=asso, cible_utilisateur=mobilise,
        type_demande="SE_RENDRE_A", lieu_texte="PC de crise", jeton_verification=secrets.token_urlsafe(32))
    return demande, mobilise, autre


@pytest.mark.django_db
class TestMesMobilisations:

    def test_le_benevole_mobilise_lit_sa_demande_et_son_jeton(self, mobilisation):
        demande, mobilise, _ = mobilisation

        reponse = _client(mobilise).get("/api/mes-mobilisations/")

        assert reponse.status_code == 200
        assert [d["jeton_verification"] for d in reponse.data] == [demande.jeton_verification]
        assert reponse.data[0]["lieu_texte"] == "PC de crise"
        # Le QR code rendu est celui de l'attestation PDF : même adresse, et une vraie image.
        import base64

        assert reponse.data[0]["adresse_verification"].endswith(
            f"/verifier-mobilisation/{demande.jeton_verification}")
        assert base64.b64decode(reponse.data[0]["qr_png"])[:4] == b"\x89PNG"

    def test_personne_ne_lit_la_demande_d_un_autre(self, mobilisation):
        _d, _m, autre = mobilisation

        assert _client(autre).get("/api/mes-mobilisations/").data == []

    def test_sans_compte_la_liste_est_fermee(self, mobilisation):
        assert _client().get("/api/mes-mobilisations/").status_code == 401

    def test_le_qr_se_verifie_sans_compte_mais_sans_le_nom(self, mobilisation):
        demande, mobilise, _ = mobilisation
        chemin = f"/api/verifier-mobilisation/{demande.jeton_verification}/donnees/"

        anonyme = _client().get(chemin).data
        connecte = _client(mobilise).get(chemin).data

        assert anonyme["valide"] is True and "destinataire" not in anonyme and "lieu" not in anonyme
        assert connecte["lieu"] == "PC de crise" and "Durand" in connecte["destinataire"]
