"""Notifications poussées (core/web_push.py) : chiffrement RFC 8291, signature VAPID RFC 8292."""
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core import web_push
from core.web_push import b64url, depuis_b64url

# RFC 8291, annexe A.
CONTENU = b"When I grow up, I want to be a watermelon"
AS_PRIVE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PRIVE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
SEL = "DGv6ra1nlYgDCS1FRnbzlw"
ATTENDU = ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_"
           "yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def _cle(b64):
    return ec.derive_private_key(int.from_bytes(depuis_b64url(b64), "big"), ec.SECP256R1())


def dechiffrer(corps: bytes, cle_navigateur, auth: bytes) -> bytes:
    """Ce que fait le navigateur, pour l'aller-retour."""
    sel, taille_cle = corps[:16], corps[20]
    publique_serveur = corps[21:21 + taille_cle]
    pub_ua = cle_navigateur.public_key().public_bytes(serialization.Encoding.X962,
                                                      serialization.PublicFormat.UncompressedPoint)
    partage = cle_navigateur.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), publique_serveur))
    ikm = web_push._hkdf(auth, partage, b"WebPush: info\x00" + pub_ua + publique_serveur, 32)
    cle = web_push._hkdf(sel, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = web_push._hkdf(sel, ikm, b"Content-Encoding: nonce\x00", 12)
    clair = AESGCM(cle).decrypt(nonce, corps[21 + taille_cle:], None)
    assert clair.endswith(b"\x02")
    return clair[:-1]


def test_le_chiffrement_redonne_l_exemple_de_la_rfc_8291():
    corps = web_push.chiffrer(CONTENU, depuis_b64url(UA_PUBLIC), depuis_b64url(AUTH),
                              cle_ephemere=_cle(AS_PRIVE), sel=depuis_b64url(SEL))
    assert b64url(corps) == ATTENDU


def test_aller_retour_avec_des_cles_tirees_au_hasard():
    navigateur = ec.generate_private_key(ec.SECP256R1())
    p256dh = navigateur.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    message = json.dumps({"titre": "Renfort demandé à 14 h", "lien": "/terrain/alertes"}).encode()
    corps = web_push.chiffrer(message, p256dh, auth)
    assert message not in corps                                  # rien de lisible en route
    assert dechiffrer(corps, navigateur, auth) == message


def test_seuls_les_services_de_notification_connus_sont_appeles():
    cles = {"p256dh": UA_PUBLIC, "auth": AUTH}
    for adresse in ("https://web.push.apple.com/QGuQyavXutnMK", "https://fcm.googleapis.com/fcm/send/abc",
                    "https://updates.push.services.mozilla.com/wpush/v2/x"):
        assert web_push.valider_abonnement({"endpoint": adresse, "keys": cles})["endpoint"] == adresse
    for adresse in ("http://web.push.apple.com/x", "https://exemple.fr/x", "https://web.push.apple.com.exemple.fr/x",
                    "https://169.254.169.254/latest", ""):
        with pytest.raises(web_push.AbonnementRefuse):
            web_push.valider_abonnement({"endpoint": adresse, "keys": cles})
    with pytest.raises(web_push.AbonnementRefuse):
        web_push.valider_abonnement({"endpoint": "https://web.push.apple.com/x", "keys": {"p256dh": "abc", "auth": AUTH}})


def test_l_entete_vapid_est_signe_par_notre_cle():
    cle = ec.generate_private_key(ec.SECP256R1())
    entete = web_push.entete_vapid("https://web.push.apple.com/QGuQ", cle, "https://www.assista-crise.fr", maintenant=1_000)
    jeton, k = entete.removeprefix("vapid t=").split(", k=")
    assert k == web_push.cle_publique_b64url(cle)
    signe, signature = jeton.rsplit(".", 1)
    revendications = json.loads(depuis_b64url(signe.split(".")[1]))
    assert revendications == {"aud": "https://web.push.apple.com", "exp": 1_000 + 12 * 3600, "sub": "https://www.assista-crise.fr"}
    brute = depuis_b64url(signature)
    cle.public_key().verify(encode_dss_signature(int.from_bytes(brute[:32], "big"), int.from_bytes(brute[32:], "big")),
                            signe.encode(), ec.ECDSA(hashes.SHA256()))


def test_envoyer_chiffre_signe_et_signale_un_abonnement_expire():
    cle = ec.generate_private_key(ec.SECP256R1())
    navigateur = ec.generate_private_key(ec.SECP256R1())
    p256dh = b64url(navigateur.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    abonnement = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": p256dh, "auth": AUTH}}
    appels = []

    class Reponse:
        def __init__(self, statut): self.status_code = statut

    def poster(url, data, headers, timeout, allow_redirects):
        appels.append((url, data, headers, allow_redirects))
        return Reponse(201)

    assert web_push.envoyer(abonnement, {"titre": "Essai"}, urgent=True, cle=cle, poster=poster) == 201
    url, corps, entetes, redirections = appels[0]
    assert url == "https://web.push.apple.com/abc" and redirections is False
    assert entetes["Content-Encoding"] == "aes128gcm" and entetes["Urgency"] == "high"
    assert entetes["Authorization"].startswith("vapid t=")
    assert json.loads(dechiffrer(corps, navigateur, depuis_b64url(AUTH))) == {"titre": "Essai"}

    with pytest.raises(web_push.AbonnementExpire):
        web_push.envoyer(abonnement, {"titre": "Essai"}, cle=cle, poster=lambda *a, **k: Reponse(410))


def test_sans_secret_pas_de_cle(tmp_path, monkeypatch):
    monkeypatch.setenv("VAPID_PRIVE_FILE", str(tmp_path / "absent.pem"))
    assert web_push.cle_privee() is None and web_push.cle_publique_b64url() is None
    cle = ec.generate_private_key(ec.SECP256R1())
    (tmp_path / "vapid.pem").write_bytes(cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
    monkeypatch.setenv("VAPID_PRIVE_FILE", str(tmp_path / "vapid.pem"))
    assert web_push.cle_publique_b64url() == web_push.cle_publique_b64url(cle)
