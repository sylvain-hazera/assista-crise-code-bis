package fr.assistacrise.mobile.ui

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color as CouleurAndroid
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.EncodeHintType
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import fr.assistacrise.mobile.BuildConfig
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.Mobilisation
import java.util.concurrent.Executors

/**
 * Lire un QR code de mobilisation. Accessible **sans compte**, dès l'écran de connexion : celui
 * qui contrôle une attestation au bord d'une route n'est pas forcément des nôtres.
 *
 * Les images de la caméra sont analysées une à une sur le téléphone et jetées aussitôt :
 * rien n'est enregistré, rien n'est envoyé, sinon le jeton lu — à notre serveur.
 */
@Composable
fun EcranScanner(modele: ModeleApplication) {
    val contexte = LocalContext.current
    var autorise by remember { mutableStateOf(contexte.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    val demande = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { autorise = it }

    Column(Modifier.fillMaxSize()) {
        EnTeteRetour("Lire un QR code", modele, modele::fermerScanner)
        if (!autorise) {
            Column(Modifier.padding(24.dp)) {
                Text("Pour lire un QR code, l'application a besoin de la caméra. Elle ne sert qu'à cela : aucune image n'est enregistrée.", style = MaterialTheme.typography.bodyLarge)
                Spacer(Modifier.height(16.dp))
                Button(onClick = { demande.launch(Manifest.permission.CAMERA) }, modifier = Modifier.fillMaxWidth().height(50.dp)) { Text("Autoriser la caméra") }
            }
            return@Column
        }
        Box(Modifier.weight(1f).fillMaxWidth().background(Color.Black), contentAlignment = Alignment.Center) {
            VueCamera(modele::qrLu)
            // Le cadre guide le geste ; la lecture, elle, se fait sur toute l'image.
            Box(Modifier.fillMaxWidth(0.72f).aspectRatio(1f).border(3.dp, Color.White, RoundedCornerShape(16.dp)))
        }
        Text(
            modele.erreurScanner ?: "Visez le QR code de l'attestation de mobilisation.",
            style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center,
            color = if (modele.erreurScanner != null) Refus else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.fillMaxWidth().padding(20.dp),
        )
    }
}

@Composable
private fun VueCamera(surLecture: (String) -> Unit) {
    val contexte = LocalContext.current
    val cycle = LocalLifecycleOwner.current
    val vue = remember { PreviewView(contexte) }
    DisposableEffect(cycle) {
        val analyse = Executors.newSingleThreadExecutor()
        val principal = ContextCompat.getMainExecutor(contexte)
        val futur = ProcessCameraProvider.getInstance(contexte)
        futur.addListener({
            val camera = futur.get()
            val apercu = Preview.Builder().build().also { it.setSurfaceProvider(vue.surfaceProvider) }
            val lecteur = QRCodeReader()
            val images = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
            images.setAnalyzer(analyse) { image -> lire(image, lecteur)?.let { texte -> principal.execute { surLecture(texte) } }; image.close() }
            runCatching {
                camera.unbindAll()
                camera.bindToLifecycle(cycle, CameraSelector.DEFAULT_BACK_CAMERA, apercu, images)
            }
        }, principal)
        onDispose {
            runCatching { futur.get().unbindAll() }
            analyse.shutdown()
        }
    }
    AndroidView(factory = { vue }, modifier = Modifier.fillMaxSize())
}

/** Cherche un QR code dans une image de la caméra. `null` : il n'y en a pas, ce qui est le cas ordinaire. */
private fun lire(image: ImageProxy, lecteur: QRCodeReader): String? = runCatching {
    val plan = image.planes[0]
    val largeur = image.width
    val hauteur = image.height
    // Les lignes du capteur peuvent être plus longues que l'image : on ne recopie que l'image.
    val gris = ByteArray(largeur * hauteur)
    val tampon = plan.buffer
    for (ligne in 0 until hauteur) {
        tampon.position(ligne * plan.rowStride)
        tampon.get(gris, ligne * largeur, minOf(largeur, tampon.remaining()))
    }
    val source = PlanarYUVLuminanceSource(gris, largeur, hauteur, 0, 0, largeur, hauteur, false)
    lecteur.decode(BinaryBitmap(HybridBinarizer(source))).text
}.getOrNull().also { lecteur.reset() }

/** Le verdict : valide ou non, en grand, puis ce que le serveur accepte d'en dire. */
@Composable
fun EcranVerdict(modele: ModeleApplication) {
    val compte by modele.compte.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize()) {
        EnTeteRetour("Vérification", modele, modele::fermerScanner)
        val v = modele.verdict
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            when {
                modele.verificationEnCours -> { Spacer(Modifier.height(60.dp)); CircularProgressIndicator(); Spacer(Modifier.height(16.dp)); Text("Vérification auprès du serveur…") }
                v == null -> Text(
                    // Sans réponse du serveur, on ne dit ni valide ni invalide : on ne sait pas.
                    modele.erreurScanner ?: "La vérification n'a pas abouti.",
                    style = MaterialTheme.typography.titleMedium, color = Attente, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 40.dp),
                )
                else -> {
                    val couleur = if (v.valide) EnLigne else Refus
                    Surface(color = couleur.copy(alpha = 0.12f), shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            // Le mot d'abord, la couleur ensuite : le verdict se lit en plein soleil.
                            Text(if (v.valide) "VALIDE" else if (v.connue) "RÉVOQUÉE" else "INCONNUE", style = MaterialTheme.typography.displaySmall, color = couleur)
                            Text(v.motif, style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center)
                        }
                    }
                    if (v.connue) {
                        Spacer(Modifier.height(16.dp))
                        Ligne("Référence", v.reference)
                        Ligne("Émise par", v.institution)
                        Ligne("Crise", v.crise)
                        Ligne("Nature", v.nature)
                        instantDe(v.date)?.let { Ligne("Émise", ilYA(it)) }
                        v.destinataire?.takeIf { it.isNotBlank() }?.let { Ligne("Destinataire", it) }
                        v.lieu?.takeIf { it.isNotBlank() }?.let { Ligne("Lieu", it) }
                        if (!v.complet) {
                            Spacer(Modifier.height(12.dp))
                            Text(
                                "Le nom de la personne et le lieu ne sont montrés qu'à un compte connecté. Comparez la référence à celle de l'attestation présentée.",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center,
                            )
                        }
                    }
                }
            }
        }
        Column(Modifier.padding(20.dp)) {
            Button(onClick = modele::ouvrirScanner, modifier = Modifier.fillMaxWidth().height(50.dp)) { Text("Lire un autre QR code") }
            if (compte == null) {
                Spacer(Modifier.height(8.dp))
                OutlinedButton(onClick = modele::fermerScanner, modifier = Modifier.fillMaxWidth().height(50.dp)) { Text("Retour à la connexion") }
            }
        }
    }
}

