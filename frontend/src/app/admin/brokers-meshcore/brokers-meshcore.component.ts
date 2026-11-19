import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import {
  SourceObservateurMeshCore, SourceObservateurMeshCoreService,
} from '../../services/source-observateur-meshcore.service';

type Brouillon = Omit<SourceObservateurMeshCore, 'id' | 'derniere_connexion' | 'dernier_etat' | 'derniere_erreur'>;

const BROUILLON_VIDE: Brouillon = {
  nom: '', broker_host: '', broker_port: 1883, mqtt_username: '', mqtt_password: '', mqtt_use_tls: false,
  mqtt_transport: 'tcp', mqtt_ws_chemin: '/mqtt', filtre_topic: 'meshcore/#', actif: true,
};

/** Brokers MQTT des observateurs MeshCore (19/11/2026).
 *
 * Un observateur est un répéteur au firmware complété d'un client MQTT : il republie ce qu'il
 * entend. Chaque broker déclaré ici est écouté en permanence par le service
 * `ac_observateurs_meshcore` ; ses trames deviennent des liaisons sur la carte radio, comme
 * celles qu'entendent nos propres companions. Déclarer ou modifier : administrateur de la
 * plateforme (une connexion sortante permanente est un acte d'exploitation). */
@Component({
  selector: 'app-brokers-meshcore',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './brokers-meshcore.component.html',
  styleUrls: ['./brokers-meshcore.component.scss'],
})
export class BrokersMeshcoreComponent implements OnInit {
  sources: SourceObservateurMeshCore[] = [];
  erreur: string | null = null;
  enEdition: string | null = null;      // id, « nouveau », ou null
  brouillon: Brouillon = { ...BROUILLON_VIDE };
  envoi = false;

  constructor(private readonly service: SourceObservateurMeshCoreService) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.service.liste().subscribe({
      next: l => { this.sources = Array.isArray(l) ? l : ((l as { results?: SourceObservateurMeshCore[] }).results ?? []); },
      error: () => { this.erreur = 'Liste des brokers indisponible.'; },
    });
  }

  nouveau(): void {
    this.enEdition = 'nouveau';
    this.brouillon = { ...BROUILLON_VIDE };
    this.erreur = null;
  }

  editer(s: SourceObservateurMeshCore): void {
    this.enEdition = s.id;
    this.brouillon = { ...BROUILLON_VIDE, ...s, mqtt_password: '' };
    this.erreur = null;
  }

  annuler(): void { this.enEdition = null; }

  /** Le transport WebSocket va presque toujours avec le port 443 et le chiffrement. */
  changerTransport(): void {
    if (this.brouillon.mqtt_transport === 'websockets' && this.brouillon.broker_port === 1883) {
      this.brouillon.broker_port = 443;
      this.brouillon.mqtt_use_tls = true;
    }
  }

  enregistrer(): void {
    const donnees: Partial<SourceObservateurMeshCore> = { ...this.brouillon };
    // Champ vide en modification : on garde le mot de passe déjà enregistré.
    if (this.enEdition !== 'nouveau' && !donnees.mqtt_password) { delete donnees.mqtt_password; }
    this.envoi = true;
    const appel = this.enEdition === 'nouveau'
      ? this.service.creer(donnees) : this.service.modifier(this.enEdition!, donnees);
    appel.subscribe({
      next: () => { this.envoi = false; this.enEdition = null; this.charger(); },
      error: (e: HttpErrorResponse) => { this.envoi = false; this.erreur = this.message(e); },
    });
  }

  basculer(s: SourceObservateurMeshCore): void {
    this.service.modifier(s.id, { actif: !s.actif }).subscribe({
      next: () => this.charger(),
      error: (e: HttpErrorResponse) => { this.erreur = this.message(e); },
    });
  }

  supprimer(s: SourceObservateurMeshCore): void {
    if (!confirm(`Ne plus écouter « ${s.nom} » ? Les liaisons déjà observées restent.`)) { return; }
    this.service.supprimer(s.id).subscribe({
      next: () => this.charger(),
      error: (e: HttpErrorResponse) => { this.erreur = this.message(e); },
    });
  }

  libelleEtat(s: SourceObservateurMeshCore): string {
    if (!s.actif) { return 'arrêté'; }
    switch (s.dernier_etat) {
      case 'CONNECTE': return 'connecté';
      case 'ERREUR': return 'en erreur';
      case 'DECONNECTE': return 'déconnecté';
      default: return 'en attente du service';
    }
  }

  classeEtat(s: SourceObservateurMeshCore): string {
    if (!s.actif) { return ''; }
    return s.dernier_etat === 'CONNECTE' ? 'bon' : s.dernier_etat === 'ERREUR' ? 'faible' : 'moyen';
  }

  private message(e: HttpErrorResponse): string {
    if (e.status === 403) { return "Réservé à l'administrateur de la plateforme."; }
    if (e.status === 400 && e.error && typeof e.error === 'object') {
      return Object.entries(e.error).map(([champ, v]) => `${champ} : ${Array.isArray(v) ? v.join(' ') : v}`).join(' — ');
    }
    return 'Enregistrement impossible pour le moment.';
  }
}
