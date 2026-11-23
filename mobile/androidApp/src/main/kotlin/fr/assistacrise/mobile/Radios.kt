package fr.assistacrise.mobile

import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.os.ParcelUuid
import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.donnees.EmetteurRadio
import fr.assistacrise.mobile.lien.CanalRadio
import fr.assistacrise.mobile.lien.Protocole
import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.Meshtastic
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * Les radios du téléphone (23/11/2026) : une Meshtastic et une MeshCore, en même temps si
 * l'intervenant a les deux. « Peux-tu prévoir que je peux avoir un nœud MeshCore et un
 * Meshtastic en même temps sur le même téléphone ? »
 *
 * Chaque protocole a sa liaison (`LiaisonRadio`), retenue et reconnectée seule. Ici : la
 * recherche Bluetooth (commune), l'aiguillage vers la bonne liaison, et l'émission vers une
 * équipe — sur **chaque** radio qui porte le canal de l'équipe, pour que les deux réseaux
 * l'entendent. Le serveur apprend ensuite par quels réseaux le message est déjà parti
 * (`deja_emis_radio`), et les ponts ne le répètent sur aucun d'eux.
 *
 * Aucun canal n'est jamais créé ici : on n'emploie que le canal de l'équipe, tel que la
 * plateforme l'installe, retrouvé par son nom. Absent de la radio, le message attend le réseau.
 */
@SuppressLint("MissingPermission")   // `LiaisonRadio.autorise` vérifiée avant chaque recherche
class Radios(private val app: Application) : EmetteurRadio {
    val meshtastic = LiaisonRadio(app, Protocole.MESHTASTIC)
    val meshcore = LiaisonRadio(app, Protocole.MESHCORE)
    val toutes: List<LiaisonRadio> get() = listOf(meshtastic, meshcore)

    fun pour(protocole: Protocole): LiaisonRadio = if (protocole == Protocole.MESHCORE) meshcore else meshtastic

    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    /** L'état des deux liaisons, Meshtastic d'abord. */
    val etats: StateFlow<List<LiaisonRadio.Etat>> = combine(meshtastic.etat, meshcore.etat) { a, b -> listOf(a, b) }
        .stateIn(portee, SharingStarted.Eagerly, listOf(meshtastic.etat.value, meshcore.etat.value))

    /** Les liaisons prêtes à émettre. */
    fun pretes(): List<LiaisonRadio> = toutes.filter { it.etat.value.phase == LiaisonRadio.Phase.PRETE }

    // --- Recherche (commune aux deux protocoles) -----------------------------------------

    private val _trouvees = MutableStateFlow<List<LiaisonRadio.RadioTrouvee>>(emptyList())
    val trouvees: StateFlow<List<LiaisonRadio.RadioTrouvee>> = _trouvees
    private val _recherche = MutableStateFlow(false)
    val recherche: StateFlow<Boolean> = _recherche
    private val _erreurRecherche = MutableStateFlow<String?>(null)
    val erreurRecherche: StateFlow<String?> = _erreurRecherche
    private val adaptateur get() = app.getSystemService(BluetoothManager::class.java)?.adapter

    private val ecouteRecherche = object : ScanCallback() {
        override fun onScanResult(type: Int, resultat: ScanResult) {
            val services = resultat.scanRecord?.serviceUuids?.map { it.uuid.toString().lowercase() } ?: return
            val protocole = when {
                MeshCore.SERVICE in services -> Protocole.MESHCORE
                Meshtastic.SERVICE in services -> Protocole.MESHTASTIC
                else -> return
            }
            val radio = LiaisonRadio.RadioTrouvee(resultat.device.address, resultat.device.name ?: resultat.scanRecord?.deviceName ?: "Radio sans nom", protocole)
            if (_trouvees.value.none { it.adresse == radio.adresse }) _trouvees.value = _trouvees.value + radio
        }
    }

