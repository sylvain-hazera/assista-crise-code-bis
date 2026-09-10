import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CompagnonMeshCoreService } from '../../services/compagnon-meshcore.service';
import { CompagnonMeshCore, MeshCoreConnexionType } from '../../shared/models/compagnon-meshcore.model';

/** Page de test MeshCore : juste de quoi déclarer un companion (nom + IP/port, ou device série,
 * ou adresse BLE) sans passer par le Django admin — voir meshcore-bridge/README.md pour le
 * service qui se connecte réellement dessus. Volontairement minimal (pas de gestion
 * d'institution ici) tant que le matériel n'a pas confirmé l'usage — voir doc de conception
 * « Maillage Terrain ». Reste sur la branche feature/meshcore-poc, jamais déployée sur .114. */
@Component({
  selector: 'app-meshcore-companions',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meshcore-companions.component.html',
  styleUrl: './meshcore-companions.component.scss',
})
export class MeshcoreCompanionsComponent implements OnInit {

  companions: CompagnonMeshCore[] = [];
  loading = true;
  errorMessage = '';

  nouveauNom = '';
  nouveauType: MeshCoreConnexionType = 'TCP';
  nouveauHost = '';
  nouveauPort = 5000;
  nouveauDevice = '/dev/ttyUSB0';
  nouveauBle = '';
  creating = false;

  constructor(private service: CompagnonMeshCoreService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.service.getAll().subscribe({
      next: (data) => { this.companions = data; this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger les companions.'; this.loading = false; },
    });
  }

  get formValide(): boolean {
    if (!this.nouveauNom.trim()) return false;
    if (this.nouveauType === 'TCP') return !!this.nouveauHost.trim() && !!this.nouveauPort;
    if (this.nouveauType === 'SERIE') return !!this.nouveauDevice.trim();
    if (this.nouveauType === 'BLE') return !!this.nouveauBle.trim();
    return false;
  }

  ajouter(): void {
    if (!this.formValide) return;

    const payload: Partial<CompagnonMeshCore> = {
      nom: this.nouveauNom.trim(),
      connexion_type: this.nouveauType,
    };
    if (this.nouveauType === 'TCP') {
      payload.tcp_host = this.nouveauHost.trim();
      payload.tcp_port = this.nouveauPort;
    } else if (this.nouveauType === 'SERIE') {
      payload.serie_device = this.nouveauDevice.trim();
    } else if (this.nouveauType === 'BLE') {
      payload.ble_adresse = this.nouveauBle.trim();
    }

    this.creating = true;
    this.service.create(payload).subscribe({
      next: (created) => {
        this.companions = [created, ...this.companions];
        this.nouveauNom = '';
        this.nouveauHost = '';
        this.nouveauBle = '';
        this.creating = false;
      },
      error: () => { this.errorMessage = "Impossible de créer ce companion."; this.creating = false; },
    });
  }

  supprimer(companion: CompagnonMeshCore): void {
    if (!confirm(`Supprimer le companion « ${companion.nom} » ?`)) return;
    this.service.delete(companion.id).subscribe(() => {
      this.companions = this.companions.filter(c => c.id !== companion.id);
    });
  }

  adresse(c: CompagnonMeshCore): string {
    if (c.connexion_type === 'TCP') return `${c.tcp_host}:${c.tcp_port}`;
    if (c.connexion_type === 'SERIE') return c.serie_device || '—';
    return c.ble_adresse || '—';
  }

  statutClass(c: CompagnonMeshCore): string {
    if (c.dernier_etat === 'CONNECTE') return 'statut-ok';
    if (c.dernier_etat === 'ERREUR') return 'statut-erreur';
    return 'statut-inconnu';
  }

  copierId(c: CompagnonMeshCore): void {
    navigator.clipboard?.writeText(c.id).catch(() => {});
  }
}
