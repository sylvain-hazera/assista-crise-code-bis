package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlin.test.assertFalse

/** Vecteurs repris des tests de meshcore-open (test/reaction_helper_test.dart) et du NIST. */
class ReactionsRadioTest {
    private fun hex(b: ByteArray) = b.joinToString("") { (it.toInt() and 0xff).toString(16).padStart(2, '0') }

    @Test fun sha256_sur_plusieurs_blocs() {
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", hex(sha256(ByteArray(0))))
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", hex(sha256("abc".encodeToByteArray())))
        assertEquals("248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
            hex(sha256("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq".encodeToByteArray())))
        assertEquals(SHA_200_A, hex(sha256(ByteArray(200) { 'a'.code.toByte() })))
    }

    @Test fun empreinte_meshcoreone() {
        assertEquals("tyvbkb33", ReactionsRadio.empreinteMc1("Hello world!", 1234567890))
    }

    @Test fun empreinte_meshcore_open() {
        assertEquals("e779", ReactionsRadio.empreinteOpen(1700000000, "Bob", "hello"))
        assertEquals("b5bd", ReactionsRadio.empreinteOpen(1700000000, null, "hi"))
        assertEquals("7fee", ReactionsRadio.empreinteOpen(1700000000, "Привет😀", "x"))
    }

    @Test fun ecrire_puis_relire_sur_un_canal() {
        val t = ReactionsRadio.ecrire("👍", "Hello world!", 1234567890, "Alice")
        assertEquals("@[Alice]👍\ntyvbkb33", t)
        val r = ReactionsRadio.lire(t)!!
        assertEquals("👍", r.emoji)
        assertEquals("Alice", r.auteurVise)
        assertTrue(ReactionsRadio.vise(r, "Hello world!", 1234567890, "Alice"))
        assertFalse(ReactionsRadio.vise(r, "Hello world!", 1234567890, "Bob"))
        assertFalse(ReactionsRadio.vise(r, "Hello world!", 1234567891, "Alice"))
    }

    @Test fun direct_et_ancien_ordre() {
        val d = ReactionsRadio.lire("🥳\nb3je6qf7")!!
        assertEquals("🥳", d.emoji); assertNull(d.auteurVise)
        val a = ReactionsRadio.lire("🥳@[entropy 📓]\nb3je6qf7")!!
        assertEquals("🥳", a.emoji); assertEquals("entropy 📓", a.auteurVise)
    }

    @Test fun format_meshcore_open() {
        val r = ReactionsRadio.lire("r:e779:00")!!
        assertEquals("👍", r.emoji)
        assertTrue(ReactionsRadio.vise(r, "hello", 1700000000, "Bob"))
        assertEquals("❤️", ReactionsRadio.lire("r:e779:01")!!.emoji)
    }

    @Test fun pas_de_faux_positifs() {
        assertNull(ReactionsRadio.lire("test\nabcdefgh"))
        assertNull(ReactionsRadio.lire("🥳\nhashistoolong"))
        assertNull(ReactionsRadio.lire("@[Léa] rdv au pont\nabcdefgh"))
        assertNull(ReactionsRadio.lire("bonjour"))
        assertNull(ReactionsRadio.lire("r:e779:ff"))
    }

    private companion object {
        const val SHA_200_A = "c2a908d98f5df987ade41b5fce213067efbcc21ef2240212a41e54b5e7c28ae5"
    }
}
