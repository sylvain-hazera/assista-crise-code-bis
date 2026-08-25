import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { GeolocationService } from '../../../../services/geolocation.service';
import { AddressResult } from '../../../models/address-result.model';

@Component({
  selector: 'app-address-picker',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './address-picker.component.html',
  styleUrls: ['./address-picker.component.scss']
})
export class AddressPickerComponent implements OnInit {
  @Input() label = 'Adresse';
  @Input() placeholder = 'Rechercher une adresse…';
  @Input() required = false;
  /** Émet l'adresse choisie, ou null si le champ est vidé après une sélection. */
  @Output() addressSelected = new EventEmitter<AddressResult | null>();

  query = '';
  suggestions: AddressResult[] = [];
  showDropdown = false;
  isSearching = false;
  hasSelection = false;

  private userPosition: { lat: number; lon: number } | null = null;
  private searchDebounce: ReturnType<typeof setTimeout> | null = null;

  constructor(private geolocationService: GeolocationService) {}

  ngOnInit(): void {
    // Demande silencieuse : le navigateur affiche sa propre popup de permission. En cas de
    // refus/échec on continue simplement sans biais géographique — jamais bloquant, jamais
    // de préremplissage automatique du champ (l'utilisateur n'est pas forcément chez lui).
    this.geolocationService.requestLocation()
      .then(coords => { this.userPosition = { lat: coords.latitude, lon: coords.longitude }; })
      .catch(() => { /* pas de position disponible : recherche sans biais, comportement normal */ });
  }

  onQueryChange(): void {
    this.hasSelection = false;
    this.addressSelected.emit(null);

    if (this.searchDebounce) clearTimeout(this.searchDebounce);

    const q = this.query.trim();
    if (q.length < 3) {
      this.suggestions = [];
      this.showDropdown = false;
      return;
    }

    this.searchDebounce = setTimeout(() => this.runSearch(q), 300);
  }

  private runSearch(query: string): void {
    this.isSearching = true;
    const bias = this.userPosition ?? undefined;
    this.geolocationService.searchAddresses(query, bias).subscribe({
      next: (res) => {
        this.suggestions = (res?.features ?? []).map((f: any) => this.toAddressResult(f));
        this.showDropdown = this.suggestions.length > 0;
        this.isSearching = false;
      },
      error: () => {
        this.suggestions = [];
        this.isSearching = false;
      },
    });
  }

  selectSuggestion(addr: AddressResult): void {
    this.query = addr.label;
    this.suggestions = [];
    this.showDropdown = false;
    this.hasSelection = true;
    this.addressSelected.emit(addr);
  }

  /** Préremplit le champ avec l'adresse actuelle de l'utilisateur — action explicite (bouton),
   * jamais automatique : utile quand il signale depuis l'endroit concerné (ex: un arbre sur la
   * chaussée), pas pertinent s'il déclare depuis chez lui pour un tiers. */
  useMyLocation(): void {
    this.isSearching = true;
    this.geolocationService.requestLocation()
      .then(coords => {
        this.userPosition = { lat: coords.latitude, lon: coords.longitude };
        this.geolocationService.reverseGeocode(coords.latitude, coords.longitude).subscribe({
          next: (res) => {
            const feature = res?.features?.[0];
            this.isSearching = false;
            if (feature) {
              this.selectSuggestion(this.toAddressResult(feature));
            }
          },
          error: () => { this.isSearching = false; },
        });
      })
      .catch(() => { this.isSearching = false; });
  }

  private toAddressResult(feature: any): AddressResult {
    const p = feature.properties ?? {};
    const [lon, lat] = feature.geometry?.coordinates ?? [null, null];
    return {
      label: p.label ?? '',
      street: p.name ?? '',
      postcode: p.postcode ?? '',
      city: p.city ?? '',
      citycode: p.citycode ?? '',
      latitude: lat,
      longitude: lon,
    };
  }
}
