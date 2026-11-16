package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DomaineTest {
    private val valide = Inscription(
        prenom = "Camille", nom = "Durand", email = "camille@exemple.fr",
        telephone = "06 12 34 56 78", codePostal = "71000", motDePasse = "Abcdef1!",
        conditionsAcceptees = true,
    )

    @Test fun uneInscriptionCompleteEstRecevable() {
        assertEquals(emptyMap(), validerInscription(valide))
    }

    @Test fun chaqueChampFautifEstNommeParSaCleDApi() {
        val erreurs = validerInscription(Inscription())
        assertEquals(
            setOf(Champs.PRENOM, Champs.NOM, Champs.EMAIL, Champs.TELEPHONE, Champs.CODE_POSTAL,
                Champs.MOT_DE_PASSE, Champs.CONDITIONS),
            erreurs.keys,
        )
    }

    @Test fun leMotDePasseExigeLesCinqConditions() {
        assertTrue(ForceMotDePasse.de("Abcdef1!").suffisante)
        assertFalse(ForceMotDePasse.de("abcdef1!").suffisante)   // pas de majuscule
        assertFalse(ForceMotDePasse.de("ABCDEF1!").suffisante)   // pas de minuscule
        assertFalse(ForceMotDePasse.de("Abcdefg!").suffisante)   // pas de chiffre
        assertFalse(ForceMotDePasse.de("Abcdefg1").suffisante)   // pas de caractère spécial
        assertFalse(ForceMotDePasse.de("Abc1!").suffisante)      // trop court
    }

    @Test fun lesNumerosFrancaisUsuelsPassent() {
        for (numero in listOf("0612345678", "06 12 34 56 78", "+33 6 12 34 56 78", "06.12.34.56.78")) {
            assertFalse(Champs.TELEPHONE in validerInscription(valide.copy(telephone = numero)), numero)
        }
        assertTrue(Champs.TELEPHONE in validerInscription(valide.copy(telephone = "12345")))
    }

    @Test fun leModeVientDuCompteEtNonDUnReglage() {
        assertEquals(Mode.CITOYEN, Compte(id = "1").mode)
        assertEquals(Mode.INTERVENANT, Compte(id = "1", institutionId = "i").mode)
        assertEquals(Mode.INTERVENANT, Compte(id = "1", type = "ADMIN").mode)
        assertFalse(Compte(id = "1", institutionId = "i").peutPiloterLesMissions)
        assertTrue(Compte(id = "1", type = "SECOURS").peutPiloterLesMissions)
    }

    @Test fun laFileSuperposeLeDernierStatutDeclare() {
        val missions = listOf(Mission(id = "a", titre = "A"), Mission(id = "b", titre = "B"))
        fun action(n: Int, cible: String, statut: StatutMission, etat: EtatAction = EtatAction.EN_ATTENTE) =
            ActionEnAttente("$n", ActionEnAttente.GENRE_STATUT_MISSION, cible, statut.name, "", n.toLong(), etat = etat)
        val vue = superposerLaFile(
            missions,
            listOf(
                action(1, "a", StatutMission.EN_COURS),
                action(2, "a", StatutMission.TERMINEE),
                action(3, "b", StatutMission.EN_COURS, EtatAction.REFUSEE),
            ),
        )
        assertEquals(StatutMission.TERMINEE, vue[0].mission.statut)
        assertTrue(vue[0].nonConfirme)
        // Un refus ne maquille pas la mission : elle montre ce que le serveur a dit.
        assertEquals(StatutMission.EN_PREPARATION, vue[1].mission.statut)
        assertFalse(vue[1].nonConfirme)
    }

    @Test fun unStatutNeSauteQuUnCran() {
        assertEquals(listOf(StatutMission.EN_COURS), StatutMission.EN_PREPARATION.voisins())
        assertFalse(StatutMission.TERMINEE in StatutMission.EN_PREPARATION.voisins())
    }

    // ── Calcul anti-robot de la création de compte ────────────────────────────────────────

    @Test fun sha256DonneLesEmpreintesDeReference() {
        // Vecteurs FIPS 180-4 : sans eux, un défi du serveur ne serait jamais résolu.
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", sha256Hex(""))
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", sha256Hex("abc"))
        assertEquals("9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318", sha256Hex("a".repeat(55)))
    }

    @Test fun leDefiEstResoluAChaqueExtremiteDeLaPlage() {
        fun defi(nombre: Int, maximum: Int) = Defi("0123456789abcdef01234567", sha256Hex("0123456789abcdef01234567$nombre"), maximum, 0, 0, "")
        assertEquals(0, resoudreDefi(defi(0, 500)))
        assertEquals(137, resoudreDefi(defi(137, 500)))
        assertEquals(500, resoudreDefi(defi(500, 500)))
        assertEquals(1000, resoudreDefi(defi(1000, 1200)))     // le nombre de chiffres change en route
    }

    @Test fun unDefiSansSolutionOuMalFormeNeTournePasSansFin() {
        assertEquals(null, resoudreDefi(Defi("abc", sha256Hex("abc900"), 100, 0, 0, "")))
        assertEquals(null, resoudreDefi(Defi("abc", "pas-une-empreinte", 100, 0, 0, "")))
        // Un serveur compromis ne fait pas calculer le téléphone pendant des heures.
        assertEquals(null, resoudreDefi(Defi("abc", sha256Hex("abc1"), Int.MAX_VALUE, 0, 0, "")))
    }
}
