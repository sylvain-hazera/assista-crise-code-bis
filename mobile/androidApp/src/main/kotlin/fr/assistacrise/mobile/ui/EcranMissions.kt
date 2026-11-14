package fr.assistacrise.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.rangerParMission
import androidx.compose.material3.HorizontalDivider
import fr.assistacrise.mobile.domaine.EtatAction
import fr.assistacrise.mobile.domaine.MissionAffichee
import fr.assistacrise.mobile.domaine.Mode
import fr.assistacrise.mobile.domaine.StatutMission

@Composable
fun EcranMissions(modele: ModeleApplication, compte: Compte) {
    val missions by modele.missions.collectAsStateWithLifecycle()
    val file by modele.file.collectAsStateWithLifecycle()
    val lien by modele.lien.collectAsStateWithLifecycle()
    val dossiers by modele.dossiers.collectAsStateWithLifecycle()
    var ouverte by rememberSaveable { mutableStateOf<String?>(null) }
    val ranges = rangerParMission(dossiers, missions.map { it.mission.id })

    val enAttente = file.count { it.etat == EtatAction.EN_ATTENTE }
    val refusees = file.count { it.etat == EtatAction.REFUSEE }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Mes missions", style = MaterialTheme.typography.headlineSmall)
                Text(
                    compte.institutionNom ?: compte.nomComplet,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
            }
            PastilleLien(lien)
            IconButton(onClick = modele::actualiser, enabled = !modele.synchronisation) {
                if (modele.synchronisation) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                else Icon(Icons.Filled.Refresh, contentDescription = "Actualiser")
            }
        }

        // Ce qui attend d'être envoyé est toujours sous les yeux, pas dans un sous-menu.
        if (enAttente > 0 || refusees > 0) {
            BandeauFile(enAttente, refusees) { modele.aller(Ecran.COMPTE) }
        }

        if (missions.isEmpty() && ranges.sansMission.isEmpty()) {
            EtatVide(compte)
        } else {
            LazyColumn(
                Modifier.fillMaxSize().padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 12.dp),
            ) {
                items(missions, key = { it.mission.id }) { m ->
                    CarteMission(m, ranges.parMission[m.mission.id].orEmpty(), modele::ouvrirDossier) { ouverte = m.mission.id }
                }
                // Un dossier confié à l'équipe sans être rangé sous une mission reste du travail à faire.
                if (ranges.sansMission.isNotEmpty()) {
                    item(key = "sans-mission") {
                        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(vertical = 12.dp)) {
                                Text(if (missions.isEmpty()) "Dossiers de mes équipes" else "Autres dossiers de mes équipes", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 16.dp))
                                ranges.sansMission.forEach { d -> LigneDossier(d, Modifier.fillMaxWidth().clickable { modele.ouvrirDossier(d.id) }.padding(horizontal = 16.dp, vertical = 8.dp)) }
                            }
                        }
                    }
                }
            }
        }
    }

    missions.firstOrNull { it.mission.id == ouverte }?.let { m ->
        DetailMission(
            m, peutPiloter = compte.peutPiloterLesMissions,
            surStatut = { statut -> modele.declarerStatut(m.mission, statut); ouverte = null },
            surFermeture = { ouverte = null },
        )
    }
}

@Composable
private fun BandeauFile(enAttente: Int, refusees: Int, surClic: () -> Unit) {
    val (couleur, texte) = if (refusees > 0) {
        Refus to (if (refusees == 1) "1 changement refusé par le serveur" else "$refusees changements refusés par le serveur")
    } else {
        Attente to (if (enAttente == 1) "1 changement en attente d'envoi" else "$enAttente changements en attente d'envoi")
    }
    Surface(
        color = couleur.copy(alpha = 0.12f),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).clickable(onClick = surClic),
    ) {
        Row(Modifier.padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.Warning, contentDescription = null, tint = couleur, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(10.dp))
            Text(texte, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            Text("Voir", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
private fun EtatVide(compte: Compte) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Aucune mission pour l'instant", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))
        Text(
            when {
                compte.reserveAVerifier ->
                    "Votre candidature est en cours d'examen par l'association. Vos missions apparaîtront ici une fois votre compte validé et une équipe attribuée."
                compte.mode == Mode.CITOYEN ->
                    "Vous n'êtes rattaché à aucune équipe. Les missions des équipes dont vous êtes membre apparaîtront ici."
                else -> "Les missions de vos équipes apparaîtront ici dès qu'elles seront créées."
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        )
    }
}

@Composable
private fun CarteMission(m: MissionAffichee, dossiers: List<Dossier>, ouvrirDossier: (String) -> Unit, surClic: () -> Unit) {
    Card(
        onClick = surClic,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(m.mission.titre, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.width(8.dp))
                EtiquetteStatut(m.mission.statut)
            }
            m.mission.criseNom?.let {
                Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (m.mission.equipesNoms.isNotEmpty()) {
                Text(m.mission.equipesNoms.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (m.nonConfirme) {
                Spacer(Modifier.height(6.dp))
                Text("Non confirmé : en attente d'envoi", style = MaterialTheme.typography.labelMedium, color = Attente)
            }
        }
        // Ce qu'il y a à faire dans cette mission : chaque ligne ouvre son dossier.
        if (dossiers.isNotEmpty()) {
            HorizontalDivider()
            dossiers.forEach { d -> LigneDossier(d, Modifier.fillMaxWidth().clickable { ouvrirDossier(d.id) }.padding(horizontal = 16.dp, vertical = 8.dp)) }
            Spacer(Modifier.height(6.dp))
        }
    }
}

@Composable
private fun EtiquetteStatut(statut: StatutMission) {
    val couleur: Color = when (statut) {
        StatutMission.EN_PREPARATION -> MaterialTheme.colorScheme.outline
        StatutMission.EN_COURS -> MaterialTheme.colorScheme.secondary
        StatutMission.TERMINEE -> EnLigne
    }
    Surface(color = couleur.copy(alpha = 0.14f), shape = RoundedCornerShape(50)) {
        Text(statut.libelle, style = MaterialTheme.typography.labelMedium, color = couleur, modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp))
    }
}

@Composable
private fun DetailMission(m: MissionAffichee, peutPiloter: Boolean, surStatut: (StatutMission) -> Unit, surFermeture: () -> Unit) {
    AlertDialog(
        onDismissRequest = surFermeture,
        title = { Text(m.mission.titre) },
        text = {
            Column {
                EtiquetteStatut(m.mission.statut)
                if (m.nonConfirme) {
                    Text("Ce statut n'est pas encore confirmé par le serveur.", style = MaterialTheme.typography.bodySmall, color = Attente, modifier = Modifier.padding(top = 6.dp))
                }
                if (m.mission.description.isNotBlank()) {
                    Spacer(Modifier.height(12.dp))
                    Text(m.mission.description, style = MaterialTheme.typography.bodyMedium)
                }
                if (peutPiloter) {
                    Spacer(Modifier.height(16.dp))
                    m.mission.statut.voisins().forEach { statut ->
                        Button(onClick = { surStatut(statut) }, modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                            Text("Passer à « ${statut.libelle} »")
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = surFermeture) { Text("Fermer") } },
    )
}
