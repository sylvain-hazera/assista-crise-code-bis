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
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.Badge
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.LiaisonRadio
import fr.assistacrise.mobile.MessagerieRadio
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
    val etats by modele.radios.collectAsStateWithLifecycle()
    val etat by modele.radio.collectAsStateWithLifecycle()
    val avance by modele.radioAvance.collectAsStateWithLifecycle()
    val conversations by modele.conversationsRadio.collectAsStateWithLifecycle()
    val nonLus by modele.nonLusRadio.collectAsStateWithLifecycle()
    val mentions by modele.mentionsRadio.collectAsStateWithLifecycle()
    var onglet by rememberSaveable { mutableStateOf(0) }
    var recherche by rememberSaveable { mutableStateOf("") }
    // Toute radio connectée, plus seulement en mode avancé (23/11/2026) : ses canaux sont des
    // moyens de conversation comme les autres. Le mode avancé garde les réglages.
    if (etats.none { it.phase == LiaisonRadio.Phase.PRETE }) return
    if (etat.phase != LiaisonRadio.Phase.PRETE) {
        etats.firstOrNull { it.phase == LiaisonRadio.Phase.PRETE }?.protocole?.let { p -> LaunchedEffect(p) { modele.choisirRadio(p) } }
        return
    }
    val pilote = modele.piloteRadio ?: return
    val pr = pilote.protocole
    fun k(reste: String) = MessagerieRadio.cle(pr, reste)

    val canaux = pilote.canaux.map { c ->
        Entree(k("c:${c.index}"), c.nom, modele.equipeDuCanalRadio(c.index)?.let { "Canal ${c.index} · canal de l'équipe ${it.nom}" } ?: "Canal ${c.index}")
    }
    val contacts = when (pilote) {
        is PiloteMeshtastic -> avance.noeuds.values.filter { it.numero != avance.monNoeud }.sortedByDescending { it.dernierContact ?: 0 }
            .map { Entree(k("d:${it.identifiant}"), it.nomLong.ifBlank { it.identifiant }, listOfNotNull(it.nomCourt.takeIf { s -> s.isNotBlank() }, it.identifiant, it.sauts?.let { s -> "$s saut(s)" }).joinToString(" · ")) }
        is PiloteMeshCore -> avance.contacts.values.sortedByDescending { it.derniereAnnonce }
            .map { Entree(k("d:${it.pubkeyHex.take(12)}"), it.nom.ifBlank { it.pubkeyHex.take(12) }, "${it.genre} · ${it.libelleChemin}") }
        else -> emptyList()
    }
    // Les conversations directes avec quelqu'un qui n'est plus dans la liste restent ouvrables.
    val orphelines = conversations.keys.filter { it.startsWith(k("d:")) && contacts.none { c -> c.cle == it } }
        .map { Entree(it, modele.nomDuContactRadio(it), "Conversation") }

    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Text("Radio ${etat.protocole?.libelle ?: ""} · ${etat.nom ?: ""}", style = MaterialTheme.typography.titleMedium)
            // Le moyen (Meshtastic, MeshCore), avec ses non-lus et ses mentions ; deux radios sur
            // le téléphone : on choisit celle qu'on regarde.
            val pretes = etats.filter { it.phase == LiaisonRadio.Phase.PRETE }
            Row(Modifier.padding(vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                pretes.forEach { e ->
                    val p = e.protocole ?: return@forEach
                    val nonLu = nonLus.filterKeys { it.startsWith(p.name + "|") }.values.sum()
                    val mention = mentions.filterKeys { it.startsWith(p.name + "|") }.values.sum()
                    FilterChip(selected = p == pr, onClick = { modele.choisirRadio(p) },
                        label = { Text(p.libelle) }, trailingIcon = { PastilleNonLus(nonLu, mention) })
                }
            }
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
                    PastilleNonLus(nonLus[e.cle] ?: 0, mentions[e.cle] ?: 0)
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
    val (protocole, reste) = MessagerieRadio.lireCle(cle) ?: return
    val canal = reste.startsWith("c:")
    val pilote = modele.piloteDe(protocole)
    val titre = if (canal) pilote?.canaux?.firstOrNull { "c:${it.index}" == reste }?.let { "Canal « ${it.nom} »" } ?: "Canal ${reste.removePrefix("c:")}"
                else modele.nomDuContactRadio(cle)
    var texte by rememberSaveable(cle) { mutableStateOf("") }
    var repondreA by androidx.compose.runtime.remember(cle) { mutableStateOf<fr.assistacrise.mobile.domaine.MessageConversationRadio?>(null) }
    val defilement = rememberLazyListState()
    LaunchedEffect(messages.size) { if (messages.isNotEmpty()) defilement.animateScrollToItem(messages.size - 1) }
    val heure = SimpleDateFormat("dd/MM HH:mm", Locale.FRANCE)

    Column(Modifier.fillMaxSize().imePadding()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = modele::fermerConversationRadio) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") }
            Column(Modifier.weight(1f)) {
                Text(titre, style = MaterialTheme.typography.titleMedium)
                Text("${protocole.libelle} · " + if (canal) "tous ceux qui ont ce canal l'entendent" else "message direct, par la radio",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            // Un canal sonne si on le demande (les messages directs sonnent toujours).
            if (canal) {
                var sonne by rememberSaveable(cle) { mutableStateOf(modele.canalRadioNotifie(cle)) }
                IconButton(onClick = { sonne = !sonne; modele.notifierCanalRadio(cle, sonne) }) {
                    // Seule l'icône « cloche » est dans la bibliothèque de base : barrée = estompée.
                    Icon(Icons.Filled.Notifications, if (sonne) "Ne plus notifier ce canal" else "Notifier les messages de ce canal",
                        tint = if (sonne) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.35f))
                }
            }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp), state = defilement, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(messages) { m ->
                Box(Modifier.fillMaxWidth(), contentAlignment = if (m.moi) Alignment.CenterEnd else Alignment.CenterStart) {
                  AvecMenuMessage(m.auteur, m.texte, m.moi, { repondreA = m }, { texte = taguer(texte, m.auteur) },
                      surReagir = if (modele.reactionRadioPossible(cle, m)) { e -> modele.reagirALaRadio(cle, m, e) } else null) {
                    Column(Modifier.widthIn(max = 300.dp).background(
                        if (m.moi) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp)).padding(10.dp)) {
                        if (!m.moi && m.auteur.isNotBlank()) Text(m.auteur, style = MaterialTheme.typography.labelMedium)
                        // Réponse native (Meshtastic reply_id) : le message visé, en bref.
                        m.repondA.takeIf { it != 0L }?.let { id -> messages.lastOrNull { it.idRadio == id } }?.let { v ->
                            Text("↪ ${if (v.moi) "Moi" else v.auteur} : ${v.texte.take(40)}${if (v.texte.length > 40) "…" else ""}",
                                style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        // Un marqueur (format MeshCore SAR) se lit en clair ; il est aussi sur la carte.
                        val marqueur = fr.assistacrise.mobile.domaine.MarqueursRadio.lire(m.texte)
                        if (marqueur != null) {
                            Text("📍 ${marqueur.emoji} ${fr.assistacrise.mobile.domaine.MarqueursRadio.libelle(marqueur.emoji)}" + (marqueur.note?.let { " · $it" } ?: ""),
                                style = MaterialTheme.typography.bodyMedium)
                            Text("Marqueur sur la carte · ${"%.5f".format(java.util.Locale.ROOT, marqueur.latitude)}, ${"%.5f".format(java.util.Locale.ROOT, marqueur.longitude)}",
                                style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        } else Text(m.texte, style = MaterialTheme.typography.bodyMedium)
                        if (m.reactions.isNotEmpty()) {
                            Text(m.reactions.entries.joinToString("  ") { (e, qui) -> if (qui.size > 1) "$e ${qui.size}" else e },
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.semantics { contentDescription = m.reactions.entries.joinToString(" ; ") { (e, qui) -> "$e : ${qui.joinToString(", ")}" } })
                        }
                        // Reçu : sauts et signal (comme les applications officielles) ; envoyé : ce qu'il est devenu.
                        val etat = if (m.moi) when {
                            !m.envoye -> "non parti"
                            m.statut == fr.assistacrise.mobile.domaine.StatutEnvoiRadio.RECU ->
                                fr.assistacrise.mobile.domaine.StatutEnvoiRadio.RECU.libelle + (m.delaiMs?.let { " en ${"%.1f".format(it / 1000.0)} s" } ?: "")
                            m.statut == fr.assistacrise.mobile.domaine.StatutEnvoiRadio.PARTI && m.idRadio != 0L -> "envoyé, accusé attendu"
                            else -> m.statut?.libelle ?: ""
                        } else m.reception()
                        Text(listOf(heure.format(Date(m.horodatage)), etat).filter { it.isNotBlank() }.joinToString(" · "),
                            style = MaterialTheme.typography.labelSmall,
                            color = if (m.statut == fr.assistacrise.mobile.domaine.StatutEnvoiRadio.ECHEC) MaterialTheme.colorScheme.error
                                    else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                  }
                }
            }
        }
        repondreA?.let { r -> BandeauReponse(if (r.moi) "" else r.auteur, r.texte) { repondreA = null } }
        // Taille d'un message radio (26/11/2026) : au-delà, il part en plusieurs morceaux.
        val aEnvoyer = repondreA?.let { r -> fr.assistacrise.mobile.domaine.Mentions.reponseRadio(if (r.moi) "" else r.auteur, texte) } ?: texte.trim()
        val limite = if (protocole == fr.assistacrise.mobile.lien.Protocole.MESHCORE) (if (canal) 133 - ((pilote?.identite?.length ?: 10) + 2) else 150) else 200
        val octets = aEnvoyer.encodeToByteArray().size
        if (texte.isNotBlank()) {
            Text("$octets / $limite octets" + if (octets > limite) " · partira en ${(octets + limite - 1) / limite} messages" else "",
                Modifier.padding(horizontal = 12.dp), style = MaterialTheme.typography.labelSmall,
                color = if (octets > limite) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(texte, { texte = it }, label = { Text("Message") }, modifier = Modifier.weight(1f), maxLines = 4)
            IconButton(enabled = texte.isNotBlank(), onClick = {
                // Réponse à la manière des applications MeshCore : « @[Nom] texte » ; en Meshtastic,
                // la réponse native (reply_id) part en plus.
                modele.ecrireALaRadio(cle, aEnvoyer, repondreA?.idRadio ?: 0)
                texte = ""; repondreA = null
            }) {
                Icon(Icons.AutoMirrored.Filled.Send, "Envoyer")
            }
        }
    }
}
