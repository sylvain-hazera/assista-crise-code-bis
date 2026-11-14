package fr.assistacrise.mobile.ui

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.Photographe
import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.EtatAction
import fr.assistacrise.mobile.domaine.filDuDossier
import java.io.File

/**
 * Un dossier, vu par celui qui est sur place : où c'est, qui appeler, ce qui s'y est dit, et
 * de quoi y ajouter un commentaire ou une photo. Tout ce qu'il ajoute s'écrit d'abord sur le
 * téléphone et part quand le réseau le permet.
 */
@Composable
fun EcranDossier(modele: ModeleApplication) {
    val dossiers by modele.dossiers.collectAsStateWithLifecycle()
    val equipes by modele.equipes.collectAsStateWithLifecycle()
    val compte by modele.compte.collectAsStateWithLifecycle()
    val commentaires by modele.commentaires.collectAsStateWithLifecycle()
    val photos by modele.photos.collectAsStateWithLifecycle()
    val file by modele.file.collectAsStateWithLifecycle()
    val contexte = LocalContext.current
    val d = dossiers.firstOrNull { it.id == modele.dossierOuvert }

    Column(Modifier.fillMaxSize().imePadding()) {
        EnTeteRetour(d?.numero?.ifBlank { null } ?: "Dossier", modele, modele::fermerDossier)
        if (d == null) {
            Text("Ce dossier n'est plus confié à vos équipes.", modifier = Modifier.padding(20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
            return@Column
        }
        val jeDirige = equipes.firstOrNull { it.id == d.equipe }?.estDirigeePar(compte?.id) == true
        val (position, autorise, demanderPosition) = positionDuMoment()
        var texte by rememberSaveable { mutableStateOf("") }
        var legende by rememberSaveable { mutableStateOf("") }
        var prise by remember { mutableStateOf<File?>(null) }
        val appareil = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { reussie ->
            val fichier = prise
            prise = null
            if (reussie && fichier != null) { modele.ajouterPhoto(d, fichier, position, legende); legende = "" } else fichier?.delete()
        }

        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(d.titre.ifBlank { "Dossier ${d.numero}" }, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
                if (d.priorite == "URGENTE" && !d.clos) Text("Urgent", style = MaterialTheme.typography.labelLarge, color = Refus)
            }
            Text(listOfNotNull(d.statutLibelle, d.equipeNom, d.commune, d.criseNom).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            (d.description.ifBlank { d.descriptionOrigine ?: "" }).takeIf { it.isNotBlank() }?.let {
                Spacer(Modifier.height(10.dp)); Text(it, style = MaterialTheme.typography.bodyLarge)
            }
            d.contactNom?.takeIf { it.isNotBlank() }?.let { Spacer(Modifier.height(8.dp)); Text("Sur place : $it", style = MaterialTheme.typography.bodyMedium) }
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                d.contactTelephone?.takeIf { it.isNotBlank() }?.let { numero ->
                    TextButton(onClick = { runCatching { contexte.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:$numero"))) } }) { Text("Appeler") }
                }
                if (d.situe) TextButton(onClick = {
                    runCatching { contexte.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("geo:${d.latitude},${d.longitude}?q=${d.latitude},${d.longitude}"))) }
                }) { Text("Itinéraire") }
                Spacer(Modifier.weight(1f))
                if (jeDirige && !d.clos) {
                    val suivant = if (d.statut == "EN_COURS") "AFFECTE" else "EN_COURS"
                    OutlinedButton(onClick = { modele.definirStatutDossier(d, suivant) }) { Text(if (suivant == "EN_COURS") "Nous y sommes" else "Pas encore commencé") }
                }
            }

            // --- Photos -------------------------------------------------------------------
            SousTitre("Photos")
            val recues = photos[d.id].orEmpty()
            val enAttente = file.filter { it.genre == ActionEnAttente.GENRE_PHOTO && it.cible == d.id }
            if (recues.isEmpty() && enAttente.isEmpty()) {
                Text("Aucune photo pour l'instant.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    recues.forEach { p ->
                        LaunchedEffect(p.id) { modele.chargerVignette(p.id) }
                        Vignette(modele, p.id, listOfNotNull(
                            p.auteur.ifBlank { null },
                            instantDe(p.date)?.let { ilYA(it) },
                            if (p.latitude != null) "située" else "sans position",
                        ).joinToString(" · "), p.commentaire?.takeIf { it.isNotBlank() } ?: p.empreinte?.take(12)?.let { "Empreinte $it…" })
                    }
                    enAttente.forEach { a ->
                        LaunchedEffect(a.id) { modele.chargerVignetteEnAttente(a) }
                        val fiche = modele.photoEnAttente(a)
                        Vignette(
                            modele, a.id,
                            if (a.etat == EtatAction.REFUSEE) "Refusée" else "En attente d'envoi",
                            if (a.etat == EtatAction.REFUSEE) a.erreur else if (fiche?.latitude != null) "Située à ${fiche.precisionM?.toInt() ?: 0} m près" else "Sans position",
                            alerte = true,
                        )
                    }
                }
            }
            Spacer(Modifier.height(10.dp))
            OutlinedTextField(
                value = legende, onValueChange = { legende = it.take(200) }, label = { Text("Légende de la photo (facultatif)") },
                modifier = Modifier.fillMaxWidth(), singleLine = true, keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            )
            Spacer(Modifier.height(6.dp))
            Button(
                onClick = {
                    val (fichier, adresse) = Photographe.nouvellePrise(contexte)
                    prise = fichier
                    runCatching { appareil.launch(adresse) }.onFailure { prise = null; fichier.delete() }
                },
                enabled = !modele.photoEnCours, modifier = Modifier.fillMaxWidth().height(50.dp),
            ) {
                if (modele.photoEnCours) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                else Text("Prendre une photo")
            }
            // Ce que la photo emportera, dit AVANT de la prendre.
            when {
                position != null -> Text(
                    "La photo portera l'heure et votre position (à ${position.precisionM.toInt()} m près). Seule l'équipe du dossier voit cette position.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp),
                )
                !autorise -> Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Sans votre position, la photo partira sans lieu.", style = MaterialTheme.typography.bodySmall, color = Attente, modifier = Modifier.weight(1f))
                    TextButton(onClick = demanderPosition) { Text("Situer mes photos") }
                }
                else -> Text("Recherche de votre position… Une photo prise maintenant partira sans lieu.", style = MaterialTheme.typography.bodySmall, color = Attente, modifier = Modifier.padding(top = 6.dp))
            }

            // --- Commentaires -------------------------------------------------------------
            SousTitre("Commentaires")
            val fil = filDuDossier(commentaires[d.id].orEmpty(), file, d.id, ::instantDe)
            if (fil.isEmpty()) Text("Aucun commentaire pour l'instant.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            fil.forEachIndexed { rang, c ->
                if (rang > 0) HorizontalDivider()
                Column(Modifier.padding(vertical = 8.dp)) {
                    Text(c.texte, style = MaterialTheme.typography.bodyLarge)
                    Text(
                        when {
                            c.refus != null -> "Refusé : ${c.refus}"
                            c.enAttente -> "En attente d'envoi"
                            else -> listOfNotNull(c.auteur.ifBlank { null }, c.instant?.let { ilYA(it) }).joinToString(" · ")
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = when { c.refus != null -> Refus; c.enAttente -> Attente; else -> MaterialTheme.colorScheme.onSurfaceVariant },
                    )
                }
            }
            Spacer(Modifier.height(12.dp))
        }

        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = texte, onValueChange = { texte = it }, placeholder = { Text("Ajouter un commentaire") },
                modifier = Modifier.weight(1f), maxLines = 4, keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = { modele.commenter(d, texte); texte = "" }, enabled = texte.isNotBlank()) { Text("Envoyer") }
        }
    }
}

@Composable
private fun SousTitre(texte: String) {
    Spacer(Modifier.height(22.dp))
    Text(texte, style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun Vignette(modele: ModeleApplication, cle: String, ligne: String, detail: String?, alerte: Boolean = false) {
    Column(Modifier.width(150.dp)) {
        Box(Modifier.size(150.dp, 112.dp).clip(RoundedCornerShape(10.dp)).background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
            val image = modele.vignettes[cle]
            if (image != null) Image(image, contentDescription = "Photo du dossier", contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            else CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
        }
        Text(ligne, style = MaterialTheme.typography.labelMedium, color = if (alerte) Attente else MaterialTheme.colorScheme.onSurface, modifier = Modifier.padding(top = 4.dp))
        detail?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 3) }
    }
}

/** Une ligne de dossier, pour les listes : sous une mission, ou parmi les interventions. */
@Composable
fun LigneDossier(d: Dossier, modifier: Modifier = Modifier) {
    Column(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(d.titre.ifBlank { "Dossier ${d.numero}" }, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            if (d.priorite == "URGENTE" && !d.clos) Text("Urgent", style = MaterialTheme.typography.labelMedium, color = Refus)
        }
        Text(listOfNotNull(d.statutLibelle, d.commune).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
