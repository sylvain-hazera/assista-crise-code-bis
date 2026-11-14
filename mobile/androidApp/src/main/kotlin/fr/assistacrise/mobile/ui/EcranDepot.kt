package fr.assistacrise.mobile.ui

import android.Manifest
import android.annotation.SuppressLint
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.ServiceSuivi
import fr.assistacrise.mobile.domaine.ChampsDepot
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.Declarant
import fr.assistacrise.mobile.domaine.Deposant
import fr.assistacrise.mobile.domaine.Depot
import fr.assistacrise.mobile.domaine.GenreDepot
import fr.assistacrise.mobile.domaine.Releve
import fr.assistacrise.mobile.domaine.Situation

/** Le formulaire des trois gestes citoyens. Il se remplit et s'enregistre sans réseau. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EcranDepot(modele: ModeleApplication, compte: Compte) {
    val ouvert = modele.depotOuvert
    if (ouvert == null) { LaunchedEffect(Unit) { modele.fermerDepot() }; return }
    val (genre, crise) = ouvert
    val etat = modele.depot
    val typesDemande by modele.typesDemande.collectAsStateWithLifecycle()
    val typesInformation by modele.typesInformation.collectAsStateWithLifecycle()
    val typesOffre by modele.typesOffre.collectAsStateWithLifecycle()
    val types = when (genre) { GenreDepot.DEMANDE -> typesDemande; GenreDepot.OFFRE -> typesOffre; else -> typesInformation }

    var prenom by rememberSaveable { mutableStateOf(compte.prenom) }
    var nom by rememberSaveable { mutableStateOf(compte.nom) }
    var email by rememberSaveable { mutableStateOf(compte.email) }
    var telephone by rememberSaveable { mutableStateOf(compte.telephone ?: "") }
    var titre by rememberSaveable { mutableStateOf("") }
    var description by rememberSaveable { mutableStateOf("") }
    var idType by rememberSaveable { mutableStateOf<String?>(null) }
    var situation by rememberSaveable { mutableStateOf(Situation.RELOGE) }
    var declarant by rememberSaveable { mutableStateOf(Declarant.PERSONNE_SEULE) }
    var adultes by rememberSaveable { mutableStateOf("1") }
    var enfants by rememberSaveable { mutableStateOf("0") }
    val (positionLue, autorise, demanderPosition) = positionDuMoment()
    // Un lieu touché sur la carte l'emporte : c'est là que ça se passe, pas là où je me tiens.
    val lieu = modele.lieuChoisi
    val position = lieu ?: positionLue

    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(bottom = 32.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 4.dp, top = 4.dp)) {
            IconButton(onClick = { modele.fermerDepot() }) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Retour")
            }
            Column {
                Text(genre.titre, style = MaterialTheme.typography.titleLarge)
                Text(crise.nom, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }

        Column(Modifier.padding(horizontal = 24.dp).widthIn(max = 480.dp).fillMaxWidth()) {
            Spacer(Modifier.height(8.dp))
            when (genre) {
                GenreDepot.SECURITE -> {
                    Titre("Votre situation")
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Situation.entries.forEach { s -> FilterChip(selected = situation == s, onClick = { situation = s }, label = { Text(s.libelle) }) }
                    }
                    Titre("Vous déclarez pour")
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Declarant.entries.forEach { d -> FilterChip(selected = declarant == d, onClick = { declarant = d }, label = { Text(d.libelle) }) }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.padding(top = 8.dp)) {
                        Champ(adultes, { adultes = it.filter(Char::isDigit).take(3) }, "Adultes", Modifier.weight(1f),
                            erreur = etat.champs[ChampsDepot.PERSONNES], clavier = KeyboardOptions(keyboardType = KeyboardType.Number))
                        Champ(enfants, { enfants = it.filter(Char::isDigit).take(3) }, "Enfants", Modifier.weight(1f),
                            clavier = KeyboardOptions(keyboardType = KeyboardType.Number))
                    }
                }
                GenreDepot.DEMANDE, GenreDepot.SIGNALEMENT, GenreDepot.OFFRE -> {
                    Titre(when (genre) { GenreDepot.DEMANDE -> "De quoi avez-vous besoin ?"; GenreDepot.OFFRE -> "Que proposez-vous ?"; else -> "Que signalez-vous ?" })
                    if (types.isEmpty()) {
                        Text("La liste des types n'a pas encore pu être chargée. Elle le sera au prochain passage en ligne.", style = MaterialTheme.typography.bodySmall, color = Attente)
                    } else {
                        // Les grandes familles d'abord ; le détail n'apparaît que pour celle choisie.
                        val ids = types.map { it.id }.toSet()
                        val racines = types.filter { it.parent == null || it.parent !in ids }
                        val choisi = types.firstOrNull { it.id == idType }
                        val famille = choisi?.let { c -> racines.firstOrNull { it.id == c.id || it.id == c.parent } }
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            racines.forEach { t -> FilterChip(selected = famille?.id == t.id, onClick = { idType = t.id }, label = { Text(t.libelle ?: "") }) }
                        }
                        val details = famille?.let { f -> types.filter { it.parent == f.id } } ?: emptyList()
                        if (details.isNotEmpty()) {
                            Text("Précisez, si vous le pouvez", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                details.forEach { t -> FilterChip(selected = idType == t.id, onClick = { idType = t.id }, label = { Text(t.libelle ?: "") }) }
                            }
                        }
                    }
                    etat.champs[ChampsDepot.TYPE]?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                    Champ(titre, { titre = it.take(120) }, "En quelques mots", Modifier.fillMaxWidth().padding(top = 8.dp), erreur = etat.champs[ChampsDepot.TITRE],
                        clavier = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences, imeAction = ImeAction.Next))
                }
            }
            if (genre != GenreDepot.SIGNALEMENT) {
                OutlinedTextField(
                    value = description, onValueChange = { description = it },
                    label = { Text(if (genre == GenreDepot.SECURITE) "Précision (facultatif)" else "Détails (facultatif)") },
                    modifier = Modifier.fillMaxWidth().padding(top = 4.dp), minLines = 2, maxLines = 5,
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                )
            }

            Titre("Où")
            when {
                lieu != null -> Text("Le lieu que vous avez touché sur la carte sera joint.", style = MaterialTheme.typography.bodyMedium)
                position != null -> Text("Votre position actuelle sera jointe (précision : ${position.precisionM.toInt()} m).", style = MaterialTheme.typography.bodyMedium)
                !autorise -> {
                    Text(
                        if (genre == GenreDepot.SIGNALEMENT) "Un signalement doit être situé. La position n'est lue que maintenant, pour ce dépôt."
                        else "Joindre votre position aide les secours à vous trouver. Elle n'est lue que maintenant, pour ce dépôt.",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    OutlinedButton(onClick = demanderPosition, modifier = Modifier.padding(top = 6.dp)) { Text("Joindre ma position") }
                }
                else -> Text("Recherche de votre position…", style = MaterialTheme.typography.bodyMedium, color = Attente)
            }
            etat.champs[ChampsDepot.POSITION]?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }

            Titre("Qui")
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Champ(prenom, { prenom = it }, "Prénom", Modifier.weight(1f), erreur = etat.champs[ChampsDepot.PRENOM],
                    clavier = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Next))
                Champ(nom, { nom = it }, "Nom", Modifier.weight(1f), erreur = etat.champs[ChampsDepot.NOM],
                    clavier = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Next))
            }
            Champ(telephone, { telephone = it }, "Téléphone", Modifier.fillMaxWidth(), erreur = etat.champs[ChampsDepot.TELEPHONE],
                clavier = KeyboardOptions(keyboardType = KeyboardType.Phone, imeAction = ImeAction.Next))
            if (genre != GenreDepot.SECURITE) {
                Champ(email, { email = it }, "Adresse e-mail", Modifier.fillMaxWidth(), erreur = etat.champs[ChampsDepot.EMAIL],
                    clavier = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Done))
            }

            etat.erreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp)) }
            Spacer(Modifier.height(16.dp))
            Button(
                onClick = {
                    modele.deposer(Depot(
                        genre = genre, crise = crise, deposant = Deposant(prenom, nom, email, telephone),
                        titre = titre, description = description, type = types.firstOrNull { it.id == idType },
                        situation = situation, declarant = declarant,
                        adultes = adultes.toIntOrNull() ?: 0, enfants = enfants.toIntOrNull() ?: 0, position = position,
                    ))
                },
                enabled = !etat.enCours, modifier = Modifier.fillMaxWidth().height(52.dp),
            ) {
                if (etat.enCours) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                else Text("Envoyer")
            }
            Text(
                "Sans réseau, votre envoi est gardé sur ce téléphone et part dès que possible.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 8.dp),
            )
        }
    }
}

@Composable
private fun Titre(texte: String) {
    Text(texte, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 16.dp, bottom = 6.dp))
}

/**
 * La position, lue tant que le formulaire est affiché et pas une seconde de plus.
 * @return la position (ou `null`), si la permission est accordée, et de quoi la demander.
 */
