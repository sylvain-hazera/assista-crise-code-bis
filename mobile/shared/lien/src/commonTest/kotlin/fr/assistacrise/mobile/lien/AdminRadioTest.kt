package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.meshcore.AdminMeshCore
import fr.assistacrise.mobile.lien.meshtastic.AdminMeshtastic
import fr.assistacrise.mobile.lien.meshtastic.CanalMeshtastic
import fr.assistacrise.mobile.lien.meshtastic.Conteneur
import fr.assistacrise.mobile.lien.meshtastic.SchemaMeshtastic
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * « Utilisateur radio avancé » (22/11/2026). Vecteurs Meshtastic produits par la bibliothèque
 * officielle (`AdminMessage.SerializeToString()`) ; trames MeshCore construites comme le fait la
 * bibliothèque `meshcore` du pont.
 */
class AdminMeshtasticTest {
    private val lora = SchemaMeshtastic.config.first { it.cle == "lora" }
    private val position = SchemaMeshtastic.config.first { it.cle == "position" }

    @Test fun demandesDeConfiguration() {
        assertEquals("2800", AdminMeshtastic.demanderConfig(SchemaMeshtastic.config.first { it.cle == "device" }).enHex())
        assertEquals("3805", AdminMeshtastic.demanderConfig(SchemaMeshtastic.modules.first { it.cle == "telemetry" }).enHex())
    }

    @Test fun ecrireLaSectionLoRaCommeLaBibliothequeOfficielle() {
        val valeurs = AdminMeshtastic.lireSection(lora, ByteArray(0)).toMutableMap()
        valeurs[1] = true; valeurs[2] = 3L; valeurs[7] = 3L; valeurs[8] = 3L; valeurs[9] = true; valeurs[10] = 27L
        val contenu = AdminMeshtastic.ecrireSection(lora, ByteArray(0), valeurs)
        assertEquals("08011003380340034801501b", contenu.enHex())
        assertEquals("92020e320c08011003380340034801501b", AdminMeshtastic.ecrireConfig(lora, contenu).enHex())
        // Relu : les mêmes valeurs.
        val relu = AdminMeshtastic.lireSection(lora, contenu)
        assertEquals(27L, relu[10]); assertEquals(true, relu[9])
    }

    @Test fun cequeLApplicationNeConnaitPasEstGarde() {
        // Un champ 99 inconnu du schéma, venu de la radio : il doit survivre à l'écriture.
        val origine = "0884072001".depuisHex() + byteArrayOf(0x98.toByte(), 0x06, 0x01)
        val valeurs = AdminMeshtastic.lireSection(position, origine).toMutableMap()
        assertEquals(900L, valeurs[1]); assertEquals(true, valeurs[4])
        valeurs[1] = 1800L
        val ecrit = AdminMeshtastic.ecrireSection(position, origine, valeurs)
        assertTrue(ecrit.enHex().endsWith("980601"), ecrit.enHex())
        assertEquals(1800L, AdminMeshtastic.lireSection(position, ecrit)[1])
    }

    @Test fun canalEtProprietaire() {
        val c = CanalMeshtastic(index = 1, nom = "alpha", role = 2, psk = ByteArray(16) { it.toByte() }, precisionPosition = 13)
        assertEquals("8a02230801121d1210000102030405060708090a0b0c0d0e0f1a05616c7068613a02080d1802", AdminMeshtastic.ecrireCanal(c).enHex())
        assertEquals("820210120a4c6561204d617274696e1a024c4d", AdminMeshtastic.ecrireProprietaire("Lea Martin", "LM").enHex())
        assertEquals("880602", AdminMeshtastic.redemarrer(2).enHex())
    }

    @Test fun lireUneReponseDeConfigurationEtUnCanal() {
        // FromRadio{config(5): Config{lora(6): …}}
        val lora = "08011003380340034801501b".depuisHex()
        val config = byteArrayOf(0x32, lora.size.toByte()) + lora
        val trame = byteArrayOf(0x2a, config.size.toByte()) + config
        val lu = AdminMeshtastic.lire(trame) as AdminMeshtastic.Lu.Config
        assertEquals(Conteneur.CONFIG, lu.conteneur); assertEquals(6, lu.numero); assertEquals(lora.enHex(), lu.contenu.enHex())
        // FromRadio{channel(10): Channel}
        val canal = "0801121d1210000102030405060708090a0b0c0d0e0f1a05616c7068613a02080d1802".depuisHex()
        val c = (AdminMeshtastic.lire(byteArrayOf(0x52, canal.size.toByte()) + canal) as AdminMeshtastic.Lu.Canal).canal
        assertEquals(listOf(1, 2, 16, 13), listOf(c.index, c.role, c.psk.size, c.precisionPosition)); assertEquals("alpha", c.nom)
    }

