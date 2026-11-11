"""Le client Brevo : respect du contrat, et traitement des cas que la doc ne couvre pas.

Contrat relevé sur developers.brevo.com le 11/11/2026 (reference/send-transac-email,
docs/send-a-transactional-email). Testé ici parce qu'une intégration HTTP se trompe en silence :
un nom de champ faux fait un 400 que personne ne lit, un en-tête faux fait un 401.

Deux zones d'ombre de la documentation, traitées défensivement et verrouillées ici :
elle ne documente **que le 400** (aucune entrée 401/403), et elle ne dit **pas** quelle erreur
revient pour un expéditeur non vérifié. Tout statut hors 2xx est donc un échec nommé, avec le
message de Brevo remonté intact.
"""
import json

import pytest

from core.envoi_brevo import URL_BREVO, EchecBrevo, envoyer_email_brevo


class FausseReponse:
    def __init__(self, status_code, charge=None, texte=""):
        self.status_code = status_code
        self._charge = charge
        self.text = texte

    def json(self):
        if self._charge is None:
            raise ValueError("pas de JSON")
        return self._charge


def capturer(reponse):
    """Remplace requests.post et retourne (appels, fonction)."""
    appels = []

    def faux_post(url, headers=None, data=None, timeout=None):
        appels.append({"url": url, "headers": headers or {},
                       "corps": json.loads(data) if data else {}, "timeout": timeout})
        if isinstance(reponse, Exception):
            raise reponse
        return reponse

    return appels, faux_post


