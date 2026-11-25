package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Préparer la radio d'un intervenant (25/11/2026, vision d'Olivier F4GLD et de Sylvain) : les
 * emplacements 5, 6 et 7 servent en cas d'urgence — 5 = canal de la crise, 6 = canal de l'équipe,
 * 7 = canal de la commune. « Tu vires des canaux, tu choisis lesquels, tu enregistres leur
 * config, tu crées tes canaux de crise et à la fin tu restaures. »
 */
@Serializable
data class PlanUrgenceServeur(
    val equipe: String,
    @SerialName("nom_equipe") val nomEquipe: String = "",
    val indicatif: String = "",
    val crise: String? = null,
    @SerialName("nom_crise") val nomCrise: String? = null,
    val version: String = "",
    val meshtastic: List<EntreeUrgence> = emptyList(),
    val meshcore: List<EntreeUrgence> = emptyList(),
)

@Serializable
data class EntreeUrgence(val role: String, val nom: String, @SerialName("cle_hex") val cleHex: String = "", val version: String = "")

/** Un emplacement de la radio, tel qu'elle le décrit (clé comprise). `actif` faux = vide. */
@Serializable
data class CanalComplet(val index: Int, val nom: String, val cleHex: String, val actif: Boolean = true)

/** Ce que l'application propose pour un canal du plan. */
data class Proposition(
    val entree: EntreeUrgence,
    /** Déjà sur la radio (même nom ET même clé) : utilisé tel quel, rien d'écrit. */
    val dejaPresent: Int?,
    /** L'emplacement visé (modifiable par l'intervenant), null si déjà présent. */
    val emplacement: Int?,
    /** Ce qui occupe l'emplacement visé, et sera sauvegardé puis remplacé. */
    val remplace: CanalComplet?,
)

/** La radio telle qu'avant nos écritures : rangée chiffrée sur le téléphone, jamais envoyée. */
@Serializable
data class SauvegardeRadio(
    val radio: String,
    val protocole: String,
    val date: Long,
    val equipe: String = "",
    val crise: String? = null,
    val table: List<CanalComplet>,
    /** Ce que nous avons écrit : emplacement → canal. */
    val ecrits: List<CanalComplet>,
    /** Rôle de chaque emplacement écrit (« crise », « equipe », « commune »). */
    val roles: Map<Int, String> = emptyMap(),
)

/** Une action de restauration : remettre `vers` (ou vider si null) dans `index`. */
data class ActionRestauration(val index: Int, val vers: CanalComplet?, val modifieDepuis: Boolean = false)

object PlanUrgence {
    val ROLES = listOf("crise", "equipe", "commune")

    /** Les emplacements proposés par rôle : Meshtastic 5, 6, 7 ; MeshCore les trois derniers. */
    fun emplacementsParDefaut(meshcore: Boolean, total: Int = 40): Map<String, Int> =
        if (meshcore) mapOf("crise" to total - 3, "equipe" to total - 2, "commune" to total - 1)
        else mapOf("crise" to 5, "equipe" to 6, "commune" to 7)

    private fun memeCanal(a: CanalComplet, nom: String, cleHex: String) =
        a.actif && PlanRadio.normaliser(a.nom) == PlanRadio.normaliser(nom) && a.cleHex.equals(cleHex, ignoreCase = true)

    /** Pour chaque canal du plan : déjà présent, ou l'emplacement visé et ce qu'il remplace.
     * `choix` : emplacements changés par l'intervenant (rôle → emplacement). */
    fun proposer(entrees: List<EntreeUrgence>, table: List<CanalComplet>, meshcore: Boolean,
                 choix: Map<String, Int> = emptyMap(), total: Int = 40): List<Proposition> {
        val defaut = emplacementsParDefaut(meshcore, total)
        return entrees.map { e ->
            val present = table.firstOrNull { memeCanal(it, e.nom, e.cleHex) }
            if (present != null) Proposition(e, present.index, null, null)
            else {
                val i = choix[e.role] ?: defaut.getValue(e.role)
                Proposition(e, null, i, table.firstOrNull { it.index == i && it.actif })
            }
        }
    }

