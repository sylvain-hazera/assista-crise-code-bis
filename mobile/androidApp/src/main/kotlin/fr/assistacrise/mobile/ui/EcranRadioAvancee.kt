package fr.assistacrise.mobile.ui

import android.graphics.Bitmap
import android.util.Base64
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.lien.PiloteMeshtastic
import fr.assistacrise.mobile.lien.PiloteRadio
import fr.assistacrise.mobile.lien.Protocole
import fr.assistacrise.mobile.lien.depuisHex
import fr.assistacrise.mobile.lien.enHex
import fr.assistacrise.mobile.lien.meshcore.AdminMeshCore
import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.AdminMeshtastic
import fr.assistacrise.mobile.lien.meshtastic.CanalMeshtastic
import fr.assistacrise.mobile.lien.meshtastic.ChampReglage
import fr.assistacrise.mobile.lien.meshtastic.Meshtastic
import fr.assistacrise.mobile.lien.meshtastic.SchemaMeshtastic
import fr.assistacrise.mobile.lien.meshtastic.SectionReglage
import fr.assistacrise.mobile.lien.meshtastic.TypeReglage
import java.security.MessageDigest
import java.security.SecureRandom

/**
 * « Utilisateur radio avancé » (22/11/2026) : l'intégralité des menus de la radio connectée,
 * Meshtastic ou MeshCore — canaux, contacts, réglages, outils. Chaque écriture est résumée et
 * confirmée ; ce qui peut couper la radio du réseau demande une confirmation renforcée ; la
 * radio est relue après chaque écriture, pour afficher ce qu'elle a réellement gardé.
 */
@Composable
fun EcranRadioAvancee(modele: ModeleApplication) {
    val etat by modele.radio.collectAsStateWithLifecycle()
    val avance by modele.radioAvance.collectAsStateWithLifecycle()
    var onglet by rememberSaveable { mutableStateOf(0) }
    val pilote = modele.piloteRadio

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { modele.aller(Ecran.COMPTE) }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") }
            Column(Modifier.weight(1f)) {
                Text("Radio avancée", style = MaterialTheme.typography.titleLarge)
                Text("${etat.nom ?: "Radio"} · ${etat.protocole?.libelle ?: "non connectée"}", style = MaterialTheme.typography.bodySmall)
            }
            TextButton(onClick = modele::relireLaRadio) { Text("Relire") }
        }
        if (pilote == null || !pilote.prete) {
            Text("Connectez d'abord une radio (écran Compte).", modifier = Modifier.padding(16.dp))
            return@Column
        }
        avance.derniereReponse?.let { Text("Dernière réponse de la radio : $it", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 16.dp)) }
        TabRow(selectedTabIndex = onglet) {
            listOf("Canaux", "Contacts", "Réglages", "Outils").forEachIndexed { i, nom ->
                Tab(selected = onglet == i, onClick = { onglet = i }, text = { Text(nom) })
            }
        }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            when (pilote.protocole) {
                Protocole.MESHTASTIC -> when (onglet) {
                    0 -> CanauxMeshtastic(modele, pilote as PiloteMeshtastic, avance)
                    1 -> ContactsMeshtastic(modele, pilote as PiloteMeshtastic, avance)
                    2 -> ReglagesMeshtastic(modele, pilote as PiloteMeshtastic, avance)
                    else -> OutilsMeshtastic(modele, pilote as PiloteMeshtastic)
                }
                Protocole.MESHCORE -> when (onglet) {
                    0 -> CanauxMeshCore(modele, avance)
                    1 -> ContactsMeshCore(modele, avance)
                    2 -> ReglagesMeshCore(modele, avance)
                    else -> OutilsMeshCore(modele)
                }
            }
        }
    }
}

// ── Confirmations ──

@Composable
private fun Confirmer(titre: String, texte: String, sensible: Boolean, surOui: () -> Unit, surNon: () -> Unit) {
    var etape by remember { mutableStateOf(0) }
    AlertDialog(
        onDismissRequest = surNon,
        title = { Text(if (etape == 0) titre else "Êtes-vous sûr ?") },
        text = {
            Text(if (etape == 0) texte else "Ce réglage peut couper la radio du réseau de votre équipe : elle n'entendra plus ses coéquipiers tant qu'elle ne sera pas réglée comme eux. À ne faire qu'en connaissance de cause.")
        },
        confirmButton = {
            TextButton(onClick = { if (sensible && etape == 0) etape = 1 else surOui() }) { Text(if (sensible && etape == 0) "Continuer" else "Envoyer à la radio") }
        },
        dismissButton = { TextButton(onClick = surNon) { Text("Annuler") } },
    )
}

@Composable
private fun ConfirmerEffacement(titre: String, texte: String, surOui: () -> Unit, surNon: () -> Unit) {
    var saisie by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = surNon,
        title = { Text(titre) },
        text = {
            Column {
                Text(texte)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(saisie, { saisie = it }, label = { Text("Tapez EFFACER pour confirmer") }, singleLine = true)
            }
        },
        confirmButton = { TextButton(enabled = saisie.trim() == "EFFACER", onClick = surOui) { Text("Effacer") } },
        dismissButton = { TextButton(onClick = surNon) { Text("Annuler") } },
    )
}

