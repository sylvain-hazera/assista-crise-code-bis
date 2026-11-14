package fr.assistacrise.mobile

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** Ce que le système sait du réseau : une connexion à Internet, validée par lui, existe-t-elle ? */
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
        capacites != null &&
            capacites.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            capacites.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
}