    /** Refuse un choix impossible : le canal principal (0), ou deux canaux au même endroit. */
    fun erreur(propositions: List<Proposition>, total: Int): String? {
        val cibles = propositions.mapNotNull { it.emplacement }
        if (cibles.any { it <= 0 || it >= total }) return "Emplacement 1 à ${total - 1} (le 0 est le canal principal)."
        if (cibles.toSet().size != cibles.size) return "Deux canaux ne peuvent pas aller dans le même emplacement."
        return null
    }

    /** Ce qu'il faut écrire (dans l'ordre) pour appliquer les propositions. */
    fun aEcrire(propositions: List<Proposition>): List<Pair<Int, EntreeUrgence>> =
        propositions.mapNotNull { p -> p.emplacement?.let { it to p.entree } }

    /**
     * Remettre la radio comme avant : chaque emplacement écrit retrouve son contenu d'origine
     * (ou est vidé). Un emplacement modifié à la main depuis (il ne porte plus ce que nous y
     * avons écrit) est laissé tel quel et signalé. `garderEquipe` : le canal de l'équipe reste.
     */
    fun restaurer(sauvegarde: SauvegardeRadio, actuelle: List<CanalComplet>, garderEquipe: Boolean): List<ActionRestauration> =
        sauvegarde.ecrits.mapNotNull { ecrit ->
            if (garderEquipe && sauvegarde.roles[ecrit.index] == "equipe") return@mapNotNull null
            val maintenant = actuelle.firstOrNull { it.index == ecrit.index }
            val toujoursLeNotre = maintenant != null && memeCanal(maintenant, ecrit.nom, ecrit.cleHex)
            val origine = sauvegarde.table.firstOrNull { it.index == ecrit.index && it.actif }
            ActionRestauration(ecrit.index, origine, modifieDepuis = !toujoursLeNotre)
        }

    // --- Lien de canal Meshtastic (QR code) -----------------------------------------------

    /** [(nom, clé hex)] → « https://meshtastic.org/e/?add=true#… » (ChannelSet), lisible par
     * l'application Meshtastic officielle ; le mode « ajouter » n'efface pas ses canaux. */
    fun lienMeshtastic(canaux: List<Pair<String, String>>, ajouter: Boolean = true): String {
        val corps = mutableListOf<Byte>()
        fun varint(v: Long, dans: MutableList<Byte>) { var x = v; while (x >= 0x80) { dans += ((x and 0x7f) or 0x80).toByte(); x = x ushr 7 }; dans += x.toByte() }
        fun champ(n: Int, octets: List<Byte>, dans: MutableList<Byte>) { varint(((n shl 3) or 2).toLong(), dans); varint(octets.size.toLong(), dans); dans += octets }
        for ((nom, cle) in canaux) {
            val reglages = mutableListOf<Byte>()
            if (cle.isNotEmpty()) champ(2, cle.chunked(2).map { it.toInt(16).toByte() }, reglages)
            champ(3, nom.encodeToByteArray().toList(), reglages)
            champ(1, reglages, corps)
        }
        return "https://meshtastic.org/e/" + (if (ajouter) "?add=true" else "") + "#" + base64Url(corps.toByteArray())
    }

    private const val ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

    fun base64Url(o: ByteArray): String = buildString {
        var i = 0
        while (i < o.size) {
            val b0 = o[i].toInt() and 0xff
            val b1 = if (i + 1 < o.size) o[i + 1].toInt() and 0xff else -1
            val b2 = if (i + 2 < o.size) o[i + 2].toInt() and 0xff else -1
            append(ALPHABET[b0 shr 2])
            append(ALPHABET[((b0 and 3) shl 4) or (if (b1 >= 0) b1 shr 4 else 0)])
            if (b1 >= 0) append(ALPHABET[((b1 and 15) shl 2) or (if (b2 >= 0) b2 shr 6 else 0)])
            if (b2 >= 0) append(ALPHABET[b2 and 63])
            i += 3
        }
    }
}