// ── Meshtastic ──

@Composable
private fun CanauxMeshtastic(modele: ModeleApplication, pilote: PiloteMeshtastic, avance: PiloteRadio.Avance) {
    var edite by remember { mutableStateOf<CanalMeshtastic?>(null) }
    val presse = LocalClipboardManager.current
    Text("Huit emplacements. Le canal primaire porte le préréglage radio ; les clés ne sont jamais affichées.", style = MaterialTheme.typography.bodySmall)
    (0 until 8).forEach { i ->
        val c = avance.canauxMeshtastic[i] ?: CanalMeshtastic(i, "", 0)
        Card(Modifier.fillMaxWidth()) {
            Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("$i · ${c.nom.ifBlank { if (c.role == 1) "Primaire (sans nom)" else "—" }}", style = MaterialTheme.typography.bodyLarge)
                    Text("${listOf("Désactivé", "Primaire", "Secondaire")[c.role.coerceIn(0, 2)]} · clé ${AdminMeshtastic.pskLisible(c.psk)}", style = MaterialTheme.typography.bodySmall)
                }
                TextButton(onClick = { edite = c }) { Text("Modifier") }
            }
        }
    }
    lienDePartage(avance)?.let { lien ->
        Text("Partager les canaux (lien et QR code des applications officielles)", style = MaterialTheme.typography.titleSmall)
        CodeQr(lien)
        OutlinedButton(onClick = { presse.setText(AnnotatedString(lien)) }) { Text("Copier le lien") }
        Text("Ce lien contient les clés des canaux : ne le partagez qu'avec votre équipe.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
    }
    edite?.let { c -> EditeurCanalMeshtastic(c, { edite = null }) { nouveau ->
        modele.envoyerALaRadio(pilote.adminGroupe(listOf(AdminMeshtastic.ecrireCanal(nouveau))), "Canal ${nouveau.index}")
        edite = null
    } }
}

@Composable
private fun EditeurCanalMeshtastic(c: CanalMeshtastic, surAnnuler: () -> Unit, surEnregistrer: (CanalMeshtastic) -> Unit) {
    var nom by remember { mutableStateOf(c.nom) }
    var role by remember { mutableStateOf(c.role) }
    var cle by remember { mutableStateOf("garder") }
    var cleSaisie by remember { mutableStateOf("") }
    var montant by remember { mutableStateOf(c.montant) }
    var descendant by remember { mutableStateOf(c.descendant) }
    var precision by remember { mutableStateOf(c.precisionPosition.toString()) }
    var confirmer by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = surAnnuler,
        title = { Text("Canal ${c.index}") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                OutlinedTextField(nom, { nom = it.take(11) }, label = { Text("Nom (11 caractères au plus)") }, singleLine = true)
                Liste("Rôle", listOf(0 to "Désactivé", 1 to "Primaire", 2 to "Secondaire"), role) { role = it }
                Liste("Clé", listOf(0 to "Garder la clé actuelle", 1 to "Nouvelle clé aléatoire (256 bits)", 2 to "Clé par défaut publique", 3 to "Saisir une clé (base64)"),
                    when (cle) { "garder" -> 0; "aleatoire" -> 1; "defaut" -> 2; else -> 3 }) { cle = listOf("garder", "aleatoire", "defaut", "saisie")[it] }
                if (cle == "saisie") OutlinedTextField(cleSaisie, { cleSaisie = it }, label = { Text("Clé en base64") }, visualTransformation = PasswordVisualTransformation(), singleLine = true)
                Interrupteur("Montée MQTT", montant) { montant = it }
                Interrupteur("Descente MQTT", descendant) { descendant = it }
                OutlinedTextField(precision, { precision = it.filter(Char::isDigit).take(2) }, label = { Text("Précision de position partagée (0 = aucune, 32 = exacte)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true)
            }
        },
        confirmButton = { TextButton(onClick = { confirmer = true }) { Text("Enregistrer") } },
        dismissButton = { TextButton(onClick = surAnnuler) { Text("Annuler") } },
    )
    if (confirmer) {
        val psk = when (cle) {
            "aleatoire" -> ByteArray(32).also { SecureRandom().nextBytes(it) }
            "defaut" -> byteArrayOf(1)
            "saisie" -> runCatching { Base64.decode(cleSaisie.trim(), Base64.DEFAULT) }.getOrDefault(c.psk)
            else -> c.psk
        }
        Confirmer("Écrire le canal ${c.index} ?",
            "Nom « $nom », ${listOf("désactivé", "primaire", "secondaire")[role]}, clé ${if (cle == "garder") "inchangée" else AdminMeshtastic.pskLisible(psk)}." +
                if (cle != "garder") "\nLes coéquipiers devront avoir la même clé pour s'entendre." else "",
            sensible = cle != "garder" || role != c.role,
            surOui = { confirmer = false; surEnregistrer(c.copy(nom = nom, role = role, psk = psk, montant = montant, descendant = descendant, precisionPosition = precision.toIntOrNull() ?: 0)) },
            surNon = { confirmer = false })
    }
}

@Composable
private fun ContactsMeshtastic(modele: ModeleApplication, pilote: PiloteMeshtastic, avance: PiloteRadio.Avance) {
    var message by remember { mutableStateOf<Long?>(null) }
    var retirer by remember { mutableStateOf<Long?>(null) }
    val noeuds = avance.noeuds.values.filter { it.numero != avance.monNoeud }.sortedByDescending { it.dernierContact ?: 0 }
    Text("${noeuds.size} nœud(s) entendu(s)", style = MaterialTheme.typography.bodySmall)
    noeuds.forEach { n ->
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp)) {
                Text("${if (n.favori) "★ " else ""}${n.nomLong.ifBlank { n.identifiant }} (${n.nomCourt.ifBlank { "?" }})", style = MaterialTheme.typography.bodyLarge)
                Text(listOfNotNull(n.identifiant, n.snr?.let { "SNR ${"%.1f".format(it)} dB" }, n.sauts?.let { "$it saut(s)" },
                    n.dernierContact?.let { "vu ${ilYA(it * 1000)}" }, n.latitude?.let { "position connue" }).joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                Row {
                    TextButton(onClick = { message = n.numero }) { Text("Message") }
                    TextButton(onClick = { modele.envoyerALaRadio(listOfNotNull(pilote.admin(AdminMeshtastic.favori(n.numero, !n.favori))), if (n.favori) "Retrait des favoris" else "Ajout aux favoris") }) {
                        Text(if (n.favori) "Retirer des favoris" else "Favori")
                    }
                    TextButton(onClick = { retirer = n.numero }) { Text("Oublier") }
                }
            }
        }
    }
    message?.let { num ->
        SaisieTexte("Message direct", "Texte", surAnnuler = { message = null }) { texte ->
            modele.envoyerALaRadio(Meshtastic.decouper(texte).map { Meshtastic.texte(num, it, (1L..0xffffffffL).random()) }, "Message direct", relire = false)
            message = null
        }
    }
    retirer?.let { num ->
        Confirmer("Oublier ce nœud ?", "Il disparaît de la liste de la radio jusqu'à ce qu'elle l'entende de nouveau.", false,
            { modele.envoyerALaRadio(listOfNotNull(pilote.admin(AdminMeshtastic.retirerNoeud(num))), "Nœud oublié"); retirer = null }, { retirer = null })
    }
}

