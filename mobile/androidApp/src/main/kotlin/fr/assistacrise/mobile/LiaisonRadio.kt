package fr.assistacrise.mobile

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Alerte
import fr.assistacrise.mobile.domaine.PlanRadio
import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.lien.AdresseReseau
import fr.assistacrise.mobile.lien.CadrageFlux
import fr.assistacrise.mobile.lien.CanalRadio
import fr.assistacrise.mobile.lien.PiloteMeshCore
import fr.assistacrise.mobile.lien.PiloteMeshtastic
import fr.assistacrise.mobile.lien.PiloteRadio
import fr.assistacrise.mobile.lien.Protocole
import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.Meshtastic
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.net.InetSocketAddress
import java.net.Socket
import java.util.UUID
import kotlin.random.Random

/**
 * La liaison Bluetooth avec la radio de l'intervenant (dossier § 4 et § 7).
 *
 * Elle ne connaît des deux protocoles que leurs identifiants Bluetooth : tout le dialogue
 * est dans les pilotes (`PiloteRadio`), qui sont testés sans radio. Ici, on transporte des
 * octets — et on fait ce que le Bluetooth d'Android exige : une seule opération à la fois,
 * chacune attendue avant la suivante.
 *
 * Elle sait aussi joindre la radio par le réseau (TCP/IP, 20/11/2026) : un nœud relié au Wi-Fi
 * ouvre un port où passent les mêmes trames, cadrées pour un flux (`CadrageFlux`, partagé avec
 * iOS). Mêmes pilotes, même reprise après coupure ; seule l'adresse doit être locale, le lien
 * n'étant pas chiffré.
 *
 * Une liaison par protocole (23/11/2026) : un téléphone peut tenir en même temps une radio
 * Meshtastic et une radio MeshCore ; `Radios` les coordonne.
 *
 * **Cette classe n'a pas pu être essayée** : l'émulateur n'a pas de Bluetooth, et il n'y
 * avait pas de radio. Elle est écrite d'après les clients de référence et le code des
 * firmwares ; le premier essai sur du matériel dira ce qui reste à corriger.
 */
@SuppressLint("MissingPermission")   // chaque entrée publique vérifie `autorise` d'abord
class LiaisonRadio(private val app: Application, val emplacement: Protocole) {

    enum class Phase { ABSENTE, RECHERCHE, CONNEXION, PRETE }

    data class Etat(
        val phase: Phase = Phase.ABSENTE,
        val nom: String? = null,
        val protocole: Protocole? = null,
        val canaux: List<CanalRadio> = emptyList(),
        val erreur: String? = null,
        /** Jointe par le réseau (TCP/IP) plutôt que par le Bluetooth. */
        val reseau: Boolean = false,
    )

    /** `adresse` : celle du Bluetooth, ou « hôte:port » pour une radio jointe par le réseau. */
    data class RadioTrouvee(val adresse: String, val nom: String, val protocole: Protocole, val reseau: Boolean = false)

    private val _etat = MutableStateFlow(Etat())
    val etat: StateFlow<Etat> = _etat

    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val adaptateur get() = app.getSystemService(BluetoothManager::class.java)?.adapter

    private var gatt: BluetoothGatt? = null
    /** La prise TCP d'une radio jointe par le réseau, et son cadrage. */
    @Volatile private var prise: Socket? = null
    private var cadrage: CadrageFlux? = null
    private var pilote: PiloteRadio? = null
    private var session: Job? = null
    private var operations = Channel<suspend () -> Unit>(Channel.UNLIMITED)

    /** Ce que l'opération en cours attend du Bluetooth : une seule à la fois. */
    @Volatile private var attente: CompletableDeferred<ByteArray?>? = null

    /** La radio que la personne a choisie : on y revient seul après une coupure. */
    private var voulue: RadioTrouvee? = null
    private var reconnexion: Job? = null

    // --- Connexion -----------------------------------------------------------------------

