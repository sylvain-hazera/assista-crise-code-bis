package fr.assistacrise.mobile

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Ce que le système sait du réseau : y en a-t-il un qui prétend mener à Internet ?
 *
 * On ne lui demande PAS s'il l'a « validé ». Cette validation est une sonde vers des serveurs
 * de Google : elle échoue derrière un réseau qui les filtre, sur le Wi-Fi d'un satellite
 * coupé d'Internet, et elle clignote à chaque changement d'antenne — autant de cas où notre
 * serveur, lui, répond très bien. Savoir si le serveur répond est le travail de
 * `IndicateurLien`, qui le lui demande directement.
 */
class ObservateurReseau(contexte: Context) {
    private val gestionnaire = contexte.getSystemService(ConnectivityManager::class.java)

    private val _present = MutableStateFlow(utilisable(gestionnaire.getNetworkCapabilities(gestionnaire.activeNetwork)))
    val present: StateFlow<Boolean> = _present

    init {
        gestionnaire.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
            override fun onCapabilitiesChanged(reseau: Network, capacites: NetworkCapabilities) {
                _present.value = utilisable(capacites)
            }
            override fun onLost(reseau: Network) {
                _present.value = false
            }
        })
    }

    private fun utilisable(capacites: NetworkCapabilities?): Boolean =
        capacites != null && capacites.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
}
