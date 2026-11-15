package fr.assistacrise.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.EtapeConnexion
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.R

@Composable
fun EcranConnexion(modele: ModeleApplication) {
    var email by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    var motDePasse by rememberSaveable { mutableStateOf("") }
    var visible by rememberSaveable { mutableStateOf(false) }
    var oubli by rememberSaveable { mutableStateOf(false) }
    val etat = modele.connexion
    val etape = modele.etapeConnexion
    // Adresse, puis code de sécurité si le compte est protégé, puis mot de passe : le
    // serveur ne regarde pas le mot de passe tant que le code n'a pas été donné.
    val envoyer = {
        when (etape) {
            EtapeConnexion.ADRESSE -> modele.continuerLaConnexion(email)
            EtapeConnexion.CODE -> { modele.donnerLeCode(email, code); code = "" }
            EtapeConnexion.MOT_DE_PASSE -> modele.connecter(email, motDePasse)
        }
    }

    Column(
        Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Logo(taille = 168.dp)
        Spacer(Modifier.height(20.dp))
        Text(stringResource(R.string.nom_application), style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.primary)
        Text(
            "Connectez-vous avec votre compte habituel.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(28.dp))

        Column(Modifier.widthIn(max = 420.dp).fillMaxWidth()) {
            Champ(
                email, { email = it }, "Adresse e-mail", Modifier.fillMaxWidth(),
                clavier = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Done),
                actif = !etat.enCours && etape == EtapeConnexion.ADRESSE,
            )
            if (etape != EtapeConnexion.ADRESSE) {
                TextButton(onClick = { code = ""; motDePasse = ""; modele.recommencerLaConnexion() }, enabled = !etat.enCours) {
                    Text("Ce n'est pas la bonne adresse")
                }
            }
            if (etape == EtapeConnexion.CODE) {
                Champ(
                    code, { code = it }, "Code de sécurité", Modifier.fillMaxWidth(),
                    clavier = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                    actif = !etat.enCours,
                )
                Text(
                    "Les 6 chiffres de votre application d'authentification, ou ceux que nous venons de " +
                        "vous envoyer par e-mail si votre compte fonctionne ainsi (valables 5 minutes). " +
                        "À défaut, l'un de vos codes de secours.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 4.dp),
                )
                TextButton(onClick = { modele.renvoyerLeCode(email) }, enabled = !etat.enCours) {
                    Text("Renvoyer le code par e-mail")
                }
                modele.messageEnvoiCode?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (etape == EtapeConnexion.MOT_DE_PASSE) {
                Champ(
                    motDePasse, { motDePasse = it }, "Mot de passe", Modifier.fillMaxWidth(),
                    clavier = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                    transformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
                    actif = !etat.enCours,
                    fin = { TextButton(onClick = { visible = !visible }) { Text(if (visible) "Masquer" else "Afficher") } },
                )
            }
            etat.erreur?.let {
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp))
            }
            Spacer(Modifier.height(16.dp))
            Button(onClick = envoyer, enabled = !etat.enCours, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                if (etat.enCours) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                else Text(if (etape == EtapeConnexion.MOT_DE_PASSE) "Se connecter" else "Continuer")
            }
            Spacer(Modifier.height(10.dp))
            OutlinedButton(onClick = { modele.aller(Ecran.INSCRIPTION) }, enabled = !etat.enCours, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                Text("Créer un compte")
            }
            TextButton(onClick = { oubli = true }, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                Text("Mot de passe oublié ?")
            }
            Spacer(Modifier.height(20.dp))
            // Sans compte : celui qui contrôle une attestation n'est pas forcément des nôtres.
            OutlinedButton(onClick = modele::ouvrirScanner, modifier = Modifier.fillMaxWidth().height(50.dp)) {
                Text("Lire un QR code de mobilisation")
            }
        }
    }

    if (oubli) {
        var adresse by rememberSaveable { mutableStateOf(email) }
        AlertDialog(
            onDismissRequest = { oubli = false },
            title = { Text("Mot de passe oublié") },
            text = {
                Column {
                    Text("Indiquez l'adresse de votre compte. Vous recevrez un e-mail avec un lien pour choisir un nouveau mot de passe.")
                    Spacer(Modifier.height(12.dp))
                    Champ(
                        adresse, { adresse = it }, "Adresse e-mail", Modifier.fillMaxWidth(),
                        clavier = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Done),
                    )
                }
            },
            confirmButton = {
                TextButton(enabled = adresse.isNotBlank(), onClick = { modele.demanderNouveauMotDePasse(adresse); oubli = false }) { Text("Envoyer") }
            },
            dismissButton = { TextButton(onClick = { oubli = false }) { Text("Annuler") } },
        )
    }
}