@Composable
private fun ReglagesMeshtastic(modele: ModeleApplication, pilote: PiloteMeshtastic, avance: PiloteRadio.Avance) {
    var ouverte by remember { mutableStateOf<SectionReglage?>(null) }
    var proprietaire by remember { mutableStateOf(false) }
    OutlinedButton(onClick = { proprietaire = true }, modifier = Modifier.fillMaxWidth()) {
        Text("Identité du nœud : ${avance.proprietaire?.first ?: "à relire"}")
    }
    Text("Configuration", style = MaterialTheme.typography.titleSmall)
    SchemaMeshtastic.config.forEach { s -> LigneSection(s, avance) { ouverte = s } }
    Text("Modules", style = MaterialTheme.typography.titleSmall)
    SchemaMeshtastic.modules.forEach { s -> LigneSection(s, avance) { ouverte = s } }
    ouverte?.let { s ->
        val origine = avance.reglages[s.conteneur to s.numero]
        if (origine == null) {
            AlertDialog(onDismissRequest = { ouverte = null }, title = { Text(s.libelle) },
                text = { Text("Cette section n'a pas encore été lue. Demandez-la à la radio.") },
                confirmButton = { TextButton(onClick = { modele.envoyerALaRadio(listOfNotNull(pilote.admin(AdminMeshtastic.demanderConfig(s))), "Lecture « ${s.libelle} »", relire = false); ouverte = null }) { Text("Lire") } },
                dismissButton = { TextButton(onClick = { ouverte = null }) { Text("Fermer") } })
        } else {
            EditeurSection(s, origine, { ouverte = null }) { contenu ->
                modele.envoyerALaRadio(pilote.adminGroupe(listOf(AdminMeshtastic.ecrireConfig(s, contenu))) +
                    listOfNotNull(pilote.admin(AdminMeshtastic.demanderConfig(s))), "Réglages « ${s.libelle} »", relire = false)
                ouverte = null
            }
        }
    }
    if (proprietaire) {
        var nomLong by remember { mutableStateOf(avance.proprietaire?.first ?: "") }
        var nomCourt by remember { mutableStateOf(avance.proprietaire?.second ?: "") }
        AlertDialog(onDismissRequest = { proprietaire = false }, title = { Text("Identité du nœud") },
            text = {
                Column {
                    OutlinedTextField(nomLong, { nomLong = it.take(39) }, label = { Text("Nom long") }, singleLine = true)
                    OutlinedTextField(nomCourt, { nomCourt = it.take(4) }, label = { Text("Nom court (4 caractères)") }, singleLine = true)
                }
            },
            confirmButton = { TextButton(onClick = {
                modele.envoyerALaRadio(pilote.adminGroupe(listOf(AdminMeshtastic.ecrireProprietaire(nomLong, nomCourt))) +
                    listOfNotNull(pilote.admin(AdminMeshtastic.demanderProprietaire())), "Identité du nœud", relire = false)
                proprietaire = false
            }) { Text("Enregistrer") } },
            dismissButton = { TextButton(onClick = { proprietaire = false }) { Text("Annuler") } })
    }
}

