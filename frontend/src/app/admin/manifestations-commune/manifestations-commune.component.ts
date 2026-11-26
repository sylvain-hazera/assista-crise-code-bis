import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { environment } from '../../../environments/environment';
import { MinimapComponent } from '../../shared/components/common/minimap/minimap.component';

export interface LigneCommune {
  element: string; libelle: string; explication: string; reserve_mairie: boolean; origine: string | null;
  statut: string | null; statut_libelle: string; en_vigueur: boolean; crise: string | null;
}

export interface PartageMairie {
  id: string; commune_code: string; mairie: string | null; invitation_libelle: string; lignes: LigneCommune[];
  manifestation: { id: string; titre: string; type_libelle: string; lieu: string; organisateur: string; debut: string;
                   fin: string; statut: string; statut_libelle: string; association: string };
  referent_nom: string; referent_telephone: string; consignes: string; arrete: string; en_vigueur: boolean;
  crises_ouvertes: { id: string; nom: string }[];
  /** Les points placés de la manifestation (PC, signaleurs). */
  points?: { intitule: string; type_point: string | null; type_point_libelle: string; latitude: number; longitude: number }[];
}

/**
 * « Manifestations sur ma commune » (26/11/2026) : ce que les associations organisent sur la
 * commune, et le tableau de ce qu'elles demandent à voir. La mairie accepte ou refuse chaque
 * demande, et peut ouvrir d'elle-même, au cas par cas, ce qu'une association ne demande jamais :
 * intervenir sur une crise, le plan communal de sauvegarde, le registre des personnes vulnérables.
 * Rien ne vaut au-delà du lendemain de la manifestation.
 */
@Component({
  selector: 'app-manifestations-commune',
  standalone: true,
  imports: [CommonModule, FormsModule, MinimapComponent],
  templateUrl: './manifestations-commune.component.html',
  styleUrl: './manifestations-commune.component.scss',
})
export class ManifestationsCommuneComponent implements OnInit {
  partages: PartageMairie[] = [];
  charge = false;
  erreur = '';
  message = '';
  /** Crise choisie pour « intervenir », par partage. */
  criseChoisie: Record<string, string> = {};

  private readonly url = `${environment.apiUrl}/manifestations-commune/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.http.get<{ partages: PartageMairie[] }>(this.url).subscribe({
      next: (r) => { this.partages = r.partages; this.charge = true; },
      error: (err) => { this.charge = true; this.erreur = err?.error?.detail || 'Les manifestations n\'ont pas pu être chargées.'; },
    });
  }

  private remplacer(p: PartageMairie, message: string): void {
    this.partages = this.partages.map(x => x.id === p.id ? p : x);
    this.message = message;
    this.erreur = '';
  }

  geste(p: PartageMairie, l: LigneCommune, geste: 'accepter' | 'refuser' | 'retirer' | 'offrir'): void {
    const corps: Record<string, string> = { geste, element: l.element };
    if (geste === 'offrir' && l.element === 'INTERVENTION_CRISE') {
      const crise = this.criseChoisie[p.id] || p.crises_ouvertes[0]?.id;
      if (!crise) { this.erreur = 'Aucune crise ouverte sur votre commune.'; return; }
      corps['crise'] = crise;
    }
    if (geste === 'offrir' && !confirm(`Ouvrir à ${p.manifestation.association} : ${l.libelle.toLowerCase()} ?\n\n${l.explication}`)) return;
    this.http.post<PartageMairie>(`${this.url}${p.id}/`, corps).subscribe({
      next: (r) => this.remplacer(r, `${l.libelle} : ${geste === 'refuser' ? 'refusé' : geste === 'retirer' ? 'retiré' : 'ouvert'}.`),
      error: (err) => this.erreur = err?.error?.detail || 'La réponse n\'a pas pu être enregistrée.',
    });
  }

  enregistrer(p: PartageMairie): void {
    this.http.patch<PartageMairie>(`${this.url}${p.id}/`, {
      referent_nom: p.referent_nom, referent_telephone: p.referent_telephone, consignes: p.consignes,
    }).subscribe({
      next: (r) => this.remplacer(r, 'Informations enregistrées.'),
      error: (err) => this.erreur = err?.error?.detail || 'Les informations n\'ont pas pu être enregistrées.',
    });
  }

  joindreArrete(p: PartageMairie, evenement: Event): void {
    const fichier = (evenement.target as HTMLInputElement).files?.[0];
    if (!fichier) return;
    const donnees = new FormData();
    donnees.append('fichier', fichier);
    this.http.post<PartageMairie>(`${environment.apiUrl}/manifestations/partages/${p.id}/arrete/`, donnees).subscribe({
      next: (r) => this.remplacer(r, 'Arrêté joint.'),
      error: (err) => this.erreur = err?.error?.detail || 'L\'arrêté n\'a pas pu être joint.',
    });
  }

  demandees(p: PartageMairie): LigneCommune[] { return p.lignes.filter(l => !l.reserve_mairie); }
  reservees(p: PartageMairie): LigneCommune[] { return p.lignes.filter(l => l.reserve_mairie); }

  /** Dates en français, quelle que soit la langue d'Angular (26/11/2026 : « Thursday » s'affichait). */
  jourLong(iso: string): string {
    return new Intl.DateTimeFormat('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(iso));
  }
  moisCourt(iso: string): string {
    return new Intl.DateTimeFormat('fr-FR', { month: 'short' }).format(new Date(iso)).replace('.', '');
  }

  /** La carte des points : le PC au centre (marqueur rouge), les autres autour. */
  carte(p: PartageMairie): { latitude: number; longitude: number; points: { latitude: number; longitude: number; label: string }[] } | null {
    const pts = p.points ?? [];
    if (!pts.length) return null;
    const centre = pts.find(x => x.type_point === 'PC_MANIFESTATION') ?? pts[0];
    return { latitude: centre.latitude, longitude: centre.longitude,
      points: pts.filter(x => x !== centre).map(x => ({ latitude: x.latitude, longitude: x.longitude,
        label: `${x.intitule}${x.type_point_libelle ? ' (' + x.type_point_libelle + ')' : ''}` })) };
  }
}
