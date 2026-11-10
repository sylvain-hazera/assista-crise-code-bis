"""Tests de admin_meshcore.py, avec un faux companion.

    docker run --rm -v "$PWD/meshcore-bridge":/src -w /src \
      --entrypoint python assista-crise-meshcore-bridge:prod -m unittest -v test_admin_meshcore

`unittest` plutôt que pytest : l'image du pont n'embarque pas de dépendance de test, et n'a pas
à en embarquer pour deux fichiers.

Ce qui est verrouillé ici vient du firmware MeshCore (`src/helpers/CommonCLI.cpp`, lu le
10/11/2026) : `tempradio` exige un délai de retour strictement positif, la fréquence est lue par
`strtof` (donc jamais de virgule décimale ni de notation scientifique), et une session se
rouvre à chaque opération parce qu'elle expire.
"""
import asyncio
import unittest

import admin_meshcore as mod


def executer(coroutine):
    return asyncio.run(coroutine)


class FausseCommandes:
    """Imite le strict nécessaire de `meshcore.commands`."""

    def __init__(self, login=object(), statut=object(), commande=object()):
        self.appels = []
        self._login, self._statut, self._commande = login, statut, commande

    async def send_login_sync(self, dst, pwd, **kwargs):
        self.appels.append(("login", dst, pwd))
        return self._login

    async def req_status_sync(self, contact, **kwargs):
        self.appels.append(("statut", contact))
        return self._statut

    async def req_neighbours_sync(self, contact, **kwargs):
        self.appels.append(("voisins", contact))
        return self._statut

    async def req_regions_sync(self, contact, **kwargs):
        self.appels.append(("regions", contact))
        return self._statut

    async def req_telemetry_sync(self, contact, **kwargs):
        self.appels.append(("telemetrie", contact))
        return self._statut

    async def send_cmd(self, dst, cmd, **kwargs):
        self.appels.append(("cmd", dst, cmd))
        return self._commande


class FauxCompagnon:
    def __init__(self, **kwargs):
        self.commands = FausseCommandes(**kwargs)


CIBLE = "ab" * 32


def tache(type_tache, **extra):
    base = {"pubkey_cible": CIBLE, "type_tache": type_tache, "parametres": None,
            "moyen_admin": "ACL", "mot_de_passe": ""}
    base.update(extra)
    return base


class TestConstructionDesCommandes(unittest.TestCase):

    def test_tempradio_est_ecrit_comme_le_firmware_l_attend(self):
        commande = mod.construire_commande(tache(
            mod.RADIO_TEMPORAIRE,
            parametres={"frequence_mhz": 869.525, "bande_khz": 250, "facteur_etalement": 11,
                        "taux_codage": 5, "minutes": 10},
        ))
        self.assertEqual(commande, "tempradio 869.525 250 11 5 10")

    def test_une_frequence_n_est_jamais_ecrite_en_notation_scientifique(self):
        """Le firmware lit la fréquence avec `strtof` : un `8.695e2` partirait quand même, pour
        revenir en « Error, invalid params » une minute plus tard."""
        commande = mod.construire_commande(tache(
            mod.RADIO_TEMPORAIRE,
            parametres={"frequence_mhz": 869.4625, "bande_khz": 62.5, "facteur_etalement": 12,
                        "taux_codage": 8, "minutes": 1},
        ))
        self.assertEqual(commande, "tempradio 869.4625 62.5 12 8 1")
        self.assertNotIn("e", commande.replace("tempradio", ""))
        self.assertNotIn(",", commande)

    def test_un_delai_de_retour_nul_est_refuse_meme_ici(self):
        """Déjà refusé par l'API, revérifié dans le pont : c'est la garde qui fait qu'un essai
        raté se rattrape tout seul, elle ne doit dépendre d'aucun appelant."""
        with self.assertRaises(mod.ErreurAdminMeshCore):
            mod.construire_commande(tache(
                mod.RADIO_TEMPORAIRE,
                parametres={"frequence_mhz": 869.5, "bande_khz": 250, "facteur_etalement": 11,
                            "taux_codage": 5, "minutes": 0},
            ))

    def test_un_reglage_devient_set_cle_valeur(self):
        commande = mod.construire_commande(tache(
            mod.DEFINIR_REGLAGE, parametres={"cle": "advert.interval", "valeur": "240"},
        ))
        self.assertEqual(commande, "set advert.interval 240")

    def test_une_cle_avec_espace_est_refusee(self):
        """Sinon « set a b c » poserait un réglage qu'on n'a pas voulu."""
        with self.assertRaises(mod.ErreurAdminMeshCore):
            mod.construire_commande(tache(
                mod.DEFINIR_REGLAGE, parametres={"cle": "advert interval", "valeur": "240"},
            ))

    def test_les_commandes_sans_parametre(self):
        self.assertEqual(mod.construire_commande(tache(mod.ANNONCER)), "advert")
        self.assertEqual(mod.construire_commande(tache(mod.REDEMARRER)), "reboot")

    def test_une_lecture_n_a_pas_de_commande_texte(self):
        self.assertIsNone(mod.construire_commande(tache(mod.LIRE_STATUT)))