@Composable
private fun LigneSection(s: SectionReglage, avance: PiloteRadio.Avance, surClic: () -> Unit) {
    val lue = avance.reglages.containsKey(s.conteneur to s.numero)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(s.libelle, modifier = Modifier.weight(1f))
        Text(if (lue) "${s.champs.size} réglages" else "non lue", style = MaterialTheme.typography.bodySmall)
        TextButton(onClick = surClic) { Text("Ouvrir") }
    }
    HorizontalDivider()
}

@Composable
private fun EditeurSection(s: SectionReglage, origine: ByteArray, surAnnuler: () -> Unit, surEnregistrer: (ByteArray) -> Unit) {
    val depart = remember(origine) { AdminMeshtastic.lireSection(s, origine) }
    val valeurs = remember(origine) { mutableStateMapOf<Int, Any>().also { it.putAll(depart) } }
    var confirmer by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = surAnnuler,
        title = { Text(s.libelle) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                s.champs.filter { it.numero in depart }.forEach { c -> EditeurChamp(c, valeurs[c.numero]) { valeurs[c.numero] = it } }
            }
        },
        confirmButton = { TextButton(onClick = { confirmer = true }) { Text("Enregistrer") } },
        dismissButton = { TextButton(onClick = surAnnuler) { Text("Annuler") } },
    )
    if (confirmer) {
        val changes = s.champs.filter { c -> !egal(depart[c.numero], valeurs[c.numero]) }
        if (changes.isEmpty()) { confirmer = false; surAnnuler(); return }
        Confirmer("Écrire « ${s.libelle} » ?",
            changes.joinToString("\n") { c -> "• ${c.libelle} : ${afficher(c, depart[c.numero])} → ${afficher(c, valeurs[c.numero])}" },
            sensible = changes.any { it.sensible },
            surOui = { confirmer = false; surEnregistrer(AdminMeshtastic.ecrireSection(s, origine, valeurs.toMap())) },
            surNon = { confirmer = false })
    }
}

private fun egal(a: Any?, b: Any?) = if (a is ByteArray && b is ByteArray) a.contentEquals(b) else a == b

private fun afficher(c: ChampReglage, v: Any?): String = when {
    c.secret -> "••••"
    v is Boolean -> if (v) "oui" else "non"
    c.type == TypeReglage.ENUM -> c.valeurs.firstOrNull { it.first.toLong() == (v as? Number)?.toLong() }?.second ?: v.toString()
    v is ByteArray -> "${v.size} octets"
    else -> v.toString()
}

