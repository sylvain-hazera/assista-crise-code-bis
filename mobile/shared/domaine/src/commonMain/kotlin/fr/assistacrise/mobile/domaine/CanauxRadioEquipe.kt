package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Les canaux radio d'une de mes équipes (25/11/2026, `teams/mes-canaux-radio/`), AVEC leurs clés :
 * l'application les installe sur la radio du téléphone. Par défaut « AC-<INDICATIF> » ; une
 * structure peut avoir mis son propre canal (nom et clé).
 */
@Serializable
data class CanauxRadioEquipe(
    val equipe: String,
    @SerialName("nom_equipe") val nomEquipe: String = "",
    val indicatif: String = "",
    val meshtastic: CanalEquipeMeshtastic? = null,
    val meshcore: CanalEquipeMeshCore? = null,
)

@Serializable
data class CanalEquipeMeshtastic(val nom: String, @SerialName("psk_hex") val pskHex: String = "", val version: String = "")

@Serializable
data class CanalEquipeMeshCore(val nom: String, @SerialName("cle_hex") val cleHex: String = "", val version: String = "")

/** Un canal d'équipe à mettre sur la radio, quel que soit le protocole. */
data class CanalAInstaller(val nom: String, val cleHex: String, val version: String)

/**
 * Ce que l'application doit faire sur la radio pour ses canaux d'équipe. Règles :
 * - un canal absent est ajouté (dans un emplacement libre, choisi par l'appelant) ;
 * - un canal déjà présent sous le même nom n'est jamais touché, SAUF s'il a été installé par
 *   l'application et que sa version a changé (clé régénérée) : il est réécrit sur place ;
 * - un canal installé par l'application qui n'est plus celui d'une de mes équipes est retiré ;
 *   un canal que la personne avait mis elle-même ne l'est jamais.
 * `installes` : nom normalisé → version, ce que l'application a elle-même installé.
 */
object PlanCanauxEquipes {
    sealed class Action {
        data class Ajouter(val canal: CanalAInstaller) : Action()
        data class Reecrire(val index: Int, val canal: CanalAInstaller) : Action()
        data class Retirer(val index: Int, val nom: String) : Action()
    }

    fun normaliser(nom: String) = PlanRadio.normaliser(nom)

    fun pour(protocoleMeshCore: Boolean, equipes: List<CanauxRadioEquipe>): List<CanalAInstaller> =
        equipes.mapNotNull { e ->
            if (protocoleMeshCore) e.meshcore?.let { CanalAInstaller(it.nom, it.cleHex, it.version) }
            else e.meshtastic?.let { CanalAInstaller(it.nom, it.pskHex, it.version) }
        }.distinctBy { normaliser(it.nom) }

    /** `presents` : nom normalisé → emplacement, les canaux actuellement sur la radio. */
    fun actions(canaux: List<CanalAInstaller>, presents: Map<String, Int>, installes: Map<String, String>): List<Action> {
        val voulus = canaux.associateBy { normaliser(it.nom) }
        val sortie = mutableListOf<Action>()
        for ((nom, canal) in voulus) {
            val index = presents[nom]
            when {
                index == null -> sortie += Action.Ajouter(canal)
                installes[nom] != null && installes[nom] != canal.version -> sortie += Action.Reecrire(index, canal)
            }
        }
        for (nom in installes.keys) {
            if (nom !in voulus) presents[nom]?.let { sortie += Action.Retirer(it, nom) }
        }
        return sortie
    }
}
