package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Mission
import fr.assistacrise.mobile.domaine.StatutMission
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * Les missions, telles que le serveur les a données la dernière fois, gardées sur le
 * téléphone pour être lisibles sans réseau. Les changements déclarés ne modifient pas cette
 * copie : ils vont dans la file, et l'affichage superpose les deux (`superposerLaFile`).
 */
class DepotMissions(
    private val api: ClientApi,
    private val magasin: Magasin,
    private val file: FileAttente,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    private val _missions = MutableStateFlow<List<Mission>>(emptyList())
    val missions: StateFlow<List<Mission>> = _missions

    suspend fun restaurer() {
        val texte = magasin.lire(FICHIER) ?: return
        _missions.value = runCatching {
            json.decodeFromString(ListSerializer(Mission.serializer()), texte)
        }.getOrDefault(emptyList())
    }

    suspend fun rafraichir(): Reponse<Unit> = when (val r = api.missions()) {
        is Reponse.Ok -> {
            // Une mission terminée ne reste pas sur le téléphone (23/11/2026 : « quand la mission
            // est terminée et transférée, ça s'efface ») -- sauf tant qu'une action la concernant
            // attend d'être envoyée. Le serveur, lui, garde tout.
            val enAttente = file.actions.value.map { it.cible }.toSet()
            val gardees = r.valeur.filter { it.statut != StatutMission.TERMINEE || it.id in enAttente }
            magasin.ecrire(FICHIER, json.encodeToString(ListSerializer(Mission.serializer()), gardees))
            _missions.value = gardees
            Reponse.Ok(Unit)
        }
        is Reponse.Refus -> r
        is Reponse.Injoignable -> r
    }

    /** Déclare un changement de statut : en file d'abord, envoi ensuite. Jamais l'inverse. */
    suspend fun declarerStatut(mission: Mission, statut: StatutMission) {
        file.ajouter(
            genre = ActionEnAttente.GENRE_STATUT_MISSION,
            cible = mission.id,
            charge = statut.name,
            libelle = "« ${mission.titre} » : ${statut.libelle}",
        )
    }

    suspend fun toutEffacer() {
        magasin.effacer(FICHIER)
        _missions.value = emptyList()
    }

    private companion object { const val FICHIER = "missions" }
}
