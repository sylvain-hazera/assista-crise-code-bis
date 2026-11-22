package fr.assistacrise.mobile

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import fr.assistacrise.mobile.domaine.CartesEmbarquees
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.maplibre.android.MapLibre
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.offline.OfflineManager
import org.maplibre.android.offline.OfflineRegion
import org.maplibre.android.offline.OfflineRegionError
import org.maplibre.android.offline.OfflineRegionStatus
import org.maplibre.android.offline.OfflineTilePyramidRegionDefinition

/**
 * Les cartes embarquées (22/11/2026) : des régions hors ligne MapLibre sur le fond IGN, dont la
 * licence (Etalab 2.0) autorise la mise en cache (dossier § 8). Le style est un fichier de
 * l'application (`asset://style-ign.json`), le même que celui de la carte : les tuiles
 * téléchargées sont celles que la carte réclamera sans réseau.
 */
class CartesHorsLigne(private val contexte: Context) {
    data class Region(val id: Long, val nom: String, val tuiles: Long, val terminee: Boolean, val octets: Long)
    data class Telechargement(val nom: String, val faites: Long, val attendues: Long, val erreur: String? = null, val termine: Boolean = false)

    private val _regions = MutableStateFlow<List<Region>>(emptyList())
    val regions: StateFlow<List<Region>> = _regions
    private val _encours = MutableStateFlow<Telechargement?>(null)
    val encours: StateFlow<Telechargement?> = _encours

    private val gestionnaire by lazy {
        MapLibre.getInstance(contexte)
        OfflineManager.getInstance(contexte).also { it.setOfflineMapboxTileCountLimit(LIMITE_TUILES) }
    }

    fun estimation(bornes: LatLngBounds, zoomMax: Int): Pair<Long, Long> {
        val n = CartesEmbarquees.tuiles(bornes.latitudeSouth, bornes.longitudeWest, bornes.latitudeNorth, bornes.longitudeEast, ZOOM_MIN, zoomMax)
        return n to n * CartesEmbarquees.OCTETS_PAR_TUILE
    }

    /** Le téléphone est-il sur un réseau non facturé au volume (Wi-Fi) ? */
    fun surWifi(): Boolean {
        val cm = contexte.getSystemService(ConnectivityManager::class.java) ?: return false
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
    }

    fun relire() {
        gestionnaire.listOfflineRegions(object : OfflineManager.ListOfflineRegionsCallback {
            override fun onList(offlineRegions: Array<OfflineRegion>?) {
                val liste = mutableListOf<Region>()
                val toutes = offlineRegions.orEmpty()
                if (toutes.isEmpty()) { _regions.value = emptyList(); return }
                toutes.forEach { r ->
                    r.getStatus(object : OfflineRegion.OfflineRegionStatusCallback {
                        override fun onStatus(status: OfflineRegionStatus?) {
                            liste += Region(r.id, String(r.metadata), status?.requiredResourceCount ?: 0,
                                status?.isComplete == true, status?.completedResourceSize ?: 0)
                            if (liste.size == toutes.size) _regions.value = liste.sortedBy { it.nom }
                        }
                        override fun onError(error: String?) = Unit
                    })
                }
            }
            override fun onError(error: String) = Unit
        })
    }

    fun telecharger(nom: String, bornes: LatLngBounds, zoomMax: Int) {
        val definition = OfflineTilePyramidRegionDefinition(STYLE, bornes, ZOOM_MIN.toDouble(), zoomMax.toDouble(),
            contexte.resources.displayMetrics.density)
        _encours.value = Telechargement(nom, 0, estimation(bornes, zoomMax).first)
        gestionnaire.createOfflineRegion(definition, nom.toByteArray(), object : OfflineManager.CreateOfflineRegionCallback {
            override fun onCreate(offlineRegion: OfflineRegion) {
                offlineRegion.setObserver(object : OfflineRegion.OfflineRegionObserver {
                    override fun onStatusChanged(status: OfflineRegionStatus) {
                        _encours.value = Telechargement(nom, status.completedResourceCount, status.requiredResourceCount,
                            termine = status.isComplete)
                        if (status.isComplete) { offlineRegion.setDownloadState(OfflineRegion.STATE_INACTIVE); relire() }
                    }
                    override fun onError(error: OfflineRegionError) {
                        _encours.value = _encours.value?.copy(erreur = "${error.reason} ${error.message}")
                    }
                    override fun mapboxTileCountLimitExceeded(limit: Long) {
                        _encours.value = _encours.value?.copy(erreur = "Région trop grande : $limit tuiles au plus. Choisissez une zone plus petite.")
                        offlineRegion.setDownloadState(OfflineRegion.STATE_INACTIVE)
                    }
                })
                offlineRegion.setDownloadState(OfflineRegion.STATE_ACTIVE)
            }
            override fun onError(error: String) { _encours.value = _encours.value?.copy(erreur = error) }
        })
    }

    fun supprimer(id: Long) {
        gestionnaire.listOfflineRegions(object : OfflineManager.ListOfflineRegionsCallback {
            override fun onList(offlineRegions: Array<OfflineRegion>?) {
                offlineRegions?.firstOrNull { it.id == id }?.delete(object : OfflineRegion.OfflineRegionDeleteCallback {
                    override fun onDelete() = relire()
                    override fun onError(error: String) = Unit
                })
            }
            override fun onError(error: String) = Unit
        })
    }

    fun oublierLeTelechargement() { _encours.value = null }

    companion object {
        const val STYLE = "asset://style-ign.json"
        const val ZOOM_MIN = 6
        const val LIMITE_TUILES = 150_000L
    }
}
