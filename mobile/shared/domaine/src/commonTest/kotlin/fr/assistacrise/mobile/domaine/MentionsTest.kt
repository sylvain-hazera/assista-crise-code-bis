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
}
