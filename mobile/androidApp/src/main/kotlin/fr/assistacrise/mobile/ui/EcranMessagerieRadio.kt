package fr.assistacrise.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.Badge
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.LiaisonRadio
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.lien.PiloteMeshCore
import fr.assistacrise.mobile.lien.PiloteMeshtastic
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Une ligne de la liste : un canal du nœud, ou un contact. */
private data class Entree(val cle: String, val nom: String, val detail: String)

/**
 * La radio dans l'écran Équipes (22/11/2026), pour l'utilisateur radio avancé : tous les canaux
 * du nœud connecté, et ses contacts (recherche par nom), chacun ouvrant une conversation.
 */
@Composable
fun PanneauRadio(modele: ModeleApplication) {
    val etat by modele.radio.collectAsStateWithLifecycle()
    val avance by modele.radioAvance.collectAsStateWithLifecycle()
    val conversations by modele.conversationsRadio.collectAsStateWithLifecycle()
    val nonLus by modele.nonLusRadio.collectAsStateWithLifecycle()
    var onglet by rememberSaveable { mutableStateOf(0) }
    var recherche by rememberSaveable { mutableStateOf("") }
    if (!modele.modeRadioAvance || etat.phase != LiaisonRadio.Phase.PRETE) return
    val pilote = modele.piloteRadio ?: return

    val canaux = pilote.canaux.map { Entree("c:${it.index}", it.nom, "Canal ${it.index}") }
    val contacts = when (pilote) {
        is PiloteMeshtastic -> avance.noeuds.values.filter { it.numero != avance.monNoeud }.sortedByDescending { it.dernierContact ?: 0 }
            .map { Entree("d:${it.identifiant}", it.nomLong.ifBlank { it.identifiant }, listOfNotNull(it.nomCourt.takeIf { s -> s.isNotBlank() }, it.identifiant, it.sauts?.let { s -> "$s saut(s)" }).joinToString(" · ")) }
        is PiloteMeshCore -> avance.contacts.values.sortedByDescending { it.derniereAnnonce }
            .map { Entree("d:${it.pubkeyHex.take(12)}", it.nom.ifBlank { it.pubkeyHex.take(12) }, "${it.genre} · ${it.chemin}") }
        else -> emptyList()
    }
    // Les conversations directes avec quelqu'un qui n'est plus dans la liste restent ouvrables.
    val orphelines = conversations.keys.filter { it.startsWith("d:") && contacts.none { c -> c.cle == it } }
        .map { Entree(it, modele.nomDuContactRadio(it.removePrefix("d:")), "Conversation") }

    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Text("Radio ${etat.protocole?.libelle ?: ""} · ${etat.nom ?: ""}", style = MaterialTheme.typography.titleMedium)
            TabRow(selectedTabIndex = onglet) {
                Tab(selected = onglet == 0, onClick = { onglet = 0 }, text = { Text("Canaux (${canaux.size})") })
                Tab(selected = onglet == 1, onClick = { onglet = 1 }, text = { Text("Contacts (${contacts.size})") })
            }
            if (onglet == 1) {
                OutlinedTextField(recherche, { recherche = it }, label = { Text("Rechercher par nom") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
            }
            val liste = if (onglet == 0) canaux else (contacts + orphelines).filter {
                recherche.isBlank() || it.nom.contains(recherche.trim(), ignoreCase = true) || it.detail.contains(recherche.trim(), ignoreCase = true)
            }
            if (liste.isEmpty()) Text(if (onglet == 0) "Aucun canal sur cette radio." else "Aucun contact.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(8.dp))
            liste.take(60).forEach { e ->
                Row(Modifier.fillMaxWidth().clickable { modele.ouvrirConversationRadio(e.cle) }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(e.nom, style = MaterialTheme.typography.bodyLarge)
                        val dernier = conversations[e.cle]?.lastOrNull()
                        Text(dernier?.let { "${if (it.moi) "Moi" else it.auteur.ifBlank { "?" }} : ${it.texte}" } ?: e.detail,
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                    }
                    nonLus[e.cle]?.takeIf { it > 0 }?.let { Badge { Text("$it") } }
                }
                HorizontalDivider()
            }
            if (liste.size > 60) Text("… affinez la recherche (${liste.size} résultats).", style = MaterialTheme.typography.bodySmall)
        }
    }
}

/** Une conversation radio : un canal du nœud, ou un échange direct. */
@Composable
fun EcranConversationRadio(modele: ModeleApplication) {
    val cle = modele.conversationRadio ?: return
    val conversations by modele.conversationsRadio.collectAsStateWithLifecycle()
    val messages = conversations[cle].orEmpty()
    val pilote = modele.piloteRadio
    val titre = if (cle.startsWith("c:")) pilote?.canaux?.firstOrNull { "c:${it.index}" == cle }?.let { "Canal « ${it.nom} »" } ?: "Canal ${cle.removePrefix("c:")}"
                else modele.nomDuContactRadio(cle.removePrefix("d:"))
    var texte by rememberSaveable(cle) { mutableStateOf("") }
    val defilement = rememberLazyListState()
    LaunchedEffect(messages.size) { if (messages.isNotEmpty()) defilement.animateScrollToItem(messages.size - 1) }
    val heure = SimpleDateFormat("dd/MM HH:mm", Locale.FRANCE)

    Column(Modifier.fillMaxSize().imePadding()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = modele::fermerConversationRadio) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") }
            Column(Modifier.weight(1f)) {
                Text(titre, style = MaterialTheme.typography.titleMedium)
                Text(if (cle.startsWith("c:")) "Tous ceux qui ont ce canal l'entendent" else "Message direct, par la radio",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp), state = defilement, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(messages) { m ->
                Box(Modifier.fillMaxWidth(), contentAlignment = if (m.moi) Alignment.CenterEnd else Alignment.CenterStart) {
                    Column(Modifier.widthIn(max = 300.dp).background(
                        if (m.moi) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp)).padding(10.dp)) {
                        if (!m.moi && m.auteur.isNotBlank()) Text(m.auteur, style = MaterialTheme.typography.labelMedium)
                        Text(m.texte, style = MaterialTheme.typography.bodyMedium)
                        Text(heure.format(Date(m.horodatage)) + if (m.moi && !m.envoye) " · non parti" else "",
                            style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(texte, { texte = it }, label = { Text("Message") }, modifier = Modifier.weight(1f), maxLines = 4)
            IconButton(enabled = texte.isNotBlank(), onClick = { modele.ecrireALaRadio(cle, texte.trim()); texte = "" }) {
                Icon(Icons.AutoMirrored.Filled.Send, "Envoyer")
            }
        }
    }
}