    fun connecter(radio: RadioTrouvee) {
        require(radio.protocole == emplacement)
        voulue = radio
        val genre = if (radio.reseau) RESEAU else BLUETOOTH
        portee.launch { app.magasin.ecrire(FICHIER, "${radio.adresse}|${radio.protocole.name}|$genre|${radio.nom}") }
        ouvrir(radio)
        // La liaison est tenue par le service de terrain : elle survit à l'écran éteint.
        ServiceTerrain.actualiser(app)
    }

    /** Une radio jointe par le réseau : l'adresse est vérifiée (locale seulement) avant tout. */
    fun connecterParLeReseau(protocole: Protocole, adresse: String): String? {
        val lecture = AdresseReseau.lire(adresse, CadrageFlux.pour(protocole).portParDefaut)
        if (lecture is AdresseReseau.Companion.Lecture.Refusee) return lecture.motif
        val valide = (lecture as AdresseReseau.Companion.Lecture.Valide).adresse
        connecter(RadioTrouvee(valide.toString(), valide.toString(), protocole, reseau = true))
        return null
    }

    /** Une radio est-elle choisie ? Le service de terrain reste alors en vie pour elle. */
    fun choisie(): Boolean = voulue != null

    /** Au redémarrage du téléphone : relit seulement la radio choisie, sans ouvrir la liaison
     * (le service de terrain s'en charge une fois démarré). */
    suspend fun reprendreSiChoisie() {
        if (voulue != null) return
        val parties = lireChoix() ?: return
        val protocole = Protocole.entries.firstOrNull { it.name == parties.getOrNull(1) } ?: return
        val reseau = parties.getOrNull(2) == RESEAU
        val nom = if (parties.getOrNull(2) in setOf(RESEAU, BLUETOOTH)) parties.getOrElse(3) { "Radio" }
                  else parties.drop(2).joinToString("|").ifEmpty { "Radio" }
        voulue = RadioTrouvee(parties[0], nom, protocole, reseau)
    }

    /** Au démarrage : retrouve la radio choisie la dernière fois. */
    suspend fun reprendre() {
        voulue?.let { radio -> if (gatt == null && prise == null && _etat.value.phase == Phase.ABSENTE) ouvrir(radio); return }
        if (voulue != null) return
        val parties = lireChoix() ?: return
        val protocole = Protocole.entries.firstOrNull { it.name == parties.getOrNull(1) } ?: return
        // Ancien format « adresse|protocole|nom » : une radio Bluetooth.
        val reseau = parties.getOrNull(2) == RESEAU
        val nom = if (parties.getOrNull(2) in setOf(RESEAU, BLUETOOTH)) parties.getOrElse(3) { "Radio" }
                  else parties.drop(2).joinToString("|").ifEmpty { "Radio" }
        if (!reseau && !autorise(app)) return
        voulue = RadioTrouvee(parties[0], nom, protocole, reseau)
        ouvrir(voulue!!)
    }

    fun deconnecter() {
        voulue = null
        reconnexion?.cancel(); reconnexion = null
        portee.launch { app.magasin.effacer(FICHIER) }
        fermer(null)
        ServiceTerrain.actualiser(app)
    }

    /** Ancien fichier unique (avant le 23/11/2026) : l'emplacement de son protocole le reprend. */
    private suspend fun lireChoix(): List<String>? {
        app.magasin.lire(FICHIER)?.let { return it.split("|", limit = 4) }
        val ancien = app.magasin.lire(ANCIEN_FICHIER)?.split("|", limit = 4) ?: return null
        if (ancien.getOrNull(1) != emplacement.name) return null
        app.magasin.ecrire(FICHIER, ancien.joinToString("|"))
        app.magasin.effacer(ANCIEN_FICHIER)
        return ancien
    }

