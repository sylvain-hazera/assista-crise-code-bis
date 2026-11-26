import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subject, debounceTime, distinctUntilChanged, switchMap } from 'rxjs';

import { environment } from '../../../environments/environment';
import { AuthService } from '../../auth/services/auth.service';
import { Commune, LocationService } from '../../services/location.service';

export interface EchelonEtendue { code: string; libelle: string; territoire: string; }

export interface DemandeAdhesion {
  id: string; nom: string; activite: string; commune_code: string; commune_nom: string; echelon: string;
  echelon_libelle: string; territoire: string; agrement: string; statut: string; statut_libelle: string;
  motif_refus: string; date_demande: string; institution: string | null;
}

/**
 * « Faire rejoindre mon association » (26/11/2026) : une association qui existe déjà demande à
 * rejoindre le réseau — AASC ou non (FCBA 33, signaleurs radio). Son nom, ce qu'elle fait, la
 * commune de son siège et jusqu'où elle intervient, sur une échelle comptée depuis le siège :
 * commune, intercommunalité, département, région, zone, national. L'administrateur valide ; le
 * demandeur devient le bureau de l'association.
 */
@Component({
  selector: 'app-rejoindre-association',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './rejoindre-association.component.html',
  styleUrl: './rejoindre-association.component.scss',
})
export class RejoindreAssociationComponent implements OnInit {
  connecte = false;
  demande: DemandeAdhesion | null = null;
  charge = false;
  erreur = '';
  envoi = false;

  nom = '';
  activite = '';
  rechercheCommune = '';
  communes: Commune[] = [];
  commune: Commune | null = null;
  echelons: EchelonEtendue[] = [];
  echelon = 'COMMUNE';
  agree = false;
  agrement = '';
  fonction = '';
  telephone = '';

  private readonly url = `${environment.apiUrl}/associations/`;
  private readonly frappe = new Subject<string>();

  constructor(private http: HttpClient, private auth: AuthService, private lieux: LocationService) {}

  ngOnInit(): void {
    this.connecte = this.auth.isLoggedIn();
    this.frappe.pipe(debounceTime(250), distinctUntilChanged(), switchMap(q => this.lieux.searchCommunesByName(q)))
      .subscribe(c => this.communes = c.slice(0, 8));
    this.chargerEchelons('');
    if (!this.connecte) { this.charge = true; return; }
    this.http.get<{ demande: DemandeAdhesion | null }>(`${this.url}demandes/`).subscribe({
      next: (r) => { this.demande = r.demande; this.charge = true; },
      error: () => { this.charge = true; },
    });
  }

  chercher(texte: string): void {
    this.rechercheCommune = texte;
    this.commune = null;
    this.frappe.next(texte);
  }

  choisirCommune(c: Commune): void {
    this.commune = c;
    this.rechercheCommune = `${c.name}${c.codePostal ? ' (' + c.codePostal + ')' : ''}`;
    this.communes = [];
    this.chargerEchelons(c.code);
  }

  private chargerEchelons(commune: string): void {
    this.http.get<{ echelons: EchelonEtendue[] }>(`${this.url}etendue/`, { params: commune ? { commune } : {} })
      .subscribe({ next: (r) => this.echelons = r.echelons, error: () => {} });
  }

  /** Une nouvelle demande est possible après un refus. */
  get peutDeposer(): boolean { return !this.demande || this.demande.statut === 'REFUSEE'; }

  envoyer(): void {
    if (!this.nom.trim() || !this.activite.trim()) { this.erreur = 'Indiquez le nom de l\'association et ce qu\'elle fait.'; return; }
    if (!this.commune) { this.erreur = 'Choisissez la commune du siège dans la liste.'; return; }
    if (this.agree && !this.agrement.trim()) { this.erreur = 'Précisez l\'agrément (types et numéro), ou décochez la case.'; return; }
    this.erreur = '';
    this.envoi = true;
    this.http.post<DemandeAdhesion>(`${this.url}demandes/`, {
      nom: this.nom.trim(), activite: this.activite.trim(), commune_code: this.commune.code, echelon: this.echelon,
      agrement: this.agree ? this.agrement.trim() : '', fonction: this.fonction.trim(), telephone: this.telephone.trim(),
    }).subscribe({
      next: (d) => { this.envoi = false; this.demande = d; },
      error: (err) => { this.envoi = false; this.erreur = err?.error?.detail || 'La demande n\'a pas pu être envoyée.'; },
    });
  }
}