    @Test fun leSchemaCouvreToutesLesSections() {
        assertTrue(SchemaMeshtastic.config.map { it.cle }.containsAll(listOf("device", "position", "power", "network", "display", "lora", "bluetooth", "security")))
        assertTrue(SchemaMeshtastic.modules.size >= 13)
        assertTrue(lora.champs.first { it.nom == "region" }.sensible)
    }
}

class AdminMeshCoreTest {
    @Test fun tramesCommeLaBibliothequeMeshcore() {
        val secret = "ce3607029a25326c64770e9f4b8c5e9d".depuisHex()
        assertEquals("200223616c7068610000000000000000000000000000000000000000000000000000ce3607029a25326c64770e9f4b8c5e9d",
            AdminMeshCore.ecrireCanal(2, "#alpha", secret).enHex())
        assertEquals("0b95440d0090d003000b05", AdminMeshCore.ecrireRadio(869.525, 250.0, 11, 5).enHex())
        assertEquals("0c16000000", AdminMeshCore.ecrirePuissance(22).enHex())
        assertEquals("0e4034ac026026f7ff00000000", AdminMeshCore.ecrirePosition(44.84, -0.58).enHex())
        assertEquals("2601090100", AdminMeshCore.ecrireAutresReglages(true, 1, 2, 0, 1, 0).enHex())
        assertEquals("2540e20100", AdminMeshCore.ecrireCodeBluetooth(123456).enHex())
        assertEquals("13" + "reboot".encodeToByteArray().enHex(), AdminMeshCore.redemarrer().enHex())
    }

    @Test fun lireUnContactEtSelfInfo() {
        val pub = ByteArray(32) { (it + 1).toByte() }
        val contact = byteArrayOf(3) + pub + byteArrayOf(2, 0, 2) + ByteArray(64) + "Relais Haillan".encodeToByteArray().copyOf(32) +
            byteArrayOf(0x10, 0, 0, 0) + byteArrayOf(0x40, 0x34, 0xac.toByte(), 0x02) + byteArrayOf(0x60, 0x26, 0xf7.toByte(), 0xff.toByte())
        val c = assertNotNull(AdminMeshCore.lireContact(contact))
        assertEquals("Relais Haillan", c.nom); assertEquals("Répéteur", c.genre); assertEquals("2 saut(s)", c.libelleChemin)
        assertEquals(44.84, c.latitude, 1e-6); assertEquals(-0.58, c.longitude, 1e-6)

        val moi = byteArrayOf(5, 1, 22, 30) + pub + byteArrayOf(0x40, 0x34, 0xac.toByte(), 0x02, 0x60, 0x26, 0xf7.toByte(), 0xff.toByte()) +
            byteArrayOf(0, 1, 0x09, 1) + "95440d00".depuisHex() + "90d00300".depuisHex() + byteArrayOf(11, 5) + "Lea".encodeToByteArray()
        val m = assertNotNull(AdminMeshCore.lireMoi(moi))
        assertEquals(listOf(22, 30, 11, 5), listOf(m.puissance, m.puissanceMax, m.facteurEtalement, m.tauxCodage))
        assertEquals(869.525, m.frequenceMhz, 1e-9); assertEquals("Lea", m.nom); assertEquals(2, m.telemetriePosition)
    }
}

class MessagesDirectsTest {
    @Test fun meshtasticUnMessageAdresseAMonNoeudEstUnDirect() {
        val p = PiloteMeshtastic { 7L }
        // FromRadio{my_info{my_node_num = 0x1234}} puis FromRadio{packet{from, to = mon nœud, decoded{port 1, "salut"}}}
        p.recevoir(fr.assistacrise.mobile.lien.meshtastic.Ecrivain().message(3, fr.assistacrise.mobile.lien.meshtastic.Ecrivain().varint(1, 0x1234)).fin())
        val donnees = fr.assistacrise.mobile.lien.meshtastic.Ecrivain().varint(1, 1).brut(2, "salut".encodeToByteArray())
        val paquet = fr.assistacrise.mobile.lien.meshtastic.Ecrivain().fixe32(1, 0xabcdefL).fixe32(2, 0x1234).message(4, donnees).fixe32(6, 99)
        val r = p.recevoir(fr.assistacrise.mobile.lien.meshtastic.Ecrivain().message(2, paquet).fin())
        assertEquals(listOf(MessageDirect("!00abcdef", "salut", Reception(), id = 99)), r.directs)
        assertTrue(r.messages.isEmpty())
    }

    @Test fun meshcoreUnMessageDeContactEstUnDirect() {
        val p = PiloteMeshCore()
        val trame = byteArrayOf(7) + "a1b2c3d4e5f6".depuisHex() + byteArrayOf(0, 0) + byteArrayOf(0x10, 0, 0, 0) + "coucou".encodeToByteArray()
        val r = p.recevoir(trame)
        assertEquals(listOf(MessageDirect("a1b2c3d4e5f6", "coucou", Reception(sauts = 0), horodatageS = 16)), r.directs)   // chemin 0 : sans relais
    }
}
