package fr.assistacrise.mobile.ui

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.BuildConfig
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.Photographe
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.Profil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * « Mon compte », comme sur le site : qui je suis, comment je me connecte, mes documents.
 * Tout ici exige le serveur — on ne change pas un mot de passe « plus tard », et une pièce
 * d'identité n'attend pas sur un téléphone.
 */
@Composable
fun EcranMonCompte(modele: ModeleApplication, compte: Compte) {
    Column(Modifier.fillMaxSize().imePadding()) {
        EnTeteRetour("Mon compte", modele) { modele.aller(Ecran.COMPTE) }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 32.dp)) {
            if (modele.horsLigne) Text("Pas de réseau : rien ne peut être modifié pour l'instant.", style = MaterialTheme.typography.bodySmall, color = Attente)
            Identite(modele, compte)
            Connexion(modele, compte)
            Documents(modele)
        }
    }
}

@Composable
private fun Section(titre: String) {
    Spacer(Modifier.height(26.dp))
    Text(titre, style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(6.dp))
}

@Composable
private fun Identite(modele: ModeleApplication, compte: Compte) {
    // `key` sur le compte : après enregistrement, la saisie repart de ce que le serveur a gardé.
    androidx.compose.runtime.key(compte) {
        var prenom by rememberSaveable { mutableStateOf(compte.prenom) }
        var nom by rememberSaveable { mutableStateOf(compte.nom) }
        var telephone by rememberSaveable { mutableStateOf(compte.telephone ?: "") }
        val etat = modele.formulaireProfil
        Section("Mon identité")
        Champ(prenom, { prenom = it }, "Prénom", Modifier.fillMaxWidth(), erreur = etat.champs["first_name"])
        Champ(nom, { nom = it }, "Nom", Modifier.fillMaxWidth(), erreur = etat.champs["last_name"])
        Champ(telephone, { telephone = it }, "Téléphone", Modifier.fillMaxWidth(), erreur = etat.champs["phone_number"], clavier = KeyboardOptions(keyboardType = KeyboardType.Phone))
        etat.erreur?.let { Text(it, color = Refus, style = MaterialTheme.typography.bodyMedium) }
        Button(onClick = { modele.enregistrerProfil(Profil(prenom, nom, telephone)) }, enabled = !etat.enCours, modifier = Modifier.fillMaxWidth().height(50.dp)) {
            Text(if (etat.enCours) "Enregistrement…" else "Enregistrer")
        }
    }
}

