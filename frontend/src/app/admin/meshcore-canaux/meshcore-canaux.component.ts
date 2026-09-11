import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CanalMeshCoreService } from '../../services/canal-meshcore.service';
import { CanalMeshCore, MessageCanalMeshCore } from '../../shared/models/canal-meshcore.model';

/** Chat de coordination générale sur les canaux MeshCore (clé partagée, diffusion à N
 * destinataires) — à l'opposé des DM privés régulateur<->équipe qui vivent dans le panneau
 * dédié de la vue équipe. Bandeau de rappel volontairement affiché en permanence : le
 * chiffrement par clé partagée est plus faible que le chiffrement par paire des DM, ce canal
 * n'est pas fait pour du contenu sensible (voir doc de conception « Maillage Terrain »). */
@Component({
  selector: 'app-meshcore-canaux',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meshcore-canaux.component.html',
  styleUrl: './meshcore-canaux.component.scss',
})
export class MeshcoreCanauxComponent implements OnInit, OnDestroy {

  canaux: CanalMeshCore[] = [];
  canalSelectionne: CanalMeshCore | null = null;
  messages: MessageCanalMeshCore[] = [];
  loadingCanaux = true;
  loadingMessages = false;
  errorMessage = '';

  nouveauCanalNom = '';
  nouveauCanalCle = '';
  creatingCanal = false;

  nouveauMessage = '';
  envoiEnCours = false;

  private intervalRafraichissement: ReturnType<typeof setInterval> | null = null;

  constructor(private service: CanalMeshCoreService) {}

  ngOnInit(): void {
    this.chargerCanaux();
    this.intervalRafraichissement = setInterval(() => {
      if (this.canalSelectionne) this.chargerMessages(this.canalSelectionne.id, false);
    }, 8000);
  }

  ngOnDestroy(): void {
    if (this.intervalRafraichissement) clearInterval(this.intervalRafraichissement);
  }

  chargerCanaux(): void {
    this.loadingCanaux = true;
    this.service.getAll().subscribe({
      next: (data) => {
        this.canaux = data;
        this.loadingCanaux = false;
        if (!this.canalSelectionne && data.length > 0) this.selectionnerCanal(data[0]);
      },
      error: () => { this.errorMessage = 'Impossible de charger les canaux.'; this.loadingCanaux = false; },
    });
  }

  get formCanalValide(): boolean {
    return !!this.nouveauCanalNom.trim();
  }

  creerCanal(): void {
    if (!this.formCanalValide) return;
    this.creatingCanal = true;
    this.service.create({
      nom: this.nouveauCanalNom.trim(),
      cle_partagee_hex: this.nouveauCanalCle.trim() || undefined,
    }).subscribe({
      next: (created) => {
        this.canaux = [created, ...this.canaux];
        this.nouveauCanalNom = '';
        this.nouveauCanalCle = '';
        this.creatingCanal = false;
        this.selectionnerCanal(created);
      },
      error: () => { this.errorMessage = 'Impossible de créer ce canal.'; this.creatingCanal = false; },
    });
  }

  selectionnerCanal(canal: CanalMeshCore): void {
    this.canalSelectionne = canal;
    this.chargerMessages(canal.id, true);
  }

  chargerMessages(canalId: string, avecSpinner: boolean): void {
    if (avecSpinner) this.loadingMessages = true;
    this.service.getMessages(canalId).subscribe({
      next: (data) => { this.messages = data; this.loadingMessages = false; },
      error: () => { if (avecSpinner) this.loadingMessages = false; },
    });
  }

  envoyer(): void {
    if (!this.canalSelectionne || !this.nouveauMessage.trim()) return;
    this.envoiEnCours = true;
    this.service.envoyerMessage(this.canalSelectionne.id, this.nouveauMessage.trim()).subscribe({
      next: (message) => {
        this.messages = [...this.messages, message];
        this.nouveauMessage = '';
        this.envoiEnCours = false;
      },
      error: () => { this.errorMessage = "Échec de l'envoi."; this.envoiEnCours = false; },
    });
  }
}
