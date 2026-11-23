import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import { AdministrationMeshtasticService } from '../../services/administration-meshtastic.service';
import {
  DiagnosticLiaisons, RelaisSourd,
} from '../../shared/models/administration-meshtastic.model';

/** Diagnostic des liaisons radio : ce que les mesures disent de l'état du réseau.
 *
 * Quatre conclusions, de la plus actionnable à la plus indicative : relais sourds, liaisons à
 * sens unique, liaisons déséquilibrées, nœuds inaudibles.
 *
 * Cette page a une responsabilité particulière : **une conclusion fausse envoie quelqu'un sur un
 * point haut**. Elle affiche donc systématiquement ce qui permet de la juger — l'origine de la
 * preuve, le nombre d'observations, et si la puissance d'émission était connue. Une conclusion
 * non corrigée en puissance est affichée comme telle, jamais comme un fait établi.
 *
 * Le calcul est lourd (il relit une semaine d'observations) : il se déclenche au chargement et
 * sur demande explicite, jamais en boucle. */
@Component({
  selector: 'app-diagnostic-radio',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './diagnostic-radio.component.html',
  styleUrl: './diagnostic-radio.component.scss',
})
export class DiagnosticRadioComponent implements OnInit {

  diagnostic: DiagnosticLiaisons | null = null;
  chargement = true;
  erreur: string | null = null;

  /** Relais sourd dont on déplie les mesures. */
  sourdDeplie: number | string | null = null;

  constructor(private service: AdministrationMeshtasticService) {}

  ngOnInit(): void {
    this.calculer();
  }

  /** Le réseau analysé (23/11/2026) : Meshtastic, ou MeshCore et tout ce qu'en rapportent les
   * observateurs MQTT, CoreScope et nos companions. */
  protocole: 'meshtastic' | 'meshcore' = 'meshtastic';

  choisirProtocole(p: 'meshtastic' | 'meshcore'): void {
    if (p === this.protocole) return;
    this.protocole = p;
    this.diagnostic = null;
    this.sourdDeplie = null;
    this.calculer();
  }

  calculer(): void {
    this.chargement = true;
    this.erreur = null;
    (this.protocole === 'meshcore' ? this.service.diagnosticMeshCore() : this.service.diagnostic()).subscribe({
      next: (diagnostic) => { this.diagnostic = diagnostic; this.chargement = false; },
      error: (e: HttpErrorResponse) => {
        this.erreur = e.status === 403
          ? 'Le diagnostic radio est réservé aux acteurs institutionnels.'
          : 'Impossible de calculer le diagnostic.';
        this.chargement = false;
      },
    });
  }

  basculerSourd(ident: number | string): void {
    this.sourdDeplie = this.sourdDeplie === ident ? null : ident;
  }

  /** L'identité d'un nœud : numéro Meshtastic, ou clé publique MeshCore. */
  ident(noeud: { node_num?: number; pubkey?: string }): number | string {
    return noeud.node_num ?? noeud.pubkey ?? '';
  }

  hexa(ident: number | string): string {
    return typeof ident === 'string'
      ? ident.slice(0, 12)
      : `!${ident.toString(16).padStart(8, '0')}`;
  }

  /** Ce que chaque origine de preuve vaut, en clair. */
  readonly libellesSource: Record<string, { libelle: string; aide: string }> = {
    RF: { libelle: 'réception directe', aide: 'Reçu et mesuré (SNR) par une passerelle, un observateur ou un companion' },
    VOISINAGE: { libelle: 'voisinage', aide: 'Déclaré par le nœud dans son relevé de voisins' },
    TRACEROUTE: { libelle: 'traceroute', aide: "Saut d'un traceroute : ne prouve pas que le nœud rapporte ce qu'il entend" },
    CHEMIN: { libelle: 'chemin', aide: "Relais consécutifs du chemin d'un paquet (observateurs MQTT, CoreScope) : pas de SNR, preuve plus faible qu'une réception directe" },
  };

  /** Vrai quand le réseau ne porte aucune conclusion : évite d'afficher quatre tableaux vides
   * sans dire pourquoi. */
  get aucuneConclusion(): boolean {
    const d = this.diagnostic;
    return !!d && !d.sourds.length && !d.sens_unique.length
      && !d.desequilibrees.length && !d.inaudibles.length;
  }

  /** Mesure réciproque ou simple borne basse. La distinction compte : une borne basse dit
   * seulement « il l'a reçu sous son seuil de démodulation », pas de combien. */
  libelleMesure(mesure: RelaisSourd['mesures'][number]): string {
    return mesure.borne
      ? `au moins ${mesure.ecart_db} dB (il ne l'a jamais rapporté)`
      : `${mesure.ecart_db} dB`;
  }
}