class TestVerificationDAcces(unittest.TestCase):

    def test_la_voie_mot_de_passe_ouvre_une_session(self):
        compagnon = FauxCompagnon()
        reponse, erreur = executer(mod.executer_tache(compagnon, tache(
            mod.VERIFIER_ACCES, moyen_admin="MOT_DE_PASSE", mot_de_passe="secret",
        )))
        self.assertIsNone(erreur)
        self.assertEqual(reponse, {"preuve": "session ouverte"})
        self.assertEqual(compagnon.commands.appels, [("login", CIBLE, "secret")])

    def test_un_mot_de_passe_refuse_est_un_echec_explicite(self):
        compagnon = FauxCompagnon(login=None)
        reponse, erreur = executer(mod.executer_tache(compagnon, tache(
            mod.VERIFIER_ACCES, moyen_admin="MOT_DE_PASSE", mot_de_passe="faux",
        )))
        self.assertIsNone(reponse)
        self.assertIn("mot de passe faux", erreur.lower())

    def test_la_voie_acl_interroge_le_statut(self):
        """Pas de mot de passe : le répéteur répond parce que notre clé est dans son ACL."""
        compagnon = FauxCompagnon()
        reponse, erreur = executer(mod.executer_tache(compagnon, tache(mod.VERIFIER_ACCES)))
        self.assertIsNone(erreur)
        self.assertIn("preuve", reponse)
        self.assertEqual(compagnon.commands.appels, [("statut", CIBLE)])

    def test_un_repeteur_muet_ne_prouve_rien(self):
        compagnon = FauxCompagnon(statut=None)
        reponse, erreur = executer(mod.executer_tache(compagnon, tache(mod.VERIFIER_ACCES)))
        self.assertIsNone(reponse)
        self.assertIn("ACL", erreur)

    def test_un_mot_de_passe_annonce_mais_absent_est_signale(self):
        """Ne jamais essayer « sans mot de passe » à la place : le firmware vérifierait alors
        l'ACL, et un succès ferait croire à une preuve qui n'a pas été faite."""
        compagnon = FauxCompagnon()
        reponse, erreur = executer(mod.executer_tache(compagnon, tache(
            mod.VERIFIER_ACCES, moyen_admin="MOT_DE_PASSE", mot_de_passe="",
        )))
        self.assertIsNone(reponse)
        self.assertIn("API", erreur)
        self.assertEqual(compagnon.commands.appels, [])


class TestExecution(unittest.TestCase):

    def test_une_ecriture_ouvre_la_session_avant_la_commande(self):
        compagnon = FauxCompagnon()
        reponse, erreur = executer(mod.executer_tache(compagnon, tache(
            mod.REDEMARRER, moyen_admin="MOT_DE_PASSE", mot_de_passe="secret",
        )))
        self.assertIsNone(erreur)
        self.assertEqual(
            compagnon.commands.appels,
            [("login", CIBLE, "secret"), ("cmd", CIBLE, "reboot")],
        )

    def test_une_ecriture_en_acl_n_ouvre_pas_de_session(self):
        compagnon = FauxCompagnon()
        executer(mod.executer_tache(compagnon, tache(mod.ANNONCER)))
        self.assertEqual(compagnon.commands.appels, [("cmd", CIBLE, "advert")])

    def test_une_session_refusee_empeche_la_commande(self):
        """Et c'est l'essentiel : sans ça on enverrait une commande non authentifiée, que le
        répéteur traiterait selon son ACL — donc peut-être."""
        compagnon = FauxCompagnon(login=None)
        reponse, erreur = executer(mod.executer_tache(compagnon, tache(
            mod.REDEMARRER, moyen_admin="MOT_DE_PASSE", mot_de_passe="faux",
        )))
        self.assertIsNone(reponse)
        self.assertEqual(len(compagnon.commands.appels), 1)   # le login seul

    def test_les_quatre_lectures_appellent_la_bonne_requete(self):
        for type_tache, attendu in [
            (mod.LIRE_STATUT, "statut"), (mod.LIRE_VOISINS, "voisins"),
            (mod.LIRE_REGIONS, "regions"), (mod.LIRE_TELEMETRIE, "telemetrie"),
        ]:
            compagnon = FauxCompagnon()
            reponse, erreur = executer(mod.executer_tache(compagnon, tache(type_tache)))
            self.assertIsNone(erreur, type_tache)
            self.assertEqual(compagnon.commands.appels, [(attendu, CIBLE)])

    def test_un_type_inconnu_ne_part_pas_sur_la_radio(self):
        compagnon = FauxCompagnon()
        reponse, erreur = executer(mod.executer_tache(compagnon, tache("INVENTE")))
        self.assertIsNone(reponse)
        self.assertIn("inconnu", erreur)
        self.assertEqual(compagnon.commands.appels, [])

    def test_une_exception_inattendue_devient_un_message(self):
        """Une tâche qui lève ne doit pas tuer la boucle du pont : elle revient en échec avec
        son message, et le réessai est décidé par l'API."""
        class Explosif(FausseCommandes):
            async def req_status_sync(self, contact, **kwargs):
                raise RuntimeError("liaison coupee")

        compagnon = FauxCompagnon()
        compagnon.commands = Explosif()
        reponse, erreur = executer(mod.executer_tache(compagnon, tache(mod.LIRE_STATUT)))
        self.assertIsNone(reponse)
        self.assertIn("liaison coupee", erreur)


if __name__ == "__main__":
    unittest.main()
