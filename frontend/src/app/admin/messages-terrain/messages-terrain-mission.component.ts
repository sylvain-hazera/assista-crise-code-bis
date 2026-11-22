import { Component, Input, OnChanges, OnDestroy } from '@angular/core';
import { DatePipe } from '@angular/common';

import { MessageTerrain, MessagesTerrainService } from '../../services/messages-terrain.service';

/**
 * Au poste de commandement, dans la fiche d'une mission (22/11/2026) : le statut de chaque
 * intervenant (« sur place », « disponible »…) et le fil des messages de terrain, relu toutes
 * les 30 secondes. Danger et demande de secours en tête et en rouge.
 */
@Component({
  selector: 'app-messages-terrain-mission',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './messages-terrain-mission.component.html',
  styleUrl: './messages-terrain-mission.component.scss',
})
export class MessagesTerrainMissionComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) missionId!: string;

  statuts: MessageTerrain[] = [];
  fil: MessageTerrain[] = [];
  private minuterie: ReturnType<typeof setInterval> | null = null;

  readonly canaux: Record<string, string> = { DONNEES: 'données', MESHTASTIC: 'radio Meshtastic', MESHCORE: 'radio MeshCore' };

  constructor(private service: MessagesTerrainService) {}

  ngOnChanges(): void {
    this.relire();
    if (this.minuterie) clearInterval(this.minuterie);
    this.minuterie = setInterval(() => this.relire(), 30_000);
  }

  ngOnDestroy(): void { if (this.minuterie) clearInterval(this.minuterie); }

  get prioritaires(): MessageTerrain[] { return this.fil.filter(m => m.prioritaire).slice(0, 5); }

  relire(): void {
    if (!this.missionId) return;
    this.service.statuts(this.missionId).subscribe({ next: s => this.statuts = s, error: () => {} });
    this.service.fil(this.missionId).subscribe({ next: f => this.fil = f, error: () => {} });
  }

  carte(m: MessageTerrain): string | null {
    return m.latitude && m.longitude ? `https://www.openstreetmap.org/?mlat=${m.latitude}&mlon=${m.longitude}#map=17/${m.latitude}/${m.longitude}` : null;
  }
}
