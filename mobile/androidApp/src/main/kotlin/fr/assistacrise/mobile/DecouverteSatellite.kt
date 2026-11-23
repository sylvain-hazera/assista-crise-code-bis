package fr.assistacrise.mobile

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.ConcurrentLinkedQueue

/**
 * Cherche les satellites annoncés en mDNS sur le Wi-Fi du site (23/11/2026) : le service
 * `_ac-local._tcp` que publie `satellite/annoncer_backend_local.py`, avec dans ses propriétés
 * le port du site (`web_port`). Rend des adresses `http://<ip>:<port>/` et le nom du satellite.
 *
 * Quelques secondes d'écoute, pas plus : c'est appelé quand le central ne répond plus, et la
 * personne attend. **Pas essayé sur un vrai satellite au moment de l'écrire** (émulateur sans
 * mDNS) : la logique de bascule qui s'en sert est testée à part (BasculeServeurTest).
 */
class DecouverteSatellite(private val contexte: Context) {

    suspend fun decouvrir(dureeMs: Long = 4_000): List<Pair<String, String>> {
        val nsd = contexte.getSystemService(NsdManager::class.java) ?: return emptyList()
        val trouves = ConcurrentLinkedQueue<NsdServiceInfo>()
        val ecoute = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(type: String) = Unit
            override fun onDiscoveryStopped(type: String) = Unit
            override fun onStartDiscoveryFailed(type: String, code: Int) = Unit
            override fun onStopDiscoveryFailed(type: String, code: Int) = Unit
            override fun onServiceFound(info: NsdServiceInfo) { trouves += info }
            override fun onServiceLost(info: NsdServiceInfo) = Unit
        }
        runCatching { nsd.discoverServices(TYPE, NsdManager.PROTOCOL_DNS_SD, ecoute) }.onFailure { return emptyList() }
        delay(dureeMs)
        runCatching { nsd.stopServiceDiscovery(ecoute) }
        val resultats = mutableListOf<Pair<String, String>>()
        for (info in trouves.distinctBy { it.serviceName }) {
            val resolu = resoudre(nsd, info) ?: continue
            @Suppress("DEPRECATION")
            val hote = resolu.host?.hostAddress ?: continue
            val port = resolu.attributes["web_port"]?.decodeToString()?.toIntOrNull() ?: 80
            resultats += "http://$hote${if (port == 80) "" else ":$port"}/" to resolu.serviceName
        }
        return resultats
    }

    @Suppress("DEPRECATION")   // resolveService suffit ici : un satellite, une adresse
    private suspend fun resoudre(nsd: NsdManager, info: NsdServiceInfo): NsdServiceInfo? {
        val fin = CompletableDeferred<NsdServiceInfo?>()
        runCatching {
            nsd.resolveService(info, object : NsdManager.ResolveListener {
                override fun onResolveFailed(i: NsdServiceInfo, code: Int) { fin.complete(null) }
                override fun onServiceResolved(i: NsdServiceInfo) { fin.complete(i) }
            })
        }.onFailure { return null }
        return withTimeoutOrNull(3_000) { fin.await() }
    }

    companion object {
        const val TYPE = "_ac-local._tcp."
    }
}