class TestContrat:

    def test_l_appel_respecte_l_endpoint_et_l_en_tete_de_cle(self, monkeypatch):
        """`api-key` et non `Authorization: Bearer` — l'autre forme renvoie 401, et c'est le
        piège le plus courant de cette API."""
        appels, faux = capturer(FausseReponse(201, {"messageId": "<abc@brevo>"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "Expediteur", "Sujet",
                            "Corps", ["dest@essai.invalide"])

        assert appels[0]['url'] == URL_BREVO == "https://api.brevo.com/v3/smtp/email"
        assert appels[0]['headers']['api-key'] == "xkeysib-abc"
        assert 'Authorization' not in appels[0]['headers']
        assert appels[0]['headers']['Content-Type'] == "application/json"

    def test_le_corps_n_envoie_que_textContent(self, monkeypatch):
        """« You can only pick one of the three body types per request » : htmlContent,
        textContent ou templateId. Nos messages sont en texte brut ; ajouter un htmlContent
        dérivé ferait une seconde version du message à maintenir."""
        appels, faux = capturer(FausseReponse(201, {"messageId": "<abc@brevo>"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "Expediteur", "Sujet",
                            "Corps du message", ["dest@essai.invalide"])

        corps = appels[0]['corps']
        assert corps['textContent'] == "Corps du message"
        assert 'htmlContent' not in corps
        assert 'templateId' not in corps
        assert corps['sender'] == {"email": "exp@essai.invalide", "name": "Expediteur"}
        assert corps['to'] == [{"email": "dest@essai.invalide"}]
        assert corps['subject'] == "Sujet"

    def test_le_nom_d_expediteur_est_tronque_a_70_caracteres(self, monkeypatch):
        """Limite documentée. Tronqué plutôt que refusé : un nom d'association un peu long ne
        doit pas empêcher un envoi."""
        appels, faux = capturer(FausseReponse(201, {"messageId": "x"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "N" * 120, "Sujet", "Corps",
                            ["dest@essai.invalide"])
        assert len(appels[0]['corps']['sender']['name']) == 70

    def test_le_reply_to_est_envoye_quand_il_existe(self, monkeypatch):
        appels, faux = capturer(FausseReponse(201, {"messageId": "x"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "E", "S", "C",
                            ["dest@essai.invalide"], reply_to="repondre@essai.invalide")
        assert appels[0]['corps']['replyTo'] == {"email": "repondre@essai.invalide"}

    def test_sans_reply_to_le_champ_est_absent_et_non_null(self, monkeypatch):
        """`replyTo: null` serait un champ invalide plutôt qu'un champ absent."""
        appels, faux = capturer(FausseReponse(201, {"messageId": "x"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "E", "S", "C",
                            ["dest@essai.invalide"])
        assert 'replyTo' not in appels[0]['corps']

    def test_le_messageId_est_renvoye(self, monkeypatch):
        _, faux = capturer(FausseReponse(201, {"messageId": "<201798300811@relay>"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        assert envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "E", "S", "C",
                                   ["d@essai.invalide"]) == "<201798300811@relay>"

    def test_un_202_sans_corps_documente_reste_un_succes(self, monkeypatch):
        """202 (envoi programmé) a un corps non documenté : on ne fait pas dépendre le succès
        de la présence du champ."""
        _, faux = capturer(FausseReponse(202, None, texte="accepte"))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        assert envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "E", "S", "C",
                                   ["d@essai.invalide"]) == ""


class TestEchecs:

    def test_un_400_remonte_le_code_et_le_message_de_brevo(self, monkeypatch):
        """Le message de Brevo est la SEULE information utile : il nomme la cause (clé, quota,
        domaine). Le remplacer par « erreur d'envoi » la ferait perdre."""
        _, faux = capturer(FausseReponse(
            400, {"code": "api-key not found", "message": "Key not found"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        with pytest.raises(EchecBrevo) as echec:
            envoyer_email_brevo("xkeysib-faux", "exp@essai.invalide", "E", "S", "C",
                                ["d@essai.invalide"])
        assert "api-key not found" in echec.value.detail
        assert "Key not found" in echec.value.detail

    @pytest.mark.parametrize("statut", [401, 403, 500, 503])
    def test_tout_statut_hors_2xx_est_un_echec(self, monkeypatch, statut):
        """La documentation ne liste QUE le 400. On ne suppose donc pas qu'un 401 n'arrivera
        jamais : un statut non documenté traité comme un succès ferait croire qu'un mail est
        parti alors qu'il ne l'est pas."""
        _, faux = capturer(FausseReponse(statut, None, texte="refus"))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        with pytest.raises(EchecBrevo):
            envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "E", "S", "C",
                                ["d@essai.invalide"])

    def test_le_429_est_nomme_comme_un_quota(self, monkeypatch):
        """Un quota dépassé n'appelle pas la même réaction qu'une clé invalide : le dire permet
        de ne pas chercher du côté de la configuration."""
        _, faux = capturer(FausseReponse(429, None, texte=""))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        with pytest.raises(EchecBrevo, match="Quota"):
            envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "E", "S", "C",
                                ["d@essai.invalide"])

    def test_une_panne_reseau_est_un_echec_et_non_une_exception_nue(self, monkeypatch):
        import requests

        _, faux = capturer(requests.ConnectionError("injoignable"))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        with pytest.raises(EchecBrevo, match="injoignable"):
            envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "E", "S", "C",
                                ["d@essai.invalide"])

    def test_une_configuration_incomplete_echoue_sans_appel_reseau(self, monkeypatch):
        """Mieux vaut refuser tout de suite que d'envoyer une requête qu'on sait refusée — et
        surtout que d'envoyer une clé vide sur le réseau."""
        appels, faux = capturer(FausseReponse(201, {"messageId": "x"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        with pytest.raises(EchecBrevo, match="incomplète"):
            envoyer_email_brevo("", "exp@essai.invalide", "E", "S", "C", ["d@essai.invalide"])
        with pytest.raises(EchecBrevo, match="incomplète"):
            envoyer_email_brevo("xkeysib-abc", "", "E", "S", "C", ["d@essai.invalide"])
        assert appels == []

    def test_sans_destinataire_rien_n_est_envoye(self, monkeypatch):
        appels, faux = capturer(FausseReponse(201, {"messageId": "x"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        with pytest.raises(EchecBrevo, match="destinataire"):
            envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "E", "S", "C", [])
        assert appels == []

    def test_l_appel_porte_un_delai_maximum(self, monkeypatch):
        """Un appel HTTP dans le cycle d'une requête web ne doit pas pouvoir la bloquer
        indéfiniment : sans timeout, une panne de Brevo gèlerait l'inscription."""
        appels, faux = capturer(FausseReponse(201, {"messageId": "x"}))
        monkeypatch.setattr('core.envoi_brevo.requests.post', faux)

        envoyer_email_brevo("xkeysib-abc", "exp@essai.invalide", "E", "S", "C",
                            ["d@essai.invalide"])
        assert appels[0]['timeout'] and appels[0]['timeout'] <= 30
