import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';

import { SatelliteService } from '../../services/satellite.service';
import { LigneSupervision } from '../../shared/models/satellite.model';

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
export class SupervisionPcCriseComponent implements OnInit {

  groupes: GroupeCrise[] = [];
  loading = true;
  errorMessage = '';

  constructor(private service: SatelliteService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.service.supervision().subscribe({
      next: (lignes) => { this.groupes = this.grouperParCrise(lignes); this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger la supervision.'; this.loading = false; },
    });
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
}