@Composable
private fun EditeurChamp(c: ChampReglage, valeur: Any?, surChange: (Any) -> Unit) {
    when (c.type) {
        TypeReglage.BOOL -> Interrupteur(c.libelle + if (c.sensible) " ⚠" else "", valeur as? Boolean ?: false) { surChange(it) }
        TypeReglage.ENUM -> Liste(c.libelle + if (c.sensible) " ⚠" else "", c.valeurs, ((valeur as? Number)?.toInt()) ?: 0) { surChange(it.toLong()) }
        TypeReglage.TEXTE -> OutlinedTextField(valeur as? String ?: "", { surChange(it) }, label = { Text(c.libelle) }, singleLine = true,
            visualTransformation = if (c.secret) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None)
        TypeReglage.FLOAT -> {
            var texte by remember(valeur) { mutableStateOf((valeur as? Number)?.toFloat()?.toString() ?: "0") }
            OutlinedTextField(texte, { texte = it; it.replace(',', '.').toFloatOrNull()?.let(surChange) }, label = { Text(c.libelle + if (c.sensible) " ⚠" else "") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true)
        }
        TypeReglage.OCTETS -> {
            // Clés : affichées masquées, remplacées seulement si l'on en saisit une (base64).
            var texte by remember { mutableStateOf("") }
            OutlinedTextField(texte, { texte = it; runCatching { Base64.decode(it.trim(), Base64.DEFAULT) }.getOrNull()?.let(surChange) },
                label = { Text("${c.libelle} (${(valeur as? ByteArray)?.size ?: 0} octets, vide = inchangé)") },
                visualTransformation = PasswordVisualTransformation(), singleLine = true)
        }
        else -> {
            var texte by remember(valeur) { mutableStateOf((valeur as? Number)?.toLong()?.toString() ?: "0") }
            OutlinedTextField(texte, { texte = it; it.toLongOrNull()?.let(surChange) }, label = { Text(c.libelle + if (c.sensible) " ⚠" else "") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true)
        }
    }
}

@Composable
private fun OutilsMeshtastic(modele: ModeleApplication, pilote: PiloteMeshtastic) {
    var effacer by remember { mutableStateOf<String?>(null) }
    var redemarrer by remember { mutableStateOf(false) }
    Button(onClick = { redemarrer = true }, modifier = Modifier.fillMaxWidth()) { Text("Redémarrer la radio") }
    OutlinedButton(onClick = { effacer = "noeuds" }, modifier = Modifier.fillMaxWidth()) { Text("Réinitialiser la liste des nœuds") }
    Button(onClick = { effacer = "usine" }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error), modifier = Modifier.fillMaxWidth()) {
        Text("Retour aux réglages d'usine")
    }
    if (redemarrer) Confirmer("Redémarrer la radio ?", "Elle sera injoignable une trentaine de secondes, puis se reconnectera seule.", false,
        { modele.envoyerALaRadio(listOfNotNull(pilote.admin(AdminMeshtastic.redemarrer())), "Redémarrage", relire = false); redemarrer = false }, { redemarrer = false })
    effacer?.let { quoi ->
        ConfirmerEffacement(
            if (quoi == "usine") "Retour aux réglages d'usine" else "Réinitialiser la liste des nœuds",
            if (quoi == "usine") "Tous les réglages et canaux de la radio seront effacés : elle ne sera plus sur le réseau de votre équipe." else "La radio oubliera tous les nœuds entendus.",
            surOui = {
                modele.envoyerALaRadio(listOfNotNull(pilote.admin(if (quoi == "usine") AdminMeshtastic.retourUsine() else AdminMeshtastic.reinitialiserNoeuds())),
                    if (quoi == "usine") "Retour usine" else "Liste des nœuds réinitialisée", relire = false)
                effacer = null
            }, surNon = { effacer = null })
    }
}

/** Le lien des applications officielles (`https://meshtastic.org/e/#…`) : ChannelSet des canaux actifs + LoRa. */
private fun lienDePartage(avance: PiloteRadio.Avance): String? {
    val canaux = avance.canauxMeshtastic.values.filter { it.role != 0 }.sortedBy { it.index }
    if (canaux.isEmpty()) return null
    val octets = java.io.ByteArrayOutputStream()
    fun varint(v: Long) { var x = v; while (x >= 0x80) { octets.write(((x and 0x7f) or 0x80).toInt()); x = x ushr 7 }; octets.write(x.toInt()) }
    fun brut(numero: Int, b: ByteArray) { varint((numero.toLong() shl 3) or 2); varint(b.size.toLong()); octets.write(b) }
    for (c in canaux) {
        val r = java.io.ByteArrayOutputStream()
        fun rv(v: Long) { var x = v; while (x >= 0x80) { r.write(((x and 0x7f) or 0x80).toInt()); x = x ushr 7 }; r.write(x.toInt()) }
        if (c.psk.isNotEmpty()) { rv((2L shl 3) or 2); rv(c.psk.size.toLong()); r.write(c.psk) }
        if (c.nom.isNotEmpty()) { val n = c.nom.encodeToByteArray(); rv((3L shl 3) or 2); rv(n.size.toLong()); r.write(n) }
        brut(1, r.toByteArray())
    }
    avance.reglages[fr.assistacrise.mobile.lien.meshtastic.Conteneur.CONFIG to 6]?.let { brut(2, it) }
    return "https://meshtastic.org/e/#" + Base64.encodeToString(octets.toByteArray(), Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
}

// ── MeshCore ──

@Composable
private fun CanauxMeshCore(modele: ModeleApplication, avance: PiloteRadio.Avance) {
    var edite by remember { mutableStateOf<Int?>(null) }
    var effacer by remember { mutableStateOf<Int?>(null) }
    Text("Les emplacements occupés. Un nom commençant par « # » est un canal public : sa clé se déduit du nom.", style = MaterialTheme.typography.bodySmall)
    avance.canauxMeshCore.values.sortedBy { it.index }.forEach { c ->
        Card(Modifier.fillMaxWidth()) {
            Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("${c.index} · ${c.nom}", modifier = Modifier.weight(1f))
                TextButton(onClick = { edite = c.index }) { Text("Modifier") }
                TextButton(onClick = { effacer = c.index }) { Text("Retirer") }
            }
        }
    }
    val libre = (0 until MeshCore.EMPLACEMENTS).firstOrNull { it !in avance.canauxMeshCore }
    if (libre != null) OutlinedButton(onClick = { edite = libre }) { Text("Ajouter un canal (emplacement $libre)") }
    edite?.let { i ->
        val actuel = avance.canauxMeshCore[i]
        var nom by remember(i) { mutableStateOf(actuel?.nom ?: "") }
        var secret by remember(i) { mutableStateOf("") }
        var confirmer by remember(i) { mutableStateOf(false) }
        AlertDialog(onDismissRequest = { edite = null }, title = { Text("Canal $i") },
            text = {
                Column {
                    OutlinedTextField(nom, { nom = it.take(31) }, label = { Text("Nom (« #nom » pour un canal public)") }, singleLine = true)
                    if (!nom.startsWith("#")) OutlinedTextField(secret, { secret = it }, label = { Text("Secret, 32 caractères hexadécimaux (vide = aléatoire, ou inchangé)") },
                        visualTransformation = PasswordVisualTransformation(), singleLine = true)
                }
            },
            confirmButton = { TextButton(enabled = nom.isNotBlank(), onClick = { confirmer = true }) { Text("Enregistrer") } },
            dismissButton = { TextButton(onClick = { edite = null }) { Text("Annuler") } })
        if (confirmer) {
            val cle = when {
                nom.startsWith("#") -> MessageDigest.getInstance("SHA-256").digest(nom.encodeToByteArray()).copyOf(16)
                secret.isNotBlank() -> secret.depuisHex().takeIf { it.size == 16 }
                actuel != null && actuel.secret.size == 16 -> actuel.secret
                else -> ByteArray(16).also { SecureRandom().nextBytes(it) }
            }
            if (cle == null) { modele.envoyerALaRadio(emptyList(), "Secret invalide (32 caractères hexadécimaux)", relire = false); confirmer = false }
            else Confirmer("Écrire le canal $i ?", "Nom « $nom ». Les coéquipiers devront avoir le même nom et la même clé.", sensible = actuel != null,
                surOui = { modele.envoyerALaRadio(listOf(AdminMeshCore.ecrireCanal(i, nom, cle), MeshCore.demanderCanal(i)), "Canal $i", relire = false); confirmer = false; edite = null },
                surNon = { confirmer = false })
        }
    }
    effacer?.let { i ->
        Confirmer("Retirer le canal $i ?", "La radio n'entendra plus ce canal.", true,
            { modele.envoyerALaRadio(listOf(AdminMeshCore.effacerCanal(i), MeshCore.demanderCanal(i)), "Canal $i retiré", relire = false); effacer = null }, { effacer = null })
    }
}

@Composable
private fun ContactsMeshCore(modele: ModeleApplication, avance: PiloteRadio.Avance) {
    var message by remember { mutableStateOf<String?>(null) }
    var supprimer by remember { mutableStateOf<String?>(null) }
    var importer by remember { mutableStateOf(false) }
    val presse = LocalClipboardManager.current
    Row {
        OutlinedButton(onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.demanderContacts()), "Lecture des contacts", relire = false) }) { Text("Relire les contacts") }
        Spacer(Modifier.size(8.dp))
        OutlinedButton(onClick = { importer = true }) { Text("Importer") }
    }
    avance.carte?.let { carte ->
        Text("Carte exportée : meshcore://${carte.enHex()}", style = MaterialTheme.typography.bodySmall)
        TextButton(onClick = { presse.setText(AnnotatedString("meshcore://${carte.enHex()}")) }) { Text("Copier la carte") }
    }
    avance.contacts.values.sortedByDescending { it.derniereAnnonce }.forEach { c ->
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp)) {
                Text(c.nom.ifBlank { c.pubkeyHex.take(12) }, style = MaterialTheme.typography.bodyLarge)
                Text("${c.genre} · ${c.chemin} · ${c.pubkeyHex.take(12)}…${if (c.latitude != 0.0) " · position connue" else ""}", style = MaterialTheme.typography.bodySmall)
                Row {
                    if (c.type == 1) TextButton(onClick = { message = c.pubkeyHex }) { Text("Message") }
                    TextButton(onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.reinitialiserChemin(c.pubkeyHex)), "Chemin réinitialisé", relire = false) }) { Text("Chemin") }
                    TextButton(onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.partagerContact(c.pubkeyHex)), "Contact partagé sur le réseau", relire = false) }) { Text("Partager") }
                    TextButton(onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.exporterContact(c.pubkeyHex)), "Export de la carte", relire = false) }) { Text("Exporter") }
                    TextButton(onClick = { supprimer = c.pubkeyHex }) { Text("Supprimer") }
                }
            }
        }
    }
    message?.let { cle ->
        SaisieTexte("Message direct", "Texte", surAnnuler = { message = null }) { texte ->
            modele.envoyerALaRadio(listOf(MeshCore.envoyerMessage(cle, texte, System.currentTimeMillis() / 1000)), "Message direct", relire = false)
            message = null
        }
    }
    supprimer?.let { cle ->
        Confirmer("Supprimer ce contact ?", "La radio l'oubliera jusqu'à sa prochaine annonce.", false,
            { modele.envoyerALaRadio(listOf(AdminMeshCore.retirerContact(cle), AdminMeshCore.demanderContacts()), "Contact supprimé", relire = false); supprimer = null }, { supprimer = null })
    }
    if (importer) SaisieTexte("Importer une carte de contact", "meshcore://… ou hexadécimal", surAnnuler = { importer = false }) { texte ->
        val carte = texte.removePrefix("meshcore://").trim().depuisHex()
        modele.envoyerALaRadio(listOf(AdminMeshCore.importerContact(carte), AdminMeshCore.demanderContacts()), "Import du contact", relire = false)
        importer = false
    }
}

