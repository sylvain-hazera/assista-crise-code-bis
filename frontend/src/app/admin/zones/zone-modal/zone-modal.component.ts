import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { ZoneService } from '../../../services/zone.service';
import { LocationService, Commune } from '../../../services/location.service';
import { Zone } from '../../../shared/models/zone.model';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';
import { ZoneMapComponent } from '../../../shared/components/common/zone-map/zone-map.component';

/**
 * Créer/éditer une zone nommée (voir Zone) — contrairement au patron "PATCH immédiat par
 * action" de teams.component (zone déjà existante), une zone en création n'a pas encore d'id :
 * communes/zone_precise sont accumulées localement puis envoyées en un seul submit, aussi bien
 * en création qu'en édition (plus simple, un seul chemin pour les deux cas).
 */
@Component({
  selector: 'app-zone-modal',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, TagSearchInputComponent, ZoneMapComponent],
  templateUrl: './zone-modal.component.html',
  styleUrl: './zone-modal.component.scss',
})
export class ZoneModalComponent implements OnChanges {
  @Input() zone: Zone | null = null; // null = création

  @Output() saved = new EventEmitter<Zone>();
  @Output() closed = new EventEmitter<void>();

  form!: FormGroup;
  communes: string[] = [];
  communeNoms: Record<string, string> = {};
  communePostaux: Record<string, string> = {};
  zonePreciseWkt: string | null = null;
  saving = false;
  errorMessage = '';

  communeSearchFn = (q: string) => this.locationService.searchCommunesByName(q);

  constructor(
    private fb: FormBuilder,
    private zoneService: ZoneService,
    private locationService: LocationService,
  ) {
    this.buildForm();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['zone']) {
      this.buildForm();
    }
  }

  private buildForm(): void {
    this.form = this.fb.group({
      nom: [this.zone?.nom ?? '', Validators.required],
      description: [this.zone?.description ?? ''],
    });
    this.communes = [...(this.zone?.communes ?? [])];
    this.communeNoms = {};
    this.communePostaux = {};
    this.communes.forEach(code => {
      this.locationService.getCommuneName(code).subscribe(c => {
        this.communeNoms[c.code] = c.name;
        if (c.codePostal) this.communePostaux[c.code] = c.codePostal;
      });
    });
    this.zonePreciseWkt = this.zone?.zone_precise ?? null;
  }

  get isEdit(): boolean {
    return !!this.zone;
  }

  get initialZoneGeojson() {
    return this.zone?.zone_precise_geojson ?? null;
  }

  addCommune(commune: Commune): void {
    if (this.communes.includes(commune.code)) return;
    this.communeNoms[commune.code] = commune.name;
    if (commune.codePostal) this.communePostaux[commune.code] = commune.codePostal;
    this.communes = [...this.communes, commune.code];
  }

  removeCommune(code: string): void {
    this.communes = this.communes.filter(c => c !== code);
  }

  onZoneChange(wkt: string | null): void {
    this.zonePreciseWkt = wkt;
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { nom, description } = this.form.getRawValue();
    const payload = {
      nom,
      description: description || undefined,
      communes: this.communes,
      zone_precise: this.zonePreciseWkt,
    };

    this.saving = true;
    this.errorMessage = '';

    const request$ = this.isEdit
      ? this.zoneService.update(this.zone!.id, payload)
      : this.zoneService.create(payload);

    request$.subscribe({
      next: (result) => {
        this.saving = false;
        this.saved.emit(result);
      },
      error: (err) => {
        this.saving = false;
        this.errorMessage = err.error?.detail || "Impossible d'enregistrer cette zone.";
      },
    });
  }

  close(): void {
    this.closed.emit();
  }
}
