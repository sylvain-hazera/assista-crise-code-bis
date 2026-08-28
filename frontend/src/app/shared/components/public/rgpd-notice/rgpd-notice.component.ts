import { Component, Input } from '@angular/core';
import { RouterLink } from '@angular/router';

/**
 * Mention d'information RGPD affichée sur chaque formulaire public collectant des données
 * personnelles (article 13 RGPD : information de la personne au moment de la collecte, pas
 * seulement via une page RGPD isolée jamais consultée). `purpose` précise la finalité propre
 * à ce formulaire dans la phrase générique.
 */
@Component({
  selector: 'app-rgpd-notice',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './rgpd-notice.component.html',
  styleUrls: ['./rgpd-notice.component.scss'],
})
export class RgpdNoticeComponent {
  @Input({ required: true }) purpose!: string;
}