@Composable
private fun ReglagesMeshCore(modele: ModeleApplication, avance: PiloteRadio.Avance) {
    val moi = avance.moi ?: run { Text("Réglages non lus : touchez « Relire »."); return }
    var nom by remember(moi) { mutableStateOf(moi.nom) }
    var lat by remember(moi) { mutableStateOf(moi.latitude.toString()) }
    var lon by remember(moi) { mutableStateOf(moi.longitude.toString()) }
    var puissance by remember(moi) { mutableStateOf(moi.puissance.toString()) }
    var freq by remember(moi) { mutableStateOf(moi.frequenceMhz.toString()) }
    var bande by remember(moi) { mutableStateOf(moi.bandeKhz.toString()) }
    var sf by remember(moi) { mutableStateOf(moi.facteurEtalement.toString()) }
    var cr by remember(moi) { mutableStateOf(moi.tauxCodage.toString()) }
    var manuel by remember(moi) { mutableStateOf(moi.ajoutManuel) }
    var tBase by remember(moi) { mutableStateOf(moi.telemetrieBase) }
    var tPos by remember(moi) { mutableStateOf(moi.telemetriePosition) }
    var tEnv by remember(moi) { mutableStateOf(moi.telemetrieEnv) }
    var politique by remember(moi) { mutableStateOf(moi.politiquePosition) }
    var multi by remember(moi) { mutableStateOf(moi.multiAcks.toString()) }
    var pin by remember { mutableStateOf("") }
    var confirmerRadio by remember { mutableStateOf(false) }
    val telemetrie = listOf(0 to "Refusée", 1 to "Contacts favoris", 2 to "Tous")

    Text("Identité et position", style = MaterialTheme.typography.titleSmall)
    OutlinedTextField(nom, { nom = it.take(31) }, label = { Text("Nom annoncé") }, singleLine = true)
    Button(onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.ecrireNom(nom)), "Nom") }) { Text("Enregistrer le nom") }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(lat, { lat = it }, label = { Text("Latitude") }, singleLine = true, modifier = Modifier.weight(1f))
        OutlinedTextField(lon, { lon = it }, label = { Text("Longitude") }, singleLine = true, modifier = Modifier.weight(1f))
    }
    Button(onClick = {
        val la = lat.replace(',', '.').toDoubleOrNull(); val lo = lon.replace(',', '.').toDoubleOrNull()
        if (la != null && lo != null) modele.envoyerALaRadio(listOf(AdminMeshCore.ecrirePosition(la, lo)), "Position annoncée")
    }) { Text("Enregistrer la position") }

    Text("Radio ⚠", style = MaterialTheme.typography.titleSmall)
    OutlinedTextField(puissance, { puissance = it.filter(Char::isDigit) }, label = { Text("Puissance (dBm, maximum ${moi.puissanceMax})") }, singleLine = true)
    Button(onClick = { puissance.toIntOrNull()?.takeIf { it in 1..moi.puissanceMax }?.let { modele.envoyerALaRadio(listOf(AdminMeshCore.ecrirePuissance(it)), "Puissance") } }) { Text("Enregistrer la puissance") }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(freq, { freq = it }, label = { Text("Fréquence (MHz)") }, singleLine = true, modifier = Modifier.weight(1f))
        OutlinedTextField(bande, { bande = it }, label = { Text("Bande (kHz)") }, singleLine = true, modifier = Modifier.weight(1f))
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(sf, { sf = it.filter(Char::isDigit) }, label = { Text("Facteur d'étalement") }, singleLine = true, modifier = Modifier.weight(1f))
        OutlinedTextField(cr, { cr = it.filter(Char::isDigit) }, label = { Text("Taux de codage") }, singleLine = true, modifier = Modifier.weight(1f))
    }
    Button(onClick = { confirmerRadio = true }) { Text("Enregistrer les paramètres radio") }

    Text("Autres réglages", style = MaterialTheme.typography.titleSmall)
    Interrupteur("Ajout manuel des contacts", manuel) { manuel = it }
    Liste("Télémétrie de base", telemetrie, tBase) { tBase = it }
    Liste("Télémétrie de position", telemetrie, tPos) { tPos = it }
    Liste("Télémétrie d'environnement", telemetrie, tEnv) { tEnv = it }
    Liste("Position dans les annonces", listOf(0 to "Jamais", 1 to "Toujours", 2 to "Selon les contacts"), politique) { politique = it }
    OutlinedTextField(multi, { multi = it.filter(Char::isDigit).take(1) }, label = { Text("Accusés multiples") }, singleLine = true)
    Button(onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.ecrireAutresReglages(manuel, tBase, tPos, tEnv, politique, multi.toIntOrNull() ?: 0)), "Autres réglages") }) {
        Text("Enregistrer les autres réglages")
    }

    Text("Code Bluetooth", style = MaterialTheme.typography.titleSmall)
    OutlinedTextField(pin, { pin = it.filter(Char::isDigit).take(6) }, label = { Text("Nouveau code à 6 chiffres") }, visualTransformation = PasswordVisualTransformation(), singleLine = true)
    Button(enabled = pin.length == 6, onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.ecrireCodeBluetooth(pin.toInt())), "Code Bluetooth", relire = false); pin = "" }) {
        Text("Changer le code (appairage à refaire)")
    }

    if (confirmerRadio) {
        val f = freq.replace(',', '.').toDoubleOrNull(); val b = bande.replace(',', '.').toDoubleOrNull()
        val s = sf.toIntOrNull(); val c = cr.toIntOrNull()
        if (f == null || b == null || s == null || c == null) { confirmerRadio = false }
        else Confirmer("Paramètres radio", "$f MHz, $b kHz, SF $s, CR $c (actuels : ${moi.frequenceMhz} MHz, ${moi.bandeKhz} kHz, SF ${moi.facteurEtalement}, CR ${moi.tauxCodage}).", true,
            { modele.envoyerALaRadio(listOf(AdminMeshCore.ecrireRadio(f, b, s, c)), "Paramètres radio"); confirmerRadio = false }, { confirmerRadio = false })
    }
}