    private fun ouvrir(radio: RadioTrouvee) {
        if (radio.reseau) { ouvrirParLeReseau(radio); return }
        val appareil = runCatching { adaptateur?.takeIf { it.isEnabled }?.getRemoteDevice(radio.adresse) }.getOrNull()
        if (appareil == null || !autorise(app)) {
            _etat.value = Etat(erreur = "Le Bluetooth est éteint ou indisponible sur ce téléphone.")
            return
        }
        fermer(null, garderVoulue = true)
        pilote = when (radio.protocole) {
            Protocole.MESHCORE -> PiloteMeshCore { System.currentTimeMillis() }
            Protocole.MESHTASTIC -> PiloteMeshtastic { Random.nextLong(1, 0xffffffffL) }
        }
        operations = Channel(Channel.UNLIMITED)
        val file = operations
        session = portee.launch { for (operation in file) runCatching { operation() } }
        _etat.value = Etat(phase = Phase.CONNEXION, nom = radio.nom, protocole = radio.protocole)
        gatt = appareil.connectGatt(app, false, ecouteGatt, BluetoothDevice.TRANSPORT_LE)
    }

    private fun fermer(erreur: String?, garderVoulue: Boolean = false) {
        session?.cancel(); session = null
        operations.close()
        attente?.complete(null); attente = null
        runCatching { gatt?.disconnect(); gatt?.close() }
        gatt = null
        val ancienne = prise
        prise = null; cadrage = null
        runCatching { ancienne?.close() }
        pilote = null
        _etat.value = Etat(erreur = erreur)
        app.radio.lienChange()
        // La radio s'est éloignée ou éteinte : on y revient, sans relâche mais sans vider la
        // batterie — 10 s, 20 s, 40 s… jusqu'à 5 min entre deux essais (22/11/2026 : « ça ne
        // doit pas s'interrompre », y compris application fermée).
        // Une seule boucle à la fois : un essai qui échoue repasse ici, et ne doit pas
        // relancer le compte à rebours au début.
        if (!garderVoulue && erreur != null && reconnexion?.isActive != true) voulue?.let { radio ->
            reconnexion = portee.launch {
                var attenteMs = 10_000L
                while (voulue == radio && gatt == null && prise == null) {
                    delay(attenteMs)
                    if (voulue != radio || gatt != null || prise != null) break
                    ouvrir(radio)
                    delay(30_000)   // le temps de se connecter, ou d'échouer
                    if (_etat.value.phase == Phase.PRETE) break
                    attenteMs = (attenteMs * 2).coerceAtMost(300_000L)
                }
            }
        }
    }

