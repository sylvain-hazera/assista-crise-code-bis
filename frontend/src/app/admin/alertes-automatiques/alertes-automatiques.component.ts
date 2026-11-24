import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import {
  AlerteNaturelle, AlertesAutomatiquesService, MatriceAlertes, PhenomeneAlerte, RegleAlerte,
} from '../../services/alertes-automatiques.service';

/** Ce que l'écran édite pour une ligne : la règle enregistrée, ou les valeurs conseillées. */
interface Ligne {
  phenomene: PhenomeneAlerte;
  actif: boolean;
  alerte: number;
  exceptionnel: number;
  reglages: Record<string, number>;
  email: boolean;
  radio: boolean;
  nuit: boolean;
  modifiee: boolean;
  enregistree: boolean;
}

/** Alertes automatiques (24/11/2026) : la collectivité règle, phénomène par phénomène, quand
 * être prévenue (application et courriel toujours, radio si exceptionnel) ; chaque alerte reçue
 * mène à une crise ou à une demande de disponibilités, relues avant tout envoi. */
@Component({
  selector: 'app-alertes-automatiques',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './alertes-automatiques.component.html',
  styleUrl: './alertes-automatiques.component.scss',
})
export class AlertesAutomatiquesComponent implements OnInit {
  private service = inject(AlertesAutomatiquesService);
  private router = inject(Router);
  private route = inject(ActivatedRoute, { optional: true });

  matrice: MatriceAlertes | null = null;
  familles: { nom: string; lignes: Ligne[] }[] = [];
  institution: string | null = null;
  chargement = true;
  erreur: string | null = null;
  message: string | null = null;
  enCours: string | null = null;
  ouverte: AlerteNaturelle | null = null;

  readonly libellesReglages: Record<string, string> = { rayon_km: 'Rayon (km)' };

  ngOnInit(): void {
    const parametres = this.route?.snapshot.queryParamMap;
    this.institution = parametres?.get('institution') ?? null;
    this.charger(parametres?.get('alerte') ?? null);
  }

  charger(alerteAOuvrir: string | null = null): void {
    this.chargement = true;
    this.service.matrice(this.institution).subscribe({
      next: (matrice) => {
        this.appliquer(matrice);
        this.chargement = false;
        if (alerteAOuvrir) { this.ouvrirParId(alerteAOuvrir); }
      },
      error: (e) => {
        this.erreur = e?.error?.detail ?? e?.error?.institution ?? 'Impossible de charger les alertes automatiques.';
        this.chargement = false;
      },
    });
  }

  changerInstitution(id: string): void {
    this.institution = id;
    this.ouverte = null;
    this.charger();
  }

  private appliquer(matrice: MatriceAlertes): void {
    this.matrice = matrice;
    this.institution = matrice.institution.id;
    const parFamille = new Map<string, Ligne[]>();
    for (const p of matrice.phenomenes) {
      const valeurs = { ...p.conseille, ...(p.regle?.seuils ?? {}) };
      const reglages: Record<string, number> = {};
      for (const nom of Object.keys(p.reglages)) { reglages[nom] = valeurs[nom]; }
      const ligne: Ligne = {
        phenomene: p, actif: p.regle?.actif ?? false, alerte: valeurs['alerte'], exceptionnel: valeurs['exceptionnel'],
        reglages, email: p.regle?.email ?? true, radio: p.radio_possible && (p.regle?.radio_si_exceptionnel ?? true),
        nuit: p.regle?.silence_nuit ?? true, modifiee: false, enregistree: !!p.regle,
      };
      parFamille.set(p.famille, [...(parFamille.get(p.famille) ?? []), ligne]);
    }
    this.familles = [...parFamille.entries()].map(([nom, lignes]) => ({ nom, lignes }));
  }

  get actives(): number {
    return this.familles.reduce((n, f) => n + f.lignes.filter(l => l.actif).length, 0);
  }

  get total(): number {
    return this.familles.reduce((n, f) => n + f.lignes.length, 0);
  }

  libelleValeur(p: PhenomeneAlerte, valeur: number): string {
    return p.echelle[String(valeur)] ?? `${valeur}`;
  }