    fun chercher() {
        val scanner = adaptateur?.takeIf { it.isEnabled && LiaisonRadio.autorise(app) }?.bluetoothLeScanner
        if (scanner == null) {
            _erreurRecherche.value = "Le Bluetooth est éteint ou indisponible sur ce téléphone."
            return
        }
        _erreurRecherche.value = null
        _trouvees.value = emptyList()
        _recherche.value = true
        val filtres = listOf(MeshCore.SERVICE, Meshtastic.SERVICE).map {
            ScanFilter.Builder().setServiceUuid(ParcelUuid(UUID.fromString(it))).build()
        }
        scanner.startScan(filtres, ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), ecouteRecherche)
        // Une recherche qu'on oublie d'arrêter vide la batterie.
        portee.launch { delay(30_000); arreterLaRecherche() }
    }

    fun arreterLaRecherche() {
        runCatching { adaptateur?.bluetoothLeScanner?.stopScan(ecouteRecherche) }
        _recherche.value = false
    }

    // --- Connexion -----------------------------------------------------------------------

    /** Connecte la radio sur l'emplacement de son protocole ; l'autre radio, s'il y en a une, reste. */
    fun connecter(radio: LiaisonRadio.RadioTrouvee) {
        arreterLaRecherche()
        pour(radio.protocole).connecter(radio)
    }

    fun connecterParLeReseau(protocole: Protocole, adresse: String): String? = pour(protocole).connecterParLeReseau(protocole, adresse)

    fun deconnecter(protocole: Protocole) = pour(protocole).deconnecter()
    fun toutDeconnecter() = toutes.forEach { it.deconnecter() }

    /** Une radio au moins est-elle choisie ? Le service de terrain reste alors en vie. */
    fun choisie(): Boolean = toutes.any { it.choisie() }

    suspend fun reprendre() = toutes.forEach { it.reprendre() }
    suspend fun reprendreSiChoisie() = toutes.forEach { it.reprendreSiChoisie() }

    /** Le lien radio de l'application : vrai tant qu'une radio au moins est prête. */
    fun lienChange() = app.lien.radio(pretes().isNotEmpty())

    // --- Émission ------------------------------------------------------------------------

    /** Sur chaque radio prête qui porte le canal de l'équipe. Rend « MESHTASTIC,MESHCORE », l'un des deux, ou null. */
    override suspend fun envoyerAEquipe(equipe: Equipe, texte: String): String? =
        pretes().mapNotNull { it.envoyerAEquipe(equipe, texte) }.joinToString(",").ifEmpty { null }

    /** Le canal de cette équipe, radio par radio. */
    fun canauxPour(equipe: Equipe): List<Pair<Protocole, CanalRadio>> =
        toutes.mapNotNull { l -> l.canalPour(equipe)?.let { l.emplacement to it } }

    /**
     * En formation, la règle du serveur pour la démo (`_contenu_message_mesh_demo`) : la radio
     * est réelle et ses voisins aussi, donc le message est préfixé « [démo] » et gardé court.
     */
    fun texteSelonLaZone(texte: String): String {
        if (!app.session.enFormation) return texte
        val propre = texte.trim()
        val prefixe = if (propre.lowercase().startsWith("[démo]")) "" else "[démo] "
        val disponible = 100 - prefixe.length
        return prefixe + if (propre.length > disponible) propre.take(disponible - 1).trimEnd() + "…" else propre
    }

    /**
     * L'équipe dont ce canal est le canal radio, géré par la plateforme : le menu radio avancé
     * le signale, et demande une confirmation renforcée avant d'y toucher (23/11/2026 : « il
     * faut s'aligner sur les canaux, vu qu'on en a peu, pour éviter la perte de données »).
     */
    fun equipeDuCanal(protocole: Protocole, index: Int): Equipe? {
        val l = pour(protocole)
        return app.equipes.equipes.value.firstOrNull { l.canalPour(it)?.index == index }
    }
}