    private val ecouteGatt = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, statut: Int, etat: Int) {
            if (g != gatt) return
            if (etat == BluetoothProfile.STATE_CONNECTED) {
                // MeshCore exige des trames de 155 octets au moins ; on demande large.
                if (!g.requestMtu(247)) g.discoverServices()
            } else if (etat == BluetoothProfile.STATE_DISCONNECTED) {
                fermer("La radio n'est plus à portée. Nouvelle tentative dans quelques instants.")
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, statut: Int) { if (g == gatt) g.discoverServices() }

        override fun onServicesDiscovered(g: BluetoothGatt, statut: Int) {
            if (g == gatt) operations.trySend { preparer(g) }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, statut: Int) {
            attente?.complete(if (statut == BluetoothGatt.GATT_SUCCESS) ByteArray(0) else null)
        }

        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, statut: Int) {
            attente?.complete(if (statut == BluetoothGatt.GATT_SUCCESS) ByteArray(0) else null)
        }

        // Android 13 et plus : la valeur arrive en paramètre.
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, valeur: ByteArray, statut: Int) {
            attente?.complete(if (statut == BluetoothGatt.GATT_SUCCESS) valeur else null)
        }

        @Deprecated("Deprecated in Java")
        @Suppress("DEPRECATION")
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, statut: Int) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                attente?.complete(if (statut == BluetoothGatt.GATT_SUCCESS) c.value ?: ByteArray(0) else null)
            }
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, valeur: ByteArray) = notifie(c, valeur)

        @Deprecated("Deprecated in Java")
        @Suppress("DEPRECATION")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) notifie(c, c.value ?: ByteArray(0))
        }
    }

    private fun notifie(c: BluetoothGattCharacteristic, valeur: ByteArray) {
        when (c.uuid.toString().lowercase()) {
            // MeshCore : la notification EST la trame.
            MeshCore.TX -> operations.trySend { traiter(valeur) }
            // Meshtastic : elle dit seulement « il y a quelque chose à lire ».
            Meshtastic.FROM_NUM -> operations.trySend { lireToutMeshtastic() }
        }
    }

    /** Après la découverte des services : appairage, notifications, présentation. */
    private suspend fun preparer(g: BluetoothGatt) {
        val p = pilote ?: return
        // Le lien transporte du clair et des clés : pas de dialogue sans appairage chiffré.
        if (g.device.bondState != BluetoothDevice.BOND_BONDED) {
            g.device.createBond()
            val appairee = withTimeoutOrNull(60_000) { while (g.device.bondState != BluetoothDevice.BOND_BONDED) delay(500); true }
            if (appairee == null) { fermer("L'appairage avec la radio n'a pas abouti. Vérifiez le code affiché sur la radio."); return }
        }
        val (service, aNotifier) = when (p.protocole) {
            Protocole.MESHCORE -> MeshCore.SERVICE to MeshCore.TX
            Protocole.MESHTASTIC -> Meshtastic.SERVICE to Meshtastic.FROM_NUM
        }
        val notification = g.getService(UUID.fromString(service))?.getCharacteristic(UUID.fromString(aNotifier))
        if (notification == null) { fermer("Cette radio ne propose pas le service attendu. Son firmware est peut-être trop ancien."); return }
        g.setCharacteristicNotification(notification, true)
        notification.getDescriptor(UUID.fromString(CCCD))?.let { descripteur ->
            operation {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    g.writeDescriptor(descripteur, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE) == android.bluetooth.BluetoothStatusCodes.SUCCESS
                } else {
                    @Suppress("DEPRECATION")
                    run { descripteur.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE; g.writeDescriptor(descripteur) }
                }
            }
        }
        p.ouverture(System.currentTimeMillis() / 1000).forEach { ecrire(it) }
        battre(p)
    }

    private fun battre(p: PiloteRadio) {
        if (p.periodeBattementMs <= 0) return
        val file = operations
        portee.launch {
            while (pilote === p) { delay(p.periodeBattementMs); p.battement()?.let { b -> file.trySend { ecrire(b) } } }
        }
    }

    // --- Par le réseau (TCP/IP) ------------------------------------------------------------

    private fun ouvrirParLeReseau(radio: RadioTrouvee) {
        val c = CadrageFlux.pour(radio.protocole)
        val adresse = (AdresseReseau.lire(radio.adresse, c.portParDefaut) as? AdresseReseau.Companion.Lecture.Valide)?.adresse
        if (adresse == null) { _etat.value = Etat(erreur = "Adresse de radio refusée : ${radio.adresse}."); return }
        fermer(null, garderVoulue = true)
        val p = when (radio.protocole) {
            Protocole.MESHCORE -> PiloteMeshCore { System.currentTimeMillis() }
            Protocole.MESHTASTIC -> PiloteMeshtastic { Random.nextLong(1, 0xffffffffL) }
        }
        pilote = p
        cadrage = c
        operations = Channel(Channel.UNLIMITED)
        val file = operations
        session = portee.launch { for (operation in file) runCatching { operation() } }
        _etat.value = Etat(phase = Phase.CONNEXION, nom = radio.nom, protocole = radio.protocole, reseau = true)
        portee.launch(Dispatchers.IO) {
            val s = Socket()
            try {
                s.connect(InetSocketAddress(adresse.hote, adresse.port), 8_000)
                s.tcpNoDelay = true
                s.keepAlive = true
            } catch (e: Exception) {
                runCatching { s.close() }
                if (pilote === p) fermer("La radio ne répond pas à $adresse. Vérifiez qu'elle et le téléphone sont sur le même Wi-Fi.")
                return@launch
            }
            if (pilote !== p) { runCatching { s.close() }; return@launch }
            prise = s
            file.trySend {
                ecrireBrut(c.reveil())
                if (c.reveil().isNotEmpty()) delay(100)
                p.ouverture(System.currentTimeMillis() / 1000).forEach { ecrire(it) }
                battre(p)
            }
            // La radio pousse ses trames d'elle-même : on lit le flux jusqu'à sa fermeture.
            val decoupeur = c.decoupeur()
            val tampon = ByteArray(1024)
            try {
                val entree = s.getInputStream()
                while (true) {
                    val lus = entree.read(tampon)
                    if (lus < 0) break
                    decoupeur.pousser(tampon, lus).forEach { trame -> file.trySend { traiter(trame) } }
                }
            } catch (_: Exception) { /* prise fermée ou réseau perdu */ }
            if (prise === s) fermer("La liaison réseau avec la radio est coupée. Nouvelle tentative dans quelques instants.")
        }
    }

    private suspend fun ecrireBrut(octets: ByteArray): Boolean {
        if (octets.isEmpty()) return true
        val s = prise ?: return false
        return withContext(Dispatchers.IO) {
            runCatching { s.getOutputStream().apply { write(octets); flush() } }.isSuccess
        }
    }

    /** Une opération Bluetooth, et sa fin attendue. @return ce qu'elle a rendu, ou `null`. */
    private suspend fun operation(lancer: () -> Boolean): ByteArray? {
        val fin = CompletableDeferred<ByteArray?>()
        attente = fin
        if (!lancer()) { attente = null; return null }
        return withTimeoutOrNull(8_000) { fin.await() }.also { attente = null }
    }

    private suspend fun ecrire(octets: ByteArray): Boolean {
        cadrage?.let { c -> return ecrireBrut(c.encadrer(octets)) }
        val g = gatt ?: return false
        val p = pilote ?: return false
        val (service, cible) = when (p.protocole) {
            Protocole.MESHCORE -> MeshCore.SERVICE to MeshCore.RX
            Protocole.MESHTASTIC -> Meshtastic.SERVICE to Meshtastic.TO_RADIO
        }
        val c = g.getService(UUID.fromString(service))?.getCharacteristic(UUID.fromString(cible)) ?: return false
        val ecrit = operation {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                g.writeCharacteristic(c, octets, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == android.bluetooth.BluetoothStatusCodes.SUCCESS
            } else {
                @Suppress("DEPRECATION")
                run { c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT; c.value = octets; g.writeCharacteristic(c) }
            }
        } != null
        // Meshtastic ne pousse rien : après chaque écriture, on va lire ce qu'il répond.
        if (ecrit && p.protocole == Protocole.MESHTASTIC) lireToutMeshtastic()
        return ecrit
    }

    private suspend fun lireToutMeshtastic() {
        val g = gatt ?: return
        val c = g.getService(UUID.fromString(Meshtastic.SERVICE))?.getCharacteristic(UUID.fromString(Meshtastic.FROM_RADIO)) ?: return
        while (true) {
            val trame = operation { g.readCharacteristic(c) } ?: return
            if (trame.isEmpty()) return                      // file vide
            traiter(trame)
        }
    }

    /** Une trame de la radio : le pilote dit quoi répondre et ce qu'elle portait. */
    private suspend fun traiter(trame: ByteArray) {
        val p = pilote ?: return
        val reaction = p.recevoir(trame)
        _etat.value = _etat.value.copy(
            phase = if (p.prete) Phase.PRETE else Phase.CONNEXION,
            nom = p.identite ?: _etat.value.nom, canaux = p.canaux, erreur = null, reseau = cadrage != null,
        )
        if (p.prete) app.radio.lienChange()
        if (p.avance.version != _avance.value.version) _avance.value = p.avance
        for (message in reaction.messages) {
            val canal = p.canaux.firstOrNull { it.index == message.canal } ?: continue
            val emetteur = message.de?.let { app.messagerieRadio.nomDuContact(MessagerieRadio.cle(p.protocole, "d:$it")) }
            val equipes = app.equipes.equipes.value
            // Canal de crise (23/11/2026) : « @ALPHA texte » est pour l'équipe Alpha.
            val parCrise = equipes.firstNotNullOfOrNull { e ->
                val cc = e.canalCrise ?: return@firstNotNullOfOrNull null
                if (p.canalNomme(cc.nomPour(p.protocole == Protocole.MESHCORE))?.index != canal.index) null
                else cc.pourMoi(message.texte)?.let { e to it }
            }
            val estCanalDeCrise = equipes.any { e -> e.canalCrise?.let { p.canalNomme(it.nomPour(p.protocole == Protocole.MESHCORE))?.index == canal.index } == true }
            val ancienCanal = equipes.firstOrNull { p.canalNomme(canalDe(it, p.protocole))?.index == canal.index }
            // Rien ne se perd hors de portée des passerelles : ce que la radio a entendu sur un
            // canal de la plateforme (ou EMCOM) est remis au serveur au retour du réseau.
            if (estCanalDeCrise || ancienCanal != null || PlanRadio.normaliser(canal.nom) == "fr_emcom") {
                remonter(p.protocole, canal.nom, emetteur, message.texte)
            }
            val (equipe, texte) = parCrise ?: (ancienCanal?.let { it to message.texte } ?: continue)
            val nouveau = app.equipes.entenduParRadio(equipe.id, texte, System.currentTimeMillis(), emetteur) ?: continue
            // La veille ne fait pas sonner ce que la radio a entendu : c'est ici (23/11/2026).
            // Une notification par équipe, mise à jour à chaque message ; un Danger ou une demande
            // de secours sonne en plus en urgent.
            if (!(app.premierPlan && app.equipeAffichee == equipe.id)) {
                app.alertes.conversation(idNotificationEquipe(equipe.id), "${equipe.nom} · par radio",
                    FormatNotification.ligneRadio(nouveau.auteur, nouveau.texte), Alerte.Genre.MESSAGE, equipe.id)
            }
            FormatNotification.urgenceTerrain(app, nouveau.auteur, nouveau.texte, equipe.id)
        }
        // Tous les canaux du nœud et les messages directs, pour la messagerie radio (22/11/2026).
        app.messagerieRadio.recevoir(reaction.messages, reaction.directs, p)
        app.messagerieRadio.accuser(reaction.accuses)
        app.messagerieRadio.joindreChemins(reaction.chemins)
        reaction.aEcrire.forEach { ecrire(it) }
    }

    // --- Utilisateur radio avancé (22/11/2026) ---------------------------------------------

    private val _avance = MutableStateFlow(PiloteRadio.Avance())
    /** Tout ce que la radio a décrit d'elle-même : réglages, canaux complets, contacts. */
    val avance: StateFlow<PiloteRadio.Avance> = _avance

    val piloteCourant: PiloteRadio? get() = pilote

    /**
     * Envoie des trames d'administration déjà formées (le pilote sait les construire). Rend vrai
     * si toutes sont parties. Les clés et secrets ne sont jamais journalisés ici.
     */
    suspend fun envoyerAdmin(trames: List<ByteArray>): Boolean {
        if (pilote?.prete != true || trames.isEmpty()) return false
        val fin = CompletableDeferred<Boolean>()
        if (operations.trySend { fin.complete(trames.all { ecrire(it) }) }.isFailure) return false
        return withTimeoutOrNull(30_000) { fin.await() } == true
    }

    /** Relit réglages, canaux et contacts (après une écriture : on vérifie ce que la radio a gardé). */
    suspend fun relireAvance(): Boolean = when (val p = pilote) {
        is PiloteMeshCore -> envoyerAdmin(p.relireTout())
        is PiloteMeshtastic -> envoyerAdmin(p.relireTout())
        else -> false
    }

    // --- Émission ------------------------------------------------------------------------

    suspend fun envoyerAEquipe(equipe: Equipe, texte: String): String? {
        val p = pilote?.takeIf { it.prete } ?: return null
        // Le canal de la crise d'abord, adressé « @INDICATIF » (23/11/2026) ; à défaut l'ancien
        // canal de l'équipe (téléphones et passerelles pas encore alignés).
        val cc = equipe.canalCrise
        val parCrise = cc?.let { p.canalNomme(it.nomPour(p.protocole == Protocole.MESHCORE)) }
        val canal = parCrise ?: p.canalNomme(canalDe(equipe, p.protocole)) ?: return null
        val contenu = if (parCrise != null && cc != null) cc.adresser(texte) else texte
        val trames = p.envoyerSurCanal(canal.index, app.radio.texteSelonLaZone(contenu), System.currentTimeMillis() / 1000)
        val fin = CompletableDeferred<Boolean>()
        if (operations.trySend { fin.complete(trames.all { ecrire(it) }) }.isFailure) return null
        return if (withTimeoutOrNull(20_000) { fin.await() } == true) p.protocole.name else null
    }

    /** Le canal par lequel on parle à cette équipe sur la radio connectée : celui de la crise,
     * sinon l'ancien canal de l'équipe. */
    fun canalPour(equipe: Equipe): CanalRadio? = pilote?.let { p ->
        equipe.canalCrise?.let { p.canalNomme(it.nomPour(p.protocole == Protocole.MESHCORE)) } ?: p.canalNomme(canalDe(equipe, p.protocole))
    }

    /** Met en file, pour le serveur, un message entendu par cette radio. */
    private suspend fun remonter(protocole: Protocole, canal: String, auteur: String?, texte: String) {
        val maintenant = System.currentTimeMillis()
        val identifiant = "${protocole.name}-${canal.hashCode().toUInt().toString(16)}-${texte.hashCode().toUInt().toString(16)}-${maintenant / 60_000}"
        if (app.file.actions.value.any { it.genre == ActionEnAttente.GENRE_ENTENDU_RADIO && it.cible == identifiant }) return
        val charge = kotlinx.serialization.json.buildJsonObject {
            put("identifiant", kotlinx.serialization.json.JsonPrimitive(identifiant))
            put("protocole", kotlinx.serialization.json.JsonPrimitive(protocole.name))
            put("canal", kotlinx.serialization.json.JsonPrimitive(canal))
            if (auteur != null) put("auteur", kotlinx.serialization.json.JsonPrimitive(auteur))
            put("texte", kotlinx.serialization.json.JsonPrimitive(texte))
            put("entendu_le", kotlinx.serialization.json.JsonPrimitive(java.time.Instant.ofEpochMilli(maintenant).toString()))
        }.toString()
        runCatching { app.file.ajouter(ActionEnAttente.GENRE_ENTENDU_RADIO, identifiant, charge, "Message radio entendu ($canal)") }
    }

    fun canalDe(equipe: Equipe, protocole: Protocole = emplacement): String? =
        if (protocole == Protocole.MESHCORE) equipe.canalMeshCore else equipe.canalMeshtastic

    private val FICHIER = "radio-${emplacement.name.lowercase()}"

    companion object {
        fun idNotificationEquipe(equipe: String) = "equipe-radio:$equipe"
        private const val ANCIEN_FICHIER = "radio"
        private const val RESEAU = "reseau"
        private const val BLUETOOTH = "bluetooth"
        private const val CCCD = "00002902-0000-1000-8000-00805f9b34fb"

        val PERMISSIONS: Array<String> =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
            else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)

        fun autorise(contexte: Context): Boolean =
            PERMISSIONS.all { contexte.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }
    }
}