@Composable
private fun Connexion(modele: ModeleApplication, compte: Compte) {
    val fiche by modele.fiche.collectAsStateWithLifecycle()
    // Un compte créé par import n'a pas de mot de passe : il en choisit un, sans « ancien » à fournir.
    val aUnMotDePasse = fiche?.motDePasseDefini ?: true
    var ancien by remember { mutableStateOf("") }
    var nouveau by remember { mutableStateOf("") }
    var confirmation by remember { mutableStateOf("") }
    val etat = modele.formulaireMotDePasse

    Section("Ma connexion")
    Text("Identifiant", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Text(compte.email, style = MaterialTheme.typography.bodyLarge)
    Text(
        "C'est avec cette adresse que vous vous connectez. Pour la changer, passez par le site : elle doit être revérifiée.",
        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.height(12.dp))
    Text(if (aUnMotDePasse) "Changer de mot de passe" else "Choisir un mot de passe", style = MaterialTheme.typography.titleSmall)
    if (!aUnMotDePasse) Text("Votre compte n'en a pas encore : vous vous connectez par le lien reçu par e-mail, qui continuera de fonctionner.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    if (aUnMotDePasse) Champ(ancien, { ancien = it }, "Mot de passe actuel", Modifier.fillMaxWidth(), erreur = etat.champs["old_password"], transformation = PasswordVisualTransformation(), clavier = KeyboardOptions(keyboardType = KeyboardType.Password))
    Champ(nouveau, { nouveau = it }, "Nouveau mot de passe", Modifier.fillMaxWidth(), erreur = etat.champs["new_password"] ?: etat.champs["nouveau_mot_de_passe"], aide = "Au moins 8 caractères", transformation = PasswordVisualTransformation(), clavier = KeyboardOptions(keyboardType = KeyboardType.Password))
    Champ(confirmation, { confirmation = it }, "Le même, une seconde fois", Modifier.fillMaxWidth(), erreur = etat.champs["confirmation"], transformation = PasswordVisualTransformation(), clavier = KeyboardOptions(keyboardType = KeyboardType.Password))
    etat.erreur?.let { Text(it, color = Refus, style = MaterialTheme.typography.bodyMedium) }
    OutlinedButton(
        onClick = { modele.changerMotDePasse(if (aUnMotDePasse) ancien else null, nouveau, confirmation) { ancien = ""; nouveau = ""; confirmation = "" } },
        enabled = !etat.enCours, modifier = Modifier.fillMaxWidth().height(50.dp),
    ) { Text(if (etat.enCours) "Enregistrement…" else "Enregistrer le mot de passe") }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Documents(modele: ModeleApplication) {
    val titres by modele.titres.collectAsStateWithLifecycle()
    val catalogue by modele.catalogue.collectAsStateWithLifecycle()
    val contexte = LocalContext.current
    val portee = rememberCoroutineScope()
    var choisi by rememberSaveable { mutableStateOf<String?>(null) }
    var dateObtention by rememberSaveable { mutableStateOf("") }
    var prise by remember { mutableStateOf<File?>(null) }
    val etat = modele.depotDocument
    val envoyer = { octets: ByteArray, nom: String, type: String ->
        choisi?.let { id -> modele.deposerDocument(id, octets, nom, type, dateObtention.takeIf { it.isNotBlank() }) { choisi = null; dateObtention = "" } }
    }
    val appareil = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { reussie ->
        val fichier = prise
        prise = null
        if (reussie && fichier != null) portee.launch {
            // Réduite et sans position : c'est un document, pas un constat. Le fichier du cache est effacé aussitôt.
            Photographe.preparer(fichier, null, "", BuildConfig.VERSION_NAME)?.let { envoyer(it.first, "document.jpg", "image/jpeg") }
        } else fichier?.delete()
    }
    val fichiers = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { adresse: Uri? ->
        if (adresse != null) portee.launch {
            val lu = withContext(Dispatchers.IO) {
                runCatching {
                    val nom = contexte.contentResolver.query(adresse, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c -> if (c.moveToFirst()) c.getString(0) else null } ?: "document"
                    val type = contexte.contentResolver.getType(adresse) ?: "application/octet-stream"
                    Triple(contexte.contentResolver.openInputStream(adresse)!!.use { it.readBytes() }, nom, type)
                }.getOrNull()
            }
            if (lu != null) envoyer(lu.first, lu.second, lu.third)
        }
    }

    Section("Mes documents")
    if (titres.isEmpty()) Text("Aucun document déposé pour l'instant.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    titres.forEachIndexed { rang, t ->
        if (rang > 0) HorizontalDivider()
        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
            Column(Modifier.weight(1f)) {
                Text(t.nom ?: "Document", style = MaterialTheme.typography.bodyLarge)
                Text(
                    listOfNotNull(
                        t.statutLibelle ?: t.statut,
                        // Un refus sans son motif ferait redéposer la même pièce.
                        t.motifRefus?.takeIf { t.refuse && it.isNotBlank() },
                        if (t.expiree) "périmé" else t.expiration?.let { "valable jusqu'au ${jourLisible(it)}" },
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = when { t.refuse || t.expiree -> Refus; t.verifie -> EnLigne; else -> Attente },
                )
            }
            if (t.refuse && t.qualification != null) TextButton(onClick = { choisi = t.qualification }) { Text("Redéposer") }
        }
    }

    Spacer(Modifier.height(14.dp))
    Text("Déposer un document", style = MaterialTheme.typography.titleSmall)
    if (catalogue.isEmpty()) {
        Text("La liste des documents attendus n'a pas pu être chargée.", style = MaterialTheme.typography.bodySmall, color = Attente)
        return
    }
    Text("Lequel ?", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        catalogue.forEach { c -> FilterChip(selected = choisi == c.id, onClick = { choisi = if (choisi == c.id) null else c.id }, label = { Text(c.nom) }) }
    }
    val titre = catalogue.firstOrNull { it.id == choisi } ?: return
    // Ce que deviendra la pièce, dit AVANT de la déposer : l'apprendre après n'est pas un choix.
    titre.conservation?.let { Text(it.phrase, style = MaterialTheme.typography.bodyMedium, color = if (it.detruiteApresVerification) EnLigne else MaterialTheme.colorScheme.onSurface, modifier = Modifier.padding(top = 6.dp)) }
    if (titres.none { it.qualification == titre.id }) {
        Champ(dateObtention, { dateObtention = it.take(10) }, "Date d'obtention (facultatif)", Modifier.fillMaxWidth(), erreur = etat.champs["date_obtention"], aide = "Année-mois-jour, par exemple 2022-06-15")
    }
    etat.erreur?.let { Text(it, color = Refus, style = MaterialTheme.typography.bodyMedium) }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 6.dp)) {
        Button(
            onClick = {
                val (fichier, adresse) = Photographe.nouvellePrise(contexte)
                prise = fichier
                runCatching { appareil.launch(adresse) }.onFailure { prise = null; fichier.delete() }
            },
            enabled = !etat.enCours, modifier = Modifier.weight(1f),
        ) { Text(if (etat.enCours) "Envoi…" else "Photographier") }
        OutlinedButton(onClick = { fichiers.launch(arrayOf("image/*", "application/pdf")) }, enabled = !etat.enCours, modifier = Modifier.weight(1f)) { Text("Choisir un fichier") }
    }
    Text("Le document part tout de suite, ou pas du tout : rien n'en est gardé sur ce téléphone.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
}