@Composable
private fun OutilsMeshCore(modele: ModeleApplication) {
    var effacer by remember { mutableStateOf(false) }
    var redemarrer by remember { mutableStateOf(false) }
    Button(onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.annoncer(false)), "Annonce (voisins)", relire = false) }, modifier = Modifier.fillMaxWidth()) { Text("S'annoncer aux voisins") }
    OutlinedButton(onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.annoncer(true)), "Annonce (tout le réseau)", relire = false) }, modifier = Modifier.fillMaxWidth()) { Text("S'annoncer à tout le réseau") }
    OutlinedButton(onClick = { modele.envoyerALaRadio(listOf(AdminMeshCore.exporterContact()), "Export de ma carte", relire = false) }, modifier = Modifier.fillMaxWidth()) { Text("Exporter ma carte de contact") }
    Button(onClick = { redemarrer = true }, modifier = Modifier.fillMaxWidth()) { Text("Redémarrer la radio") }
    Button(onClick = { effacer = true }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error), modifier = Modifier.fillMaxWidth()) {
        Text("Retour aux réglages d'usine")
    }
    if (redemarrer) Confirmer("Redémarrer la radio ?", "Elle sera injoignable quelques secondes, puis se reconnectera seule.", false,
        { modele.envoyerALaRadio(listOf(AdminMeshCore.redemarrer()), "Redémarrage", relire = false); redemarrer = false }, { redemarrer = false })
    if (effacer) ConfirmerEffacement("Retour aux réglages d'usine",
        "Clé privée, contacts, canaux et réglages seront effacés : la radio changera d'identité et quittera le réseau de votre équipe.",
        surOui = { modele.envoyerALaRadio(listOf(AdminMeshCore.retourUsine()), "Retour usine", relire = false); effacer = false }, surNon = { effacer = false })
}

