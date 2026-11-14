package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Miroir de `Mission.Statut` (backend/core/models.py). L'ordre est celui du cycle de vie. */
@Serializable
enum class StatutMission(val libelle: String) {
    EN_PREPARATION("En préparation"),
    EN_COURS("En cours"),
    TERMINEE("Terminée");

    /** Une mission avance ou recule d'un cran : on ne « termine » pas ce qui n'a pas commencé. */
    fun voisins(): List<StatutMission> = when (this) {
        EN_PREPARATION -> listOf(EN_COURS)
        EN_COURS -> listOf(TERMINEE, EN_PREPARATION)
        TERMINEE -> listOf(EN_COURS)
    }
}

@Serializable
data class Mission(
    val id: String,
    val titre: String = "",
    val description: String = "",
    @SerialName("crise_nom") val criseNom: String? = null,
    @SerialName("equipes_noms") val equipesNoms: List<String> = emptyList(),
    @SerialName("equipe_ids") val equipes: List<String> = emptyList(),
    val statut: StatutMission = StatutMission.EN_PREPARATION,
    @SerialName("date_creation") val dateCreation: String? = null,
)

/**
 * Une mission telle qu'on l'affiche : ce que le serveur a dit, corrigé de ce que le téléphone
 * a déclaré et qui n'est pas encore accusé. `nonConfirme` est affiché tel quel — un
 * intervenant qui croit avoir transmis est plus dangereux qu'un intervenant qui sait que non.
 */
data class MissionAffichee(val mission: Mission, val nonConfirme: Boolean)
