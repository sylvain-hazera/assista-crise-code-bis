package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Les messages de terrain en un geste (22/11/2026) : ce que l'intervenant signale au poste de
 * commandement, par les données, ou par radio quand le réseau manque. Le code est celui de
 * l'étiquette radio, lue par le serveur (backend/core/messages_terrain.py) : les deux listes
 * doivent rester identiques.
 */
enum class TypeMessageTerrain(
    val code: String,
    val libelle: String,
    val prioritaire: Boolean = false,
    /** Un texte est demandé : facultatif pour un danger, obligatoire pour les secours. */
    val demandeTexte: Boolean = false,
    val texteObligatoire: Boolean = false,
    val questionTexte: String = "",
    val demandeNombre: Boolean = false,
) {
    ARRIVE("ARR", "Arrivé sur les lieux"),
    SITUATION("SIT", "Message de situation", demandeTexte = true, texteObligatoire = true, questionTexte = "Votre message de situation"),
    TERMINEE("FIN", "Intervention terminée"),
    EN_ROUTE_SUIVANTE("SUIV", "En route vers l'intervention suivante"),
    DISPONIBLE("DISPO", "Disponible en retour"),
    INDISPONIBLE("INDISPO", "Non disponible en retour"),
    RENFORT("RENF", "Demande de renfort", demandeTexte = true, questionTexte = "Précision (facultatif)", demandeNombre = true),
    DANGER("DANG", "Danger / problème sur place", prioritaire = true, demandeTexte = true, questionTexte = "Quel danger ? (facultatif)"),
    PAUSE("PAUSE", "En pause"),
    PREMIERS_SECOURS("PS", "Demande de premiers secours", prioritaire = true, demandeTexte = true, texteObligatoire = true,
        questionTexte = "Pour quel motif demander des secours ?"),
    /** Un besoin relevé sur place (27/11/2026) : « EVAC·A·EQ 45.50000,4.60000 3 chevaux ». Le PC
     * en fait une demande, rapprochée de l'équipe la plus spécialisée. Voir [Classement.besoin]. */
    BESOIN("BES", "Besoin relevé sur le terrain", demandeTexte = true, texteObligatoire = true, questionTexte = "Quelques mots (facultatif)"),
}

/** Ce qui part au serveur (et, faute de réseau, sur le canal radio de l'équipe). */
@Serializable
data class MessageTerrainSortant(
    val type: String,
    val mission: String? = null,
    /** Le dossier (l'intervention) : les boutons sont dans sa fiche, à l'intérieur de la mission. */
    val dossier: String? = null,
    val equipe: String? = null,
    val texte: String = "",
    val nombre: Int? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
    @SerialName("emis_le") val emisLe: String,
    @SerialName("identifiant_client") val identifiant: String,
)

/**
 * L'étiquette radio, lisible par un humain sur n'importe quelle radio :
 * `⚑ARR 3f2a9c.9c1e0b.a1b2c3 Arrivé sur les lieux`. Les trois groupes sont le début des
 * identifiants de la mission (« ------ » sans mission), de l'intervenant, et du message.
 */
object EtiquetteTerrain {
    /** Au-delà, le texte est tronqué : une trame radio est petite (MeshCore surtout). */
    const val OCTETS_MAX = 140

    fun ecrire(type: TypeMessageTerrain, mission: String?, auteur: String, identifiant: String, texte: String = "", nombre: Int? = null,
               dossier: String? = null): String {
        val m6 = mission?.filter { it.isLetterOrDigit() }?.lowercase()?.take(6)?.padEnd(6, '0') ?: "------"
        val a6 = auteur.filter { it.isLetterOrDigit() }.lowercase().take(6).padEnd(6, '0')
        // Quatrième groupe, facultatif : le dossier.
        val d6 = dossier?.filter { it.isLetterOrDigit() }?.lowercase()?.take(6)?.let { ".$it" } ?: ""
        val entete = "⚑${type.code} $m6.$a6.$identifiant$d6"
        val corps = buildString {
            append(type.libelle)
            if (nombre != null) append(" ($nombre)")
            if (texte.isNotBlank()) append(" : ").append(texte.trim())
        }
        return tronquer("$entete $corps", OCTETS_MAX)
    }

    /** Coupe sans casser un caractère : la limite est en octets UTF-8. */
    fun tronquer(texte: String, octets: Int): String {
        if (texte.encodeToByteArray().size <= octets) return texte
        var fin = texte.length
        while (fin > 0 && texte.substring(0, fin).encodeToByteArray().size > octets - 3) fin--
        return texte.substring(0, fin) + "…"
    }

    /** Une étiquette reçue par radio, lue (23/11/2026) : de quoi notifier « Danger signalé par
     * Léa : mur fissuré » au lieu du code brut. Le texte peut être précédé de « Nom: » (MeshCore). */
    data class Lue(val type: TypeMessageTerrain, val corps: String)

    private val MOTIF = Regex("""⚑([A-Z]{2,7}) ([0-9a-f-]{6})\.([0-9a-f]{6})\.([0-9a-f]{6})(?:\.([0-9a-f]{6}))?(?: (.*))?$""",
                              RegexOption.DOT_MATCHES_ALL)

    fun lire(texte: String): Lue? {
        val debut = texte.indexOf('⚑').takeIf { it >= 0 } ?: return null
        val m = MOTIF.find(texte.substring(debut).trim()) ?: return null
        val type = TypeMessageTerrain.entries.firstOrNull { it.code == m.groupValues[1] } ?: return null
        val corps = m.groupValues[6].trim().removePrefix(type.libelle).trimStart(' ', ':').trim()
        return Lue(type, corps)
    }

    fun estTronque(type: TypeMessageTerrain, texte: String, nombre: Int?): Boolean =
        ecrire(type, "000000", "000000", "000000", texte, nombre).endsWith("…")
}
