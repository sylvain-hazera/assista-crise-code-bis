package fr.assistacrise.mobile.ui

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.domaine.Destination
import fr.assistacrise.mobile.domaine.Navigation
import fr.assistacrise.mobile.domaine.Releve

/**
 * « Aller vers » (22/11/2026) : une flèche, la distance et le cap, à vol d'oiseau, sans réseau.
 * La flèche suit la boussole du téléphone ; en mouvement, le cap du GPS fait foi. Arrivé à
 * moins de 30 m, l'application propose d'envoyer « Arrivé sur les lieux ».
 */
@Composable
fun AllerVers(destination: Destination, moi: Releve?, capGps: Float?, surArrivee: () -> Unit, surFermeture: () -> Unit) {
    val contexte = LocalContext.current
    var orientation by remember { mutableStateOf<Double?>(null) }
    var ecranAllume by remember { mutableStateOf(false) }
    var arriveeProposee by remember { mutableStateOf(false) }

    DisposableEffect(Unit) {
        val capteurs = contexte.getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val vecteur = capteurs.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        val ecoute = object : SensorEventListener {
            private val matrice = FloatArray(9)
            private val angles = FloatArray(3)
            override fun onSensorChanged(e: SensorEvent) {
                SensorManager.getRotationMatrixFromVector(matrice, e.values)
                SensorManager.getOrientation(matrice, angles)
                orientation = (Math.toDegrees(angles[0].toDouble()) + 360) % 360
            }
            override fun onAccuracyChanged(s: Sensor?, a: Int) = Unit
        }
        vecteur?.let { capteurs.registerListener(ecoute, it, SensorManager.SENSOR_DELAY_UI) }
        onDispose { capteurs.unregisterListener(ecoute) }
    }
    DisposableEffect(ecranAllume) {
        val fenetre = (contexte as? ComponentActivity)?.window
        if (ecranAllume) fenetre?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { fenetre?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }

    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.surface) {
        Column(Modifier.fillMaxSize().padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Aller vers", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(destination.nom, style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
            if (moi == null) {
                Text("En attente de votre position…", style = MaterialTheme.typography.bodyLarge)
            } else {
                val distance = Navigation.distanceM(moi.latitude, moi.longitude, destination.latitude, destination.longitude)
                val cap = Navigation.capDeg(moi.latitude, moi.longitude, destination.latitude, destination.longitude)
                val telephone = capGps?.toDouble() ?: orientation
                val couleur = MaterialTheme.colorScheme.primary
                if (telephone != null) {
                    val angle = Navigation.angleFleche(cap, telephone).toFloat()
                    Canvas(Modifier.size(220.dp)) {
                        rotate(angle) {
                            val l = size.minDimension
                            val fleche = Path().apply {
                                moveTo(l / 2, l * 0.05f); lineTo(l * 0.8f, l * 0.75f); lineTo(l / 2, l * 0.6f); lineTo(l * 0.2f, l * 0.75f); close()
                            }
                            drawPath(fleche, couleur)
                            drawCircle(couleur.copy(alpha = 0.15f), radius = l / 2, center = Offset(l / 2, l / 2))
                        }
                    }
                } else {
                    Text("Boussole indisponible : suivez le cap.", style = MaterialTheme.typography.bodyMedium)
                }
                Text(Navigation.distanceLisible(distance), style = MaterialTheme.typography.displaySmall)
                Text("Cap ${Navigation.capLisible(cap)} · à vol d'oiseau", style = MaterialTheme.typography.bodyLarge)
                Text(if (capGps != null) "Orientation : votre déplacement (GPS)" else "Orientation : boussole du téléphone",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (distance <= Navigation.SEUIL_ARRIVEE_M && !arriveeProposee) {
                    Button(onClick = { arriveeProposee = true; surArrivee() }, modifier = Modifier.fillMaxWidth()) {
                        Text("Vous y êtes : envoyer « Arrivé sur les lieux »")
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Garder l'écran allumé", modifier = Modifier.padding(end = 8.dp))
                Switch(checked = ecranAllume, onCheckedChange = { ecranAllume = it })
            }
            OutlinedButton(onClick = surFermeture) { Text("Fermer") }
        }
    }
}
