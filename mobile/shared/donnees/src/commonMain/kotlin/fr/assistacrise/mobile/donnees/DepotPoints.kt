package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.PointCrise
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * Les points importants des crises suivies (lieux d'accueil, PC, points de rassemblement…),
 * copiés sur le téléphone pour le GPS hors ligne (22/11/2026). Chiffrés comme le reste.
 */
class DepotPoints(private val api: ClientApi, private val magasin: Magasin) {
    private val json = Json { ignoreUnknownKeys = true }
    private val _points = MutableStateFlow<List<PointCrise>>(emptyList())
    val points: StateFlow<List<PointCrise>> = _points

    suspend fun restaurer() {
        _points.value = magasin.lire(FICHIER)?.let { runCatching { json.decodeFromString(FORME, it) }.getOrNull() } ?: emptyList()
    }

    /** Relit les points de ces crises. Hors réseau, la copie précédente reste. */
    suspend fun rafraichir(crises: List<String>): Reponse<Unit> {
        val tous = mutableListOf<PointCrise>()
        for (crise in crises.distinct()) {
            when (val r = api.liste("points-operationnels/?crise=$crise", PointCrise.serializer())) {
                is Reponse.Ok -> tous += r.valeur.map { it.copy(crise = it.crise ?: crise) }
                is Reponse.Refus -> Unit
                is Reponse.Injoignable -> return r
            }
        }
        _points.value = tous.filter { it.situe }
        magasin.ecrire(FICHIER, json.encodeToString(FORME, _points.value))
        return Reponse.Ok(Unit)
    }

    suspend fun toutEffacer() { _points.value = emptyList(); magasin.effacer(FICHIER) }

    private companion object {
        const val FICHIER = "points-crise"
        val FORME = ListSerializer(PointCrise.serializer())
    }
}
