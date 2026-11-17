import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { environment } from '../../../environments/environment';
import { DepartRetourComponent } from '../../shared/components/common/depart-retour/depart-retour.component';

export interface LigneReleve {
  id: string;
  crise: string;
  crise_nom: string;
  equipe: string | null;
  equipe_nom: string;
  parti_le: string;
  rentre_le: string | null;
  depart_de: string;
  retour_a: string;
  hebergement: string;
  /** Complétée ou corrigée à la main, après coup. */
  saisie_manuelle: boolean;
  heures: number | null;
}

export interface Releve {
  du: string;
  au: string;
  lignes: LigneReleve[];
  total_heures: number;
  activite: { quand: string; heure: boolean; source: 'moi' | 'equipe'; equipe: string; quoi: string }[];
  crises: { id: string; nom: string }[];
  equipes: { id: string; nom: string }[];
  lieux: { code: string; libelle: string }[];
}

/** Une ligne en cours de saisie : les champs d'un tableur, en texte local (`AAAA-MM-JJTHH:MM`). */
interface Brouillon {
  id?: string;
  crise: string;
  equipe: string;
  parti_le: string;
  rentre_le: string;
  depart_de: string;
  retour_a: string;
}

/**
 * Mon relevé d'heures (17/11/2026) : ce que j'ai déclaré par « je pars » / « je rentre », et de
 * quoi compléter mes oublis à la main, dans un tableau.
 *
 * À côté, mon activité et celle de mes équipes sur la même période : c'est en relisant « le
 * dossier a été pris en charge à 14 h 10 » qu'on retrouve l'heure à laquelle on est parti.
 *
 * Une ligne complétée ou corrigée à la main est marquée comme telle, ici et dans le relevé que
 * lit l'institution : on ne fait pas passer une correction pour une déclaration du moment.
 */
@Component({
  selector: 'app-mon-releve',
  standalone: true,
  imports: [CommonModule, FormsModule, DepartRetourComponent],
  templateUrl: './mon-releve.component.html',
  styleUrl: './mon-releve.component.scss',
})
export class MonReleveComponent implements OnInit {
  releve: Releve | null = null;
  du = '';
  au = '';
  erreur = '';
  message = '';
  envoi = false;
  /** La ligne en cours d'édition : une nouvelle (sans `id`) ou une existante. */
  brouillon: Brouillon | null = null;
  filtreActivite: 'tout' | 'moi' | 'equipe' = 'tout';

  private readonly url = `${environment.apiUrl}/mon-releve/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    const params: Record<string, string> = {};
    if (this.du) params['du'] = this.du;
    if (this.au) params['au'] = this.au;
    this.http.get<Releve>(this.url, { params }).subscribe({
      next: (releve) => { this.releve = releve; this.du = releve.du; this.au = releve.au; },
      error: (err) => this.erreur = err?.error?.detail || "Le relevé n'a pas pu être chargé.",
    });
  }

  get activite(): Releve['activite'] {
    const toute = this.releve?.activite ?? [];
    return this.filtreActivite === 'tout' ? toute : toute.filter(a => a.source === this.filtreActivite);
  }

  libelleLieu(code: string): string {
    return this.releve?.lieux.find(l => l.code === code)?.libelle.split(' (')[0] ?? '';
  }

  /** ISO du serveur → valeur d'un champ `datetime-local`, à l'heure du poste. */
  enLocal(instant: string | null): string {
    if (!instant) return '';
    const d = new Date(instant);
    const p = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  ajouter(): void {
    const releve = this.releve;
    if (!releve) return;
    this.erreur = '';
    this.brouillon = {
      crise: releve.crises[0]?.id ?? '', equipe: releve.equipes.length === 1 ? releve.equipes[0].id : '',
      parti_le: '', rentre_le: '', depart_de: 'DOMICILE', retour_a: 'DOMICILE',
    };
  }

  modifier(ligne: LigneReleve): void {
    this.erreur = '';
    this.brouillon = {
      id: ligne.id, crise: ligne.crise, equipe: ligne.equipe ?? '',
      parti_le: this.enLocal(ligne.parti_le), rentre_le: this.enLocal(ligne.rentre_le),
      depart_de: ligne.depart_de, retour_a: ligne.retour_a || ligne.depart_de,
    };
  }

  /** Reprend l'heure d'une ligne d'activité dans le champ encore vide de la ligne en cours. */
  reprendre(instant: string): void {
    if (!this.brouillon) return;
    const local = this.enLocal(instant);
    if (!this.brouillon.parti_le) this.brouillon.parti_le = local;
    else this.brouillon.rentre_le = local;
  }

  enregistrer(): void {
    const b = this.brouillon;
    if (!b) return;
    if (!b.parti_le || !b.rentre_le) { this.erreur = 'Indiquez le départ et le retour.'; return; }
    this.envoi = true;
    this.erreur = '';
    const corps = {
      crise: b.crise, equipe: b.equipe || null, depart_de: b.depart_de, retour_a: b.retour_a,
      // Le navigateur convertit l'heure du poste en instant universel : le serveur n'a pas à
      // deviner le fuseau de la personne.
      parti_le: new Date(b.parti_le).toISOString(), rentre_le: new Date(b.rentre_le).toISOString(),
    };
    const envoi = b.id ? this.http.patch(`${this.url}${b.id}/`, corps) : this.http.post(this.url, corps);
    envoi.subscribe({
      next: () => { this.envoi = false; this.brouillon = null; this.message = 'Relevé mis à jour.'; this.charger(); },
      error: (err) => { this.envoi = false; this.erreur = err?.error?.detail || "La ligne n'a pas pu être enregistrée."; },
    });
  }

  supprimer(ligne: LigneReleve): void {
    if (!confirm('Retirer cette ligne de votre relevé ?')) return;
    this.http.delete(`${this.url}${ligne.id}/`).subscribe({
      next: () => this.charger(),
      error: (err) => this.erreur = err?.error?.detail || 'Suppression impossible.',
    });
  }
}
