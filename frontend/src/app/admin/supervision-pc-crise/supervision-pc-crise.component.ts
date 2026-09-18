import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';

import { SatelliteService } from '../../services/satellite.service';
import { LigneSupervision } from '../../shared/models/satellite.model';
import { pollWhileVisible } from '../../shared/utils/polling.util';

const INTERVALLE_POLLING_SUPERVISION_MS = 30_000;

interface GroupeCrise {
  crise_id: string;
  crise_nom: string;
  lignes: LigneSupervision[];
}

/** Supervision inter-collectivités des PC Crise (communes voisines -> préfecture) — voir le
 * cadrage "Chantier B" section 5. Une commune voit ses voisines proches, un EPCI/département/
 * région voit automatiquement ses communes membres (voir SatelliteViewSet.supervision côté
 * API) : pour chaque crise active dans ce périmètre, l'état Actif/Inactif/Perdu du satellite
 * de l'institution actrice, et ses contacts de secours dès qu'il n'est pas joignable. */
@Component({
  selector: 'app-supervision-pc-crise',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './supervision-pc-crise.component.html',
  styleUrl: './supervision-pc-crise.component.scss',
})
export class SupervisionPcCriseComponent implements OnInit, OnDestroy {

  groupes: GroupeCrise[] = [];
  loading = true;
  errorMessage = '';

  private pollingSub?: Subscription;
  private premierChargement = true;

  constructor(private service: SatelliteService) {}

  ngOnInit(): void {
    // Cette vue sert justement à repérer un PC Crise qui vient de décrocher — un chargement
    // figé au montage serait contradictoire avec son objet même. Suspendu en arrière-plan,
    // rattrape immédiatement au retour au premier plan (voir pollWhileVisible). Un poll raté
    // après le tout premier chargement réussi n'efface pas les données déjà affichées — au pire
    // prochain poll réussira.
    this.pollingSub = pollWhileVisible(() => this.service.supervision(), INTERVALLE_POLLING_SUPERVISION_MS).subscribe({
      next: (lignes) => {
        this.groupes = this.grouperParCrise(lignes);
        this.loading = false;
        this.errorMessage = '';
        this.premierChargement = false;
      },
      error: () => {
        if (!this.premierChargement) return;
        this.errorMessage = 'Impossible de charger la supervision.';
        this.loading = false;
        this.premierChargement = false;
      },
    });
  }

  ngOnDestroy(): void {
    this.pollingSub?.unsubscribe();
  }

  private grouperParCrise(lignes: LigneSupervision[]): GroupeCrise[] {
    const parId = new Map<string, GroupeCrise>();
    for (const ligne of lignes) {
      let groupe = parId.get(ligne.crise_id);
      if (!groupe) {
        groupe = { crise_id: ligne.crise_id, crise_nom: ligne.crise_nom, lignes: [] };
        parId.set(ligne.crise_id, groupe);
      }
      groupe.lignes.push(ligne);
    }
    return Array.from(parId.values());
  }

  etatClass(ligne: LigneSupervision): string {
    if (ligne.satellite_etat === 'ACTIF') return 'statut-ok';
    if (ligne.satellite_etat === 'PERDU') return 'statut-erreur';
    if (ligne.satellite_etat === 'INACTIF') return 'statut-attention';
    return 'statut-inconnu';
  }

  etatLabel(ligne: LigneSupervision): string {
    if (ligne.satellite_etat === 'ACTIF') return 'Actif';
    if (ligne.satellite_etat === 'INACTIF') return 'Inactif';
    if (ligne.satellite_etat === 'PERDU') return 'Perdu';
    return 'Pas de satellite';
  }

  // Seuil d'alerte "personne ne suit visiblement cette crise" — toutes les crises listées ici
  // sont ouvertes par construction (voir SatelliteViewSet.supervision, filtre end_date__isnull),
  // donc pas besoin de vérifier ce point en plus : seule l'ancienneté de l'activité compte.
  private static readonly SEUIL_ALERTE_HEURES = 8;

  /** Vrai si personne de cette institution n'a d'activité récente sur la plateforme (aucune
   * ligne de main courante depuis SEUIL_ALERTE_HEURES) — pas une "session navigateur ouverte"
   * au sens strict (l'authentification JWT de ce projet ne garde aucune notion de session
   * serveur), mais le meilleur proxy disponible : une personne qui consulte ou modifie quoi que
   * ce soit sur le site laisse une trace récente, voir derniere_activite_humaine. */
  activiteWarning(ligne: LigneSupervision): boolean {
    if (!ligne.derniere_activite_humaine) return true;
    const heures = (Date.now() - new Date(ligne.derniere_activite_humaine).getTime()) / 3_600_000;
    return heures >= SupervisionPcCriseComponent.SEUIL_ALERTE_HEURES;
  }
}
