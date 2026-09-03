import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ZoneService } from '../../services/zone.service';
import { Zone } from '../../shared/models/zone.model';
import { ZoneModalComponent } from './zone-modal/zone-modal.component';

/**
 * Catalogue des zones nommées de mon institution (voir Zone) — support du dispositif
 * pré-enregistré (Plan) : une équipe/un point peut en référencer une pour dire "je couvre le
 * Quartier Nord" sans redessiner sa géométrie à chaque fois.
 */
@Component({
  selector: 'app-zones',
  standalone: true,
  imports: [CommonModule, FormsModule, ZoneModalComponent],
  templateUrl: './zones.component.html',
  styleUrl: './zones.component.scss',
})
export class ZonesComponent implements OnInit {
  zones: Zone[] = [];
  searchQuery = '';
  isLoading = true;
  errorMessage = '';

  modalOpen = false;
  editingZone: Zone | null = null;

  constructor(private zoneService: ZoneService) {}

  ngOnInit(): void {
    this.load();
  }

  private load(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.zoneService.getAll().subscribe({
      next: (zones) => {
        this.zones = zones;
        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = 'Impossible de charger les zones.';
        this.isLoading = false;
      },
    });
  }

  get filteredZones(): Zone[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.zones;
    return this.zones.filter(z => z.nom.toLowerCase().includes(q));
  }

  openCreateModal(): void {
    this.editingZone = null;
    this.modalOpen = true;
  }

  openEditModal(zone: Zone): void {
    this.editingZone = zone;
    this.modalOpen = true;
  }

  closeModal(): void {
    this.modalOpen = false;
    this.editingZone = null;
  }

  onSaved(): void {
    this.closeModal();
    this.load();
  }

  deleteZone(zone: Zone, event: Event): void {
    event.stopPropagation();
    if (!confirm(`Retirer la zone « ${zone.nom} » ?`)) return;
    this.zoneService.delete(zone.id).subscribe({
      next: () => this.load(),
      error: () => this.errorMessage = 'Impossible de retirer cette zone.',
    });
  }
}
