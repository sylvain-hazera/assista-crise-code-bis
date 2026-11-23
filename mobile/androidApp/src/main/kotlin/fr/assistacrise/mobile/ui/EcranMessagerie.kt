package fr.assistacrise.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.MessageAffiche
import fr.assistacrise.mobile.domaine.filDeMessages
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun EcranMessagerie(modele: ModeleApplication) {
    val equipes by modele.equipes.collectAsStateWithLifecycle()
    val fils by modele.fils.collectAsStateWithLifecycle()
    val file by modele.file.collectAsStateWithLifecycle()
    val lien by modele.lien.collectAsStateWithLifecycle()
    val equipe = equipes.firstOrNull { it.id == modele.equipeOuverte }
    if (equipe == null) { LaunchedEffect(Unit) { modele.aller(Ecran.EQUIPES) }; return }

    val messages = filDeMessages(fils[equipe.id] ?: emptyList(), file, equipe.id)
    // Ce qui arrive pendant qu'on lit est lu.
    LaunchedEffect(equipe.id, fils[equipe.id]?.size) { modele.marquerEquipeLue(equipe.id) }
    val liste = rememberLazyListState()
    var brouillon by rememberSaveable { mutableStateOf("") }

    // Le fil est relu tant que l'écran est affiché ; il s'arrête dès qu'on le quitte.
    LaunchedEffect(equipe.id) {
        while (true) { modele.relireLeFil(); delay(8_000) }
    }
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) liste.scrollToItem(messages.lastIndex)
    }

    Column(Modifier.fillMaxSize().imePadding()) {
        Row(Modifier.fillMaxWidth().padding(start = 4.dp, end = 16.dp, top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { modele.aller(Ecran.EQUIPES) }) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Retour aux équipes")
            }
            Column(Modifier.weight(1f)) {
                Text(equipe.nom, style = MaterialTheme.typography.titleLarge)
                Text("Messagerie de l'équipe", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            PastilleLien(lien)
        }

        if (messages.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                Text("Aucun message pour l'instant.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            LazyColumn(
                Modifier.weight(1f).fillMaxWidth(), state = liste,
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(messages, key = { it.cle }) { Bulle(it) }
            }
        }

        Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp, bottom = 8.dp, top = 4.dp), verticalAlignment = Alignment.Bottom) {
            OutlinedTextField(
                value = brouillon, onValueChange = { brouillon = it },
                placeholder = { Text("Écrire à l'équipe") },
                modifier = Modifier.weight(1f), maxLines = 4,
            )
            IconButton(onClick = { modele.ecrire(equipe, brouillon); brouillon = "" }, enabled = brouillon.isNotBlank()) {
                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Envoyer")
            }
        }
    }
}

@Composable
private fun Bulle(m: MessageAffiche) {
    val fond = when {
        m.refus != null -> Refus.copy(alpha = 0.12f)
        m.moi -> MaterialTheme.colorScheme.primaryContainer
        else -> MaterialTheme.colorScheme.surfaceVariant
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (m.moi) Arrangement.End else Arrangement.Start) {
        Column(
            Modifier.widthIn(max = 300.dp).background(fond, RoundedCornerShape(14.dp)).padding(horizontal = 12.dp, vertical = 8.dp),
        ) {
            if (!m.moi && m.auteur.isNotBlank()) {
                Text(m.auteur, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            }
            Text(m.texte, style = MaterialTheme.typography.bodyLarge)
            // L'état est dit en mots : « en attente » n'est pas « envoyé ».
            val etat = when {
                m.refus != null -> "Non envoyé : ${m.refus}"
                // Parti par la radio pendant une coupure : les coéquipiers l'ont, le serveur pas encore.
                m.enAttente && m.parRadio -> "Parti par radio · en attente du réseau"
                m.enAttente -> "En attente d'envoi"
                else -> listOfNotNull(heure(m.horodatage), "par radio".takeIf { m.parRadio }, "urgent".takeIf { m.urgent }).joinToString(" · ")
            }
            Text(
                etat, style = MaterialTheme.typography.labelSmall,
                color = when { m.refus != null -> Refus; m.enAttente -> Attente; else -> MaterialTheme.colorScheme.onSurfaceVariant },
            )
        }
    }
}

private fun heure(instant: Long): String = SimpleDateFormat("HH:mm", Locale.FRANCE).format(Date(instant))