  /** Les valeurs qu'un sélecteur propose pour une échelle (couleurs, niveaux). */
  valeursEchelle(p: PhenomeneAlerte): number[] {
    return Object.keys(p.echelle).map(Number).filter(v => v >= p.minimum && v <= p.maximum).sort((a, b) => a - b);
  }

  aUneEchelle(p: PhenomeneAlerte): boolean {
    return Object.keys(p.echelle).length > 0;
  }

  nomsReglages(p: PhenomeneAlerte): string[] {
    return Object.keys(p.reglages);
  }

  toucher(ligne: Ligne): void {
    ligne.modifiee = true;
    this.message = null;
  }

  basculer(ligne: Ligne): void {
    ligne.actif = !ligne.actif;
    this.enregistrer(ligne);
  }

  enregistrer(ligne: Ligne): void {
    if (!this.institution) { return; }
    this.enCours = ligne.phenomene.code;
    this.erreur = null;
    const regle: Partial<RegleAlerte> = {
      actif: ligne.actif, email: ligne.email, radio_si_exceptionnel: ligne.radio, silence_nuit: ligne.nuit,
      seuils: { alerte: Number(ligne.alerte), exceptionnel: Number(ligne.exceptionnel), ...ligne.reglages },
    };
    this.service.enregistrer(this.institution, ligne.phenomene.code, regle).subscribe({
      next: (enregistree) => {
        ligne.modifiee = false;
        ligne.enregistree = true;
        ligne.phenomene.regle = enregistree;
        this.enCours = null;
        this.message = `${ligne.phenomene.libelle} : ${enregistree.actif ? 'alerte active' : 'alerte coupée'}.`;
      },
      error: (e) => {
        this.erreur = e?.error?.seuils ?? 'Enregistrement impossible.';
        this.enCours = null;
      },
    });
  }

  tout(actif: boolean): void {
    if (!this.institution) { return; }
    if (actif && !confirm('Activer toutes les alertes avec les valeurs conseillées ? Les réglages déjà faits sont gardés.')) {
      return;
    }
    this.enCours = 'tout';
    this.service.toutes(this.institution, actif).subscribe({
      next: (matrice) => {
        this.appliquer(matrice);
        this.enCours = null;
        this.message = actif ? 'Toutes les alertes sont actives.' : 'Toutes les alertes sont coupées.';
      },
      error: () => { this.erreur = 'Action impossible.'; this.enCours = null; },
    });
  }

  ouvrir(alerte: AlerteNaturelle): void {
    this.ouverte = this.ouverte?.id === alerte.id ? null : alerte;
  }

  private ouvrirParId(id: string): void {
    const connue = this.matrice?.alertes.find(a => a.id === id);
    if (connue) { this.ouverte = connue; return; }
    this.service.alerte(id).subscribe({ next: (alerte) => this.ouverte = alerte, error: () => {} });
  }

  /** La déclaration de crise habituelle, préremplie : rien n'est créé avant qu'on la valide. */
  ouvrirUneCrise(alerte: AlerteNaturelle): void {
    this.service.preremplirCrise(alerte.id).subscribe({
      next: (p) => this.router.navigate(['/crisis-declaration'], {
        queryParams: {
          type: p.type, titre: p.titre, description: p.description, latitude: p.latitude, longitude: p.longitude,
          alerte: alerte.id,
        },
      }),
      error: () => this.erreur = 'Préparation de la crise impossible.',
    });
  }

  /** Une campagne « Crise à venir » en brouillon, ouverte dans son écran pour relecture. */
  demanderDisponibilites(alerte: AlerteNaturelle): void {
    this.enCours = `dispo-${alerte.id}`;
    this.service.demanderDisponibilites(alerte.id).subscribe({
      next: (maj) => {
        this.enCours = null;
        alerte.campagne = maj.campagne;
        this.router.navigate(['/admin/campagnes-disponibilite'], {
          queryParams: { institution: maj.institution, campagne: maj.campagne },
        });
      },
      error: (e) => {
        this.enCours = null;
        this.erreur = e?.error?.detail ?? 'Préparation de la demande impossible.';
      },
    });
  }
}
