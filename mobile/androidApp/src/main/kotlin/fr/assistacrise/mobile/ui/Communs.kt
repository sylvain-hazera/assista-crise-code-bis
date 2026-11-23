package fr.assistacrise.mobile.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Place
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.R
import fr.assistacrise.mobile.domaine.EtatLien

/** Le logo, toujours sur un disque blanc : il est dessiné pour un fond clair. */
@Composable
fun Logo(taille: Dp, modifier: Modifier = Modifier) {
    Box(modifier.size(taille).clip(CircleShape).background(Color.White), contentAlignment = Alignment.Center) {
        Image(
            painter = painterResource(R.drawable.logo),
            contentDescription = stringResource(R.string.nom_application),
            modifier = Modifier.size(taille * 0.94f),
        )
    }
}

/** Un champ de saisie avec son erreur dessous — la seule façon d'afficher une erreur de champ. */
@Composable
fun Champ(
    valeur: String,
    surChangement: (String) -> Unit,
    libelle: String,
    modifier: Modifier = Modifier,
    erreur: String? = null,
    aide: String? = null,
    clavier: KeyboardOptions = KeyboardOptions.Default,
    transformation: VisualTransformation = VisualTransformation.None,
    actif: Boolean = true,
    fin: @Composable (() -> Unit)? = null,
) {
    OutlinedTextField(
        value = valeur,
        onValueChange = surChangement,
        label = { Text(libelle) },
        modifier = modifier,
        singleLine = true,
        enabled = actif,
        isError = erreur != null,
        supportingText = (erreur ?: aide)?.let { texte -> { Text(texte) } },
        keyboardOptions = clavier,
        visualTransformation = transformation,
        trailingIcon = fin,
    )
}

/**
 * L'état du lien, affiché en permanence (dossier § 4) : par où part ce que je déclare,
 * maintenant ? Une pastille et un mot — jamais la couleur seule.
 */
@Composable
fun PastilleLien(etat: EtatLien, modifier: Modifier = Modifier) {
    val (couleur, mot) = when (etat) {
        EtatLien.INTERNET -> EnLigne to "En ligne"
        EtatLien.MESH -> Attente to "Radio"
        EtatLien.AUCUN -> Refus to "Hors ligne"
    }
    Row(
        modifier
            .clip(RoundedCornerShape(50))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(9.dp).clip(CircleShape).background(couleur))
        Spacer(Modifier.width(6.dp))
        Text(mot, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** La barre du bas. Un citoyen n'y voit que ce qui le concerne : l'aide et son compte. */
@Composable
fun BarreDuBas(ecran: fr.assistacrise.mobile.Ecran, intervenant: Boolean, nonVues: Int, aller: (fr.assistacrise.mobile.Ecran) -> Unit,
               messages: Int = 0, mentions: Int = 0) {
    val lieux = buildList {
        if (intervenant) {
            add(Triple(fr.assistacrise.mobile.Ecran.MISSIONS, "Missions", Icons.AutoMirrored.Filled.List))
            add(Triple(fr.assistacrise.mobile.Ecran.EQUIPES, "Équipes", Icons.Filled.Email))
            add(Triple(fr.assistacrise.mobile.Ecran.CARTE, "Carte", Icons.Filled.Place))
        }
        add(Triple(fr.assistacrise.mobile.Ecran.AIDE, "Aide", Icons.Filled.Info))
        add(Triple(fr.assistacrise.mobile.Ecran.COMPTE, "Compte", Icons.Filled.AccountCircle))
    }
    NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
        lieux.forEach { (lieu, nom, icone) ->
            NavigationBarItem(
                selected = ecran == lieu,
                onClick = { aller(lieu) },
                icon = {
                    // La pastille est sur « Compte » : c'est là que s'ouvrent les notifications.
                    if (lieu == fr.assistacrise.mobile.Ecran.COMPTE && nonVues > 0) {
                        BadgedBox(badge = { Badge { Text("$nonVues") } }) { Icon(icone, contentDescription = "$nonVues notification(s) non vue(s)") }
                    } else if (lieu == fr.assistacrise.mobile.Ecran.EQUIPES && messages > 0) {
                        // L'enveloppe (23/11/2026) : messages non lus, en rouge avec « @ » si l'on m'a mentionné.
                        BadgedBox(badge = { PastilleNonLus(messages, mentions) }) {
                            Icon(icone, contentDescription = "$messages message(s) non lu(s)" + if (mentions > 0) ", dont $mentions mention(s)" else "")
                        }
                    } else Icon(icone, contentDescription = null)
                },
                label = { Text(nom) },
            )
        }
    }
}

/** Une pastille de non-lus : bleue, rouge avec « @ » quand on m'a mentionné (23/11/2026). */
@Composable
fun PastilleNonLus(messages: Int, mentions: Int) {
    if (messages <= 0 && mentions <= 0) return
    Badge(
        containerColor = if (mentions > 0) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
        contentColor = if (mentions > 0) MaterialTheme.colorScheme.onError else MaterialTheme.colorScheme.onPrimary,
    ) { Text(if (mentions > 0) "@ $messages" else "$messages") }
}

/** « il y a 12 min », à partir d'un instant en millisecondes. */
fun ilYA(instant: Long, maintenant: Long = System.currentTimeMillis()): String {
    val minutes = ((maintenant - instant) / 60_000).coerceAtLeast(0)
    return when {
        minutes < 1 -> "à l'instant"
        minutes < 60 -> "il y a $minutes min"
        minutes < 24 * 60 -> "il y a ${minutes / 60} h"
        else -> "il y a ${minutes / (24 * 60)} j"
    }
}

/** Instant d'une date ISO du serveur, ou `null` si elle est illisible. */
fun instantDe(iso: String?): Long? =
    iso?.let { runCatching { java.time.OffsetDateTime.parse(it).toInstant().toEpochMilli() }.getOrNull() }

/** « 12 min », « 2 h » : une durée écoulée depuis un instant, pour une phrase en « depuis ». */
fun duree(instant: Long, maintenant: Long = System.currentTimeMillis()): String {
    val minutes = ((maintenant - instant) / 60_000).coerceAtLeast(0)
    return when {
        minutes < 1 -> "moins d'une minute"
        minutes < 60 -> "$minutes min"
        else -> "${minutes / 60} h ${minutes % 60} min"
    }
}