// ── Petits composants ──

@Composable
private fun Interrupteur(libelle: String, valeur: Boolean, surChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(libelle, modifier = Modifier.weight(1f))
        Switch(checked = valeur, onCheckedChange = surChange)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Liste(libelle: String, choix: List<Pair<Int, String>>, valeur: Int, surChange: (Int) -> Unit) {
    var ouvert by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = ouvert, onExpandedChange = { ouvert = it }) {
        OutlinedTextField(choix.firstOrNull { it.first == valeur }?.second ?: valeur.toString(), {}, readOnly = true, label = { Text(libelle) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(ouvert) }, modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth())
        ExposedDropdownMenu(expanded = ouvert, onDismissRequest = { ouvert = false }) {
            choix.forEach { (v, nom) -> DropdownMenuItem(text = { Text(nom) }, onClick = { surChange(v); ouvert = false }) }
        }
    }
}

@Composable
private fun SaisieTexte(titre: String, libelle: String, surAnnuler: () -> Unit, surValider: (String) -> Unit) {
    var texte by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = surAnnuler, title = { Text(titre) },
        text = { OutlinedTextField(texte, { texte = it }, label = { Text(libelle) }) },
        confirmButton = { TextButton(enabled = texte.isNotBlank(), onClick = { surValider(texte.trim()) }) { Text("Envoyer") } },
        dismissButton = { TextButton(onClick = surAnnuler) { Text("Annuler") } })
}

@Composable
private fun CodeQr(contenu: String) {
    val image = remember(contenu) {
        val matrice = QRCodeWriter().encode(contenu, BarcodeFormat.QR_CODE, 512, 512)
        Bitmap.createBitmap(512, 512, Bitmap.Config.RGB_565).also { b ->
            for (x in 0 until 512) for (y in 0 until 512) b.setPixel(x, y, if (matrice[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
        }.asImageBitmap()
    }
    Image(image, contentDescription = "QR code des canaux", modifier = Modifier.size(220.dp))
}