@SuppressLint("MissingPermission")   // chaque lecture est précédée de ServiceSuivi.autorise
@Composable
fun positionDuMoment(): Triple<Releve?, Boolean, () -> Unit> {
    val contexte = LocalContext.current
    var autorise by remember { mutableStateOf(ServiceSuivi.autorise(contexte)) }
    var position by remember { mutableStateOf<Releve?>(null) }
    val demande = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { accordees ->
        autorise = accordees.values.any { it }
    }
    DisposableEffect(autorise) {
        val positions = contexte.getSystemService(LocationManager::class.java)
        val ecouteur = object : LocationListener {
            override fun onLocationChanged(p: Location) {
                position = Releve(p.latitude, p.longitude, System.currentTimeMillis(), p.accuracy)
            }
            @Deprecated("Deprecated in Java")
            override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit
            override fun onProviderEnabled(provider: String) = Unit
            override fun onProviderDisabled(provider: String) = Unit
        }
        if (autorise) {
            for (source in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
                if (positions.allProviders.contains(source)) {
                    // Une position de moins de deux minutes est encore celle du moment.
                    positions.getLastKnownLocation(source)
                        ?.takeIf { System.currentTimeMillis() - it.time < 120_000 }
                        ?.let(ecouteur::onLocationChanged)
                    positions.requestLocationUpdates(source, 3_000L, 0f, ecouteur)
                }
            }
        }
        onDispose { positions.removeUpdates(ecouteur) }
    }
    return Triple(position, autorise) {
        demande.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
    }
}
