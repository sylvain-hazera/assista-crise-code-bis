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
}