@Composable
private fun Ligne(nom: String, valeur: String) {
    if (valeur.isBlank()) return
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Text(nom, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(valeur, style = MaterialTheme.typography.bodyLarge)
    }
    HorizontalDivider()
}

/**
 * Mes attestations, à présenter. Le QR code est dessiné sur le téléphone à partir de ce qui y
 * est gardé : il s'affiche sans réseau — c'est celui qui le lit qui a besoin du serveur.
 */
@Composable
fun EcranMobilisations(modele: ModeleApplication) {
    val mobilisations by modele.mobilisations.collectAsStateWithLifecycle()
    var choisie by rememberSaveable { mutableStateOf<String?>(null) }
    val montree = mobilisations.firstOrNull { it.id == choisie } ?: mobilisations.firstOrNull { it.active } ?: mobilisations.firstOrNull()

    Column(Modifier.fillMaxSize()) {
        EnTeteRetour("Mon QR code", modele, modele::fermerScanner)
        if (montree == null) {
            Text(
                "Aucune demande de mobilisation ne vous est adressée pour l'instant. Quand une institution vous mobilisera, son QR code apparaîtra ici.",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(20.dp),
            )
            return@Column
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            QrCode(montree)
            Spacer(Modifier.height(12.dp))
            Text(if (montree.active) "Attestation active" else "Attestation révoquée", style = MaterialTheme.typography.titleMedium, color = if (montree.active) EnLigne else Refus)
            Text("Référence ${montree.reference}", style = MaterialTheme.typography.bodyLarge)
            Text(listOf(montree.institutionNom, montree.criseNom, montree.nature, montree.lieu).filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
            if (mobilisations.size > 1) {
                Spacer(Modifier.height(20.dp))
                Text("Vos autres attestations", style = MaterialTheme.typography.titleSmall, modifier = Modifier.fillMaxWidth())
                mobilisations.filter { it.id != montree.id }.forEach { m ->
                    Column(Modifier.fillMaxWidth().clickable { choisie = m.id }.padding(vertical = 10.dp)) {
                        Text(listOf(m.criseNom, m.nature).filter { it.isNotBlank() }.joinToString(" · ").ifBlank { "Référence ${m.reference}" }, style = MaterialTheme.typography.bodyLarge)
                        Text(if (m.active) "Active · ${m.institutionNom}" else "Révoquée · ${m.institutionNom}", style = MaterialTheme.typography.bodySmall, color = if (m.active) MaterialTheme.colorScheme.onSurfaceVariant else Refus)
                    }
                    HorizontalDivider()
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

/** Le QR code, noir sur blanc quel que soit le thème, écran poussé à pleine luminosité tant qu'il est montré. */
@Composable
private fun QrCode(m: Mobilisation) {
    val contexte = LocalContext.current
    val adresse = m.adresseDeVerification(BuildConfig.URL_SITE) ?: return
    val image = remember(adresse) { dessinerQr(adresse) }
    DisposableEffect(Unit) {
        val fenetre = (contexte as? Activity)?.window
        val avant = fenetre?.attributes?.screenBrightness
        fenetre?.let { it.attributes = it.attributes.apply { screenBrightness = 1f } }
        onDispose { fenetre?.let { f -> f.attributes = f.attributes.apply { screenBrightness = avant ?: -1f } } }
    }
    Box(Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(12.dp)).background(Color.White).padding(12.dp), contentAlignment = Alignment.Center) {
        if (image != null) Image(image.asImageBitmap(), contentDescription = "QR code de l'attestation ${m.reference}", modifier = Modifier.fillMaxSize(), filterQuality = androidx.compose.ui.graphics.FilterQuality.None)
        else Text("QR code indisponible", color = Color.Black)
    }
}

private fun dessinerQr(texte: String): Bitmap? = runCatching {
    // Niveau Q, comme l'attestation PDF : un écran rayé ou un reflet n'empêchent pas la lecture.
    val grille = QRCodeWriter().encode(texte, BarcodeFormat.QR_CODE, 0, 0, mapOf(EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.Q, EncodeHintType.MARGIN to 2))
    Bitmap.createBitmap(grille.width, grille.height, Bitmap.Config.RGB_565).apply {
        for (x in 0 until grille.width) for (y in 0 until grille.height) setPixel(x, y, if (grille[x, y]) CouleurAndroid.BLACK else CouleurAndroid.WHITE)
    }
}.getOrNull()
