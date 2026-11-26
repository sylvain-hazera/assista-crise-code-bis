package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class MentionsTest {
    private val moi = listOf("Léa", "Léa Martin", "LEA1")

    @Test fun lesFormesDeMention() {
        assertTrue(Mentions.mentionne("@lea tu es où ?", moi))
        assertTrue(Mentions.mentionne("Max: rdv au pont @Léa Martin", moi))
        assertTrue(Mentions.mentionne("@[Léa Martin] reçu ?", moi))
        assertTrue(Mentions.mentionne("ok @LEA1, merci", moi))
    }

    @Test fun ceQuiNEnEstPas() {
        assertFalse(Mentions.mentionne("Léa est arrivée", moi))
        assertFalse(Mentions.mentionne("@Léandre tu es où ?", moi))
        assertFalse(Mentions.mentionne("lea@exemple.fr", moi))
        assertFalse(Mentions.mentionne("@ALPHA on arrive", moi))
    }

    @Test fun taguerEtRepondre() {
        kotlin.test.assertEquals("@[Léa]", Mentions.etiquette("Léa"))   // forme MeshCore, même pour un seul mot
        kotlin.test.assertEquals("@[Léa]", Mentions.etiquette("@Léa"))
        kotlin.test.assertEquals("@[Léa Martin]", Mentions.etiquette("Léa Martin"))
        val r = Mentions.reponse("Léa Martin", "rendez-vous au pont de la D88 dans dix minutes", "c'est noté")
        kotlin.test.assertEquals("↪ @[Léa Martin] « rendez-vous au pont de la D88… » c'est noté", r)
        assertTrue(Mentions.mentionne(r, moi))   // la personne à qui l'on répond est notifiée
    }

    @Test fun reponseALaManiereDeMeshCore() {
        val r = Mentions.reponseRadio("Léa Martin", "  c'est noté ")
        kotlin.test.assertEquals("@[Léa Martin] c'est noté", r)
        kotlin.test.assertEquals("Léa Martin" to "c'est noté", Mentions.lireReponse(r))
        kotlin.test.assertEquals(null, Mentions.lireReponse("pas de réponse ici"))
        assertTrue(Mentions.mentionne(r, moi))
    }
}
