import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { SatelliteService } from '../../services/satellite.service';
import { AuthService } from '../../auth/services/auth.service';
import { Satellite, JetonEnrolementSatellite, IdentifiantsCompteServiceSatellite } from '../../shared/models/satellite.model';

/** Boîtiers Raspberry Pi déployés sur site (pont MeshCore/Meshtastic local, et pour le profil
 * Full une instance assista-crise complète utilisable même sans internet) — voir le cadrage
 * "Chantier B". Enrôlement en 3 temps : on génère ici un jeton à usage unique pour SON
 * institution, communiqué hors-bande au responsable du satellite lors de l'installation ; le
 * satellite le consomme lui-même pour apparaître ci-dessous en attente ; on valide alors pour
 * lui créer un compte de service — les identifiants ne sont affichés qu'à cet instant précis,
 * une seule fois, jamais relisibles ensuite (voir SatelliteService.valider). */
@Component({
  selector: 'app-satellites',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './satellites.component.html',
  styleUrl: './satellites.component.scss',
})
export class SatellitesComponent implements OnInit {

  satellites: Satellite[] = [];
  loading = true;
  errorMessage = '';

  isDemo = false;

  genererJetonEnCours = false;
  dernierJeton: JetonEnrolementSatellite | null = null;

  // Identifiants d'un compte de service, affichés une seule fois juste après validation — voir
  // SatelliteService.valider. Effacés dès qu'on quitte la page ou qu'on en valide un autre.
  identifiantsAffiches: { satelliteNom: string; identifiants: IdentifiantsCompteServiceSatellite } | null = null;

  actionEnCours: string | null = null;

  constructor(
    private service: SatelliteService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.isDemo = this.authService.getEnvironment() === 'DEMO';
    this.load();
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.service.getAll().subscribe({
      next: (data) => { this.satellites = data; this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger les satellites.'; this.loading = false; },
    });
  }

  genererJeton(): void {
    this.genererJetonEnCours = true;
    this.errorMessage = '';
    this.service.genererJeton().subscribe({
      next: (jeton) => { this.dernierJeton = jeton; this.genererJetonEnCours = false; },
      error: (err) => {
        this.errorMessage = err.error?.error || "Impossible de générer un jeton d'enrôlement.";
        this.genererJetonEnCours = false;
      },
    });
  }

  valider(satellite: Satellite): void {
    this.actionEnCours = satellite.id;
    this.errorMessage = '';
    this.identifiantsAffiches = null;
    this.service.valider(satellite.id).subscribe({
      next: (resultat) => {
        this.actionEnCours = null;
        this.identifiantsAffiches = { satelliteNom: satellite.nom, identifiants: resultat.identifiants_compte_service };
        this.load();
      },
      error: (err) => {
        this.actionEnCours = null;
        this.errorMessage = err.error?.error || 'Impossible de valider ce satellite.';
      },
    });
  }

  revoquer(satellite: Satellite): void {
    if (!confirm(`Révoquer le satellite « ${satellite.nom} » ? Son compte de service sera immédiatement désactivé.`)) return;
    this.actionEnCours = satellite.id;
    this.errorMessage = '';
    this.service.revoquer(satellite.id).subscribe({
      next: () => { this.actionEnCours = null; this.load(); },
      error: (err) => {
        this.actionEnCours = null;
        this.errorMessage = err.error?.error || 'Impossible de révoquer ce satellite.';
      },
    });
  }

  fermerIdentifiants(): void {
    this.identifiantsAffiches = null;
  }

  copier(texte: string): void {
    navigator.clipboard?.writeText(texte).catch(() => {});
  }

  etatClass(satellite: Satellite): string {
    if (satellite.etat === 'ACTIF') return 'statut-ok';
    if (satellite.etat === 'PERDU') return 'statut-erreur';
    if (satellite.etat === 'INACTIF') return 'statut-attention';
    return 'statut-inconnu';
  }

  etatLabel(satellite: Satellite): string {
    if (satellite.etat === 'ACTIF') return 'Actif';
    if (satellite.etat === 'INACTIF') return 'Inactif';
    if (satellite.etat === 'PERDU') return 'Perdu';
    return 'Jamais contacté';
  }
}
