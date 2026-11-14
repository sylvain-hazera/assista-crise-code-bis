package fr.assistacrise.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.Notification
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

/** L'en-tête des écrans qu'on ouvre depuis un autre : retour, titre, état du lien. */
@Composable
fun EnTeteRetour(titre: String, modele: ModeleApplication, retour: () -> Unit) {
    val lien by modele.lien.collectAsStateWithLifecycle()
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(start = 4.dp, end = 16.dp, top = 8.dp, bottom = 4.dp)) {
        IconButton(onClick = retour) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Retour") }
        Text(titre, style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        PastilleLien(lien)
    }
}

/** « 20 novembre », à partir d'une date du serveur. */
fun jourLisible(iso: String): String =
    runCatching { LocalDate.parse(iso).format(DateTimeFormatter.ofPattern("d MMMM", Locale.FRANCE)) }.getOrDefault(iso)

@Composable
fun EcranNotifications(modele: ModeleApplication) {
    val notifications by modele.notifications.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize()) {
        EnTeteRetour("Notifications", modele) { modele.aller(Ecran.COMPTE) }
        if (notifications.isEmpty()) {
            Text(
                "Rien pour l'instant. Les demandes de disponibilités de votre association arriveront ici, et feront sonner ce téléphone.",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(20.dp),
            )
        } else {
            LazyColumn {
                items(notifications, key = { it.id }) { n ->
                    LigneNotification(n) { modele.ouvrirNotification(n.id) }
                    HorizontalDivider()
                }
            }
        }
    }
}

@Composable
private fun LigneNotification(n: Notification, ouvrir: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = ouvrir).padding(horizontal = 20.dp, vertical = 14.dp), verticalAlignment = Alignment.Top) {
        // Le point dit « pas encore ouverte » ; le mot à droite dit ce qu'on attend de moi.
        Box(Modifier.padding(top = 6.dp).size(9.dp).clip(CircleShape).background(if (n.dateLue == null) BleuClair else MaterialTheme.colorScheme.surface))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(n.titre, style = MaterialTheme.typography.bodyLarge, fontWeight = if (n.dateLue == null) FontWeight.SemiBold else FontWeight.Normal)
            val quand = instantDe(n.dateCreation)?.let { ilYA(it) } ?: ""
            Text(
                listOfNotNull(quand.ifBlank { null }, etatDe(n)).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = if (n.attendUneReponse) Attente else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private fun etatDe(n: Notification): String? = n.campagne?.let { c ->
    when {
        c.aReponduNon -> "Vous avez répondu : pas disponible"
        c.repondu -> "Vous avez répondu : ${c.creneauxDeclares} créneau(x)"
        c.cloturee -> "Demande close"
        else -> "Réponse attendue"
    }
}

@Composable
fun EcranNotification(modele: ModeleApplication) {
    val notifications by modele.notifications.collectAsStateWithLifecycle()
    val n = notifications.firstOrNull { it.id == modele.notificationOuverte }
    Column(Modifier.fillMaxSize()) {
        EnTeteRetour(n?.institutionNom ?: "Notification", modele) { modele.ouvrirNotifications() }
        if (n == null) {
            Text("Cette notification n'est plus disponible.", modifier = Modifier.padding(20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
            return@Column
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp)) {
            Text(n.titre, style = MaterialTheme.typography.headlineSmall)
            n.campagne?.let { c ->
                Spacer(Modifier.height(6.dp))
                Text("Du ${jourLisible(c.debut)} au ${jourLisible(c.fin)}", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary)
            }
            if (n.corps.isNotBlank()) {
                Spacer(Modifier.height(16.dp))
                Text(n.corps, style = MaterialTheme.typography.bodyLarge)
            }
        }
        n.campagne?.let { c ->
            Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) {
                when {
                    c.cloturee -> Text("Cette demande est close : il n'y a plus à y répondre.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    else -> {
                        if (c.repondu) {
                            Text(
                                if (c.aReponduNon) "Vous avez répondu que vous n'êtes pas disponible. Si cela change, donnez vos créneaux."
                                else "Vous avez donné ${c.creneauxDeclares} créneau(x). Vous pouvez encore les modifier.",
                                style = MaterialTheme.typography.bodyMedium, color = EnLigne,
                            )
                            Spacer(Modifier.height(10.dp))
                        }
                        Button(onClick = { modele.ouvrirDisponibilites(c.id) }, modifier = Modifier.fillMaxWidth().height(50.dp)) {
                            Text(if (c.repondu) "Modifier mes créneaux" else "Je donne mes créneaux")
                        }
                        if (!c.repondu) {
                            Spacer(Modifier.height(8.dp))
                            // Un « non » est une réponse : il évite d'être relancé, et l'encadrement sait sur qui compter.
                            OutlinedButton(onClick = { modele.repondreNon(n) }, enabled = !modele.chargement, modifier = Modifier.fillMaxWidth().height(50.dp)) {
                                Text("Je ne suis pas disponible")
                            }
                        }
                    }
                }
            }
        }
    }
}
