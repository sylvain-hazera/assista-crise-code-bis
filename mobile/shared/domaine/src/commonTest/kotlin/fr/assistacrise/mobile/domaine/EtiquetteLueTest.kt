package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class EtiquetteLueTest {
    @Test fun uneEtiquetteRecueSeLitEtSonLibelleNeSeRepetePas() {
        val texte = EtiquetteTerrain.ecrire(TypeMessageTerrain.DANGER, "3f2a9c11", "9c1e0b44", "a1b2c3", "Mur fissuré")
        assertEquals(EtiquetteTerrain.Lue(TypeMessageTerrain.DANGER, "Mur fissuré"), EtiquetteTerrain.lire(texte))
        assertEquals(TypeMessageTerrain.ARRIVE, EtiquetteTerrain.lire("Léa: " + EtiquetteTerrain.ecrire(TypeMessageTerrain.ARRIVE, null, "9c1e0b44", "a1b2c3"))?.type)
        assertNull(EtiquetteTerrain.lire("Bonjour du côté de Bordeaux"))
    }
}
