package fr.assistacrise.mobile.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.BuildConfig
import fr.assistacrise.mobile.domaine.MiseAJourProposee
import fr.assistacrise.mobile.domaine.UrgenceMiseAJour

/**
 * « Votre application doit être mise à jour » (20/11/2026). Toujours refermable : une
 * application de crise doit rester utilisable, même pas à jour, même sans réseau.
 */
@Composable
fun DialogueMiseAJour(proposee: MiseAJourProposee, onMettreAJour: () -> Unit, onPlusTard: () -> Unit) {
    val obligatoire = proposee.urgence == UrgenceMiseAJour.OBLIGATOIRE
    AlertDialog(
        onDismissRequest = onPlusTard,
        title = {
            Text(if (obligatoire) "Votre application ${BuildConfig.NOM_MARQUE_AFFICHE} doit être mise à jour"
                 else "Une mise à jour est disponible")
        },
        text = {
            Column {
                Text("La version ${proposee.versionPubliee} est publiée ; vous avez la version ${BuildConfig.VERSION_NAME}.")
                Text(
                    if (obligatoire) "Cette version-ci n'est plus prise en charge : certaines fonctions pourraient ne plus marcher avec le serveur."
                    else "Elle apporte des corrections et des nouveautés.",
                    modifier = Modifier.padding(top = 8.dp),
                )
                Text(
                    "Le téléchargement s'ouvre dans le navigateur ; à la fin, touchez le fichier pour l'installer. " +
                        "Vos données restent sur le téléphone. Android peut demander d'autoriser l'installation depuis le navigateur.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
        },
        confirmButton = { Button(onClick = onMettreAJour) { Text("Mettre à jour") } },
        dismissButton = { TextButton(onClick = onPlusTard) { Text(if (obligatoire) "Dans une heure" else "Plus tard") } },
    )
}
