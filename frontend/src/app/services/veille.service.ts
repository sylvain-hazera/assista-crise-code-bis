import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  AntennesIndisponibles, ArretesCirculation, Circulation, QualiteAir, VentPrevu, ConfigurationAlerteFeu, ConfigurationAlerteVigilance, FoyersActifs, HauteursEau, NiveauxMer, Defibrillateurs, Radioactivite, Seismes, Volcans, EvenementsRoutiers, MeteoForets, ObservationsMeteo, RafalesPrevues, PluiePrevue, PrecipitationsHiver,
  RestrictionsEau, RisqueAvalanche, SanteUrgences, StationsCarburant, VigilanceCrues, VigilanceMeteo, ZonesBrulees, OragesRadar, PluieRadar, FeuxSuivis, PotentielOrageFeu,
} from '../shared/models/veille.model';

/** Zone à regarder : un rectangle (la carte), un point et un rayon, ou rien — le serveur prend
 * alors la commune de l'institution de l'appelant. */
export interface EmpriseVeille {
  bbox?: [number, number, number, number];
  lat?: number;
  lon?: number;
  rayon_km?: number;
}

/** Lecture de la veille du territoire. Tout vient de NOTRE serveur, qui tient une copie des
 * sources de l'État : ce service ne doit jamais appeler un service extérieur. */
@Injectable({ providedIn: 'root' })
export class VeilleService {

  private api = environment.apiUrl;

  constructor(private http: HttpClient) {}

  vigilance(departement?: string): Observable<VigilanceMeteo> {
    const params: Record<string, string> = departement ? { departement } : {};
    return this.http.get<VigilanceMeteo>(`${this.api}/vigilance-meteo/`, { params });
  }

  /** Adresse de la carte nationale officielle, servie par notre serveur. */
  vignetteUrl(echeance: string): string {
    return `${this.api}/vigilance-meteo/vignette/${echeance}/`;
  }

  evenementsRoutiers(emprise: EmpriseVeille = {}): Observable<EvenementsRoutiers> {
    return this.http.get<EvenementsRoutiers>(`${this.api}/evenements-routiers/`, { params: this.params(emprise) });
  }

  stationsCarburant(emprise: EmpriseVeille = {}): Observable<StationsCarburant> {
    return this.http.get<StationsCarburant>(`${this.api}/stations-carburant/`, { params: this.params(emprise) });
  }

  /** Dernières mesures des stations Météo-France de l'emprise. */
  observationsMeteo(emprise: EmpriseVeille = {}): Observable<ObservationsMeteo> {
    return this.http.get<ObservationsMeteo>(`${this.api}/observations-meteo/`, { params: this.params(emprise) });
  }

  /** Quarts d'heure pour lesquels une image de pluie prévue est disponible. */
  pluiePrevue(): Observable<PluiePrevue> {
    return this.http.get<PluiePrevue>(`${this.api}/pluie-prevue/`);
  }

  /** Adresse de l'image d'une échéance, servie par notre serveur. */
  imagePluieUrl(echeance: string): string {
    return `${this.api}/pluie-prevue/image/?echeance=${encodeURIComponent(echeance)}`;
  }

  /** Éclairs vus par le satellite MTG, en GeoJSON, pour la carte (60 dernières minutes). */
  foudre(emprise: EmpriseVeille, minutes = 60): Observable<GeoJSON.FeatureCollection & { derniere_donnee: string | null; perime: boolean }> {
    return this.http.get<GeoJSON.FeatureCollection & { derniere_donnee: string | null; perime: boolean }>(
      `${this.api}/foudre/`, { params: { ...this.params(emprise), minutes: String(minutes) } });
  }

  /** Impacts Blitzortung, à titre indicatif, en GeoJSON (60 dernières minutes). */
  blitzortung(emprise: EmpriseVeille, minutes = 60): Observable<GeoJSON.FeatureCollection & { mention: string; perime: boolean }> {
    return this.http.get<GeoJSON.FeatureCollection & { mention: string; perime: boolean }>(
      `${this.api}/blitzortung/`, { params: { ...this.params(emprise), minutes: String(minutes) } });
  }

  /** Orages et pluies intenses autour de la commune de l'institution (radar, toutes les 5 min). */
  orages(emprise?: EmpriseVeille): Observable<OragesRadar> {
    return this.http.get<OragesRadar>(`${this.api}/orages/`, emprise ? { params: this.params(emprise) } : {});
  }

  /** Toutes les cellules orageuses du pays (sans cumuls ni foudre, qui sont par territoire). */
  oragesFrance(): Observable<OragesRadar> {
    return this.http.get<OragesRadar>(`${this.api}/orages/`, { params: { france: '1' } });
  }

  /** Dernière pluie observée par le radar : heure, coins et légende de l'image. */
  pluieRadar(): Observable<PluieRadar> {
    return this.http.get<PluieRadar>(`${this.api}/orages/radar/`);
  }

  imagePluieRadarUrl(heure: string): string {
    return `${this.api}/orages/radar/image/?heure=${encodeURIComponent(heure)}`;
  }

  /** Image estimée (+minutes) ; `base` (l'image observée d'origine) rend l'adresse unique. */
  imagePluieEstimeeUrl(minutes: number, base: string): string {
    return `${this.api}/orages/radar/image/?estimee=${minutes}&base=${encodeURIComponent(base)}`;
  }

  /** Quarts d'heure pour lesquels une image de rafales prévues est disponible, et la légende.
   * `ici` demande en plus le palier prévu sur la commune de l'institution de l'appelant. */
  rafalesPrevues(ici = false): Observable<RafalesPrevues> {
    return this.http.get<RafalesPrevues>(`${this.api}/rafales-prevues/`, ici ? { params: { ici: '1' } } : {});
  }

  imageRafalesUrl(echeance: string): string {
    return `${this.api}/rafales-prevues/image/?echeance=${encodeURIComponent(echeance)}`;
  }

  /** Potentiel d'orage de feu (nos estimations), avec les valeurs au centre du territoire si
   * l'appelant en a un, ou au point demandé. */
  potentielOrageFeu(point?: { lat: number; lon: number }): Observable<PotentielOrageFeu> {
    const params: Record<string, string> = point ? { lat: String(point.lat), lon: String(point.lon) } : {};
    return this.http.get<PotentielOrageFeu>(`${this.api}/orages-de-feu/`, { params });
  }

  imagePotentielOrageFeuUrl(echeance: string): string {
    return `${this.api}/orages-de-feu/image/?echeance=${encodeURIComponent(echeance)}`;
  }

  /** Feux en cours suivis par le satellite MTG, dans une emprise, ou pour toute la France. */
  feuxSuivis(emprise: EmpriseVeille | 'france' = {}): Observable<FeuxSuivis> {
    const params = emprise === 'france' ? { france: '1' } : this.params(emprise);
    return this.http.get<FeuxSuivis>(`${this.api}/feux-suivis/`, { params });
  }

  /** Quarts d'heure pour lesquels une image de neige, verglas et grêle prévus est disponible.
   * `ici` demande en plus ce qui est prévu sur la commune de l'institution de l'appelant. */
  precipitationsHiver(ici = false): Observable<PrecipitationsHiver> {
    return this.http.get<PrecipitationsHiver>(`${this.api}/precipitations-hiver/`, ici ? { params: { ici: '1' } } : {});
  }

  imagePrecipitationHiverUrl(echeance: string): string {
    return `${this.api}/precipitations-hiver/image/?echeance=${encodeURIComponent(echeance)}`;
  }

  /** Tronçons de cours d'eau surveillés par Vigicrues. `trace` joint leur tracé (carte). */
  vigilanceCrues(emprise: EmpriseVeille = {}, trace = false): Observable<VigilanceCrues> {
    const params = this.params(emprise);
    if (trace) params['trace'] = '1';
    return this.http.get<VigilanceCrues>(`${this.api}/vigilance-crues/`, { params });
  }

  restrictionsEau(departement?: string): Observable<RestrictionsEau> {
    const params: Record<string, string> = departement ? { departement } : {};
    return this.http.get<RestrictionsEau>(`${this.api}/restrictions-eau/`, { params });
  }

  /** Surfaces brûlées des trente derniers jours. `trace` joint leur contour (carte). */
  zonesBrulees(emprise: EmpriseVeille = {}, trace = false): Observable<ZonesBrulees> {
    const params = this.params(emprise);
    if (trace) params['trace'] = '1';
    return this.http.get<ZonesBrulees>(`${this.api}/zones-brulees/`, { params });
  }

  meteoForets(departement?: string): Observable<MeteoForets> {
    const params: Record<string, string> = departement ? { departement } : {};
    return this.http.get<MeteoForets>(`${this.api}/meteo-forets/`, { params });
  }

  /** Massifs et leur risque d'avalanche. Liste vide en plaine. `trace` joint leur contour. */
  risqueAvalanche(emprise: EmpriseVeille = {}, trace = false): Observable<RisqueAvalanche> {
    const params = this.params(emprise);
    if (trace) params['trace'] = '1';
    return this.http.get<RisqueAvalanche>(`${this.api}/risque-avalanche/`, { params });
  }

  /** Qualité de l'air estimée (OpenWeather) : les villes de la liste fixe du serveur dans
   * l'emprise, et la plus proche du centre. Lu dans la copie du serveur : rien ne sort. */
  qualiteAir(emprise: EmpriseVeille = {}): Observable<QualiteAir> {
    return this.http.get<QualiteAir>(`${this.api}/qualite-air/`, { params: this.params(emprise) });
  }

  /** Antennes mobiles déclarées en panne ou en maintenance (Arcep), coupures complètes d'abord.
   * Les pannes de plus de six mois ne sont pas rendues, seulement comptées. */
  antennesIndisponibles(emprise: EmpriseVeille = {}): Observable<AntennesIndisponibles> {
    return this.http.get<AntennesIndisponibles>(`${this.api}/antennes-indisponibles/`, { params: this.params(emprise) });
  }

  /** Heures pour lesquelles un champ de vent est disponible ; avec `echeance`, le champ de cette
   * heure pour l'animation de la carte. Toujours national : rien ne dit où l'on regarde. */
  ventPrevu(echeance?: string): Observable<VentPrevu> {
    return this.http.get<VentPrevu>(`${this.api}/vent-prevu/`, echeance ? { params: { echeance } } : {});
  }

  /** Niveau de la mer aux marégraphes (Shom) et surcote estimée, les plus fortes d'abord. */
  niveauxMer(emprise: EmpriseVeille = {}): Observable<NiveauxMer> {
    return this.http.get<NiveauxMer>(`${this.api}/niveaux-mer/`, { params: this.params(emprise) });
  }

  /** Hauteurs d'eau et débits mesurés en rivière (Hub'Eau), ce qui monte le plus vite d'abord. */
  hauteursEau(emprise: EmpriseVeille = {}): Observable<HauteursEau> {
    return this.http.get<HauteursEau>(`${this.api}/hauteurs-eau/`, { params: this.params(emprise) });
  }

  /** Circulation mesurée sur le réseau routier national (Bison Futé). `trace` joint le trait
   * des tronçons (carte) ; `ralentis` ne garde que les tronçons denses, saturés ou bloqués. */
  circulation(emprise: EmpriseVeille = {}, trace = false, ralentis = false): Observable<Circulation> {
    const params = this.params(emprise);
    if (trace) params['trace'] = '1';
    if (ralentis) params['ralentis'] = '1';
    return this.http.get<Circulation>(`${this.api}/circulation/`, { params });
  }

  /** Arrêtés de circulation des collectivités (DiaLog). `trace` joint leur tracé (carte). */
  arretesCirculation(emprise: EmpriseVeille = {}, trace = false): Observable<ArretesCirculation> {
    const params = this.params(emprise);
    if (trace) params['trace'] = '1';
    return this.http.get<ArretesCirculation>(`${this.api}/arretes-circulation/`, { params });
  }

  /** Recours aux urgences par pathologie, pour le département de l'appelant ou un autre. */
  santeUrgences(departement?: string): Observable<SanteUrgences> {
    const params: Record<string, string> = departement ? { departement } : {};
    return this.http.get<SanteUrgences>(`${this.api}/sante-urgences/`, { params });
  }

  /** Dernière mesure des balises Téléray (ASNR) de l'emprise. */
  radioactivite(emprise: EmpriseVeille = {}): Observable<Radioactivite> {
    return this.http.get<Radioactivite>(`${this.api}/radioactivite/`, { params: this.params(emprise) });
  }

  /** Séismes des trente derniers jours. `magnitudeMin` écarte les plus petits. */
  seismes(emprise: EmpriseVeille = {}, magnitudeMin?: number): Observable<Seismes> {
    const params = this.params(emprise);
    if (magnitudeMin != null) params['magnitude_min'] = String(magnitudeMin);
    return this.http.get<Seismes>(`${this.api}/seismes/`, { params });
  }

  /** Sismicité autour des volcans français ; `a_portee` dit lesquels concernent l'appelant. */
  volcans(): Observable<Volcans> {
    return this.http.get<Volcans>(`${this.api}/volcans/`);
  }

  defibrillateurs(emprise: EmpriseVeille = {}): Observable<Defibrillateurs> {
    return this.http.get<Defibrillateurs>(`${this.api}/defibrillateurs/`, { params: this.params(emprise) });
  }

  private params(emprise: EmpriseVeille): Record<string, string> {
    const params: Record<string, string> = {};
    if (emprise.bbox) params['bbox'] = emprise.bbox.join(',');
    if (emprise.lat != null && emprise.lon != null) {
      params['lat'] = String(emprise.lat);
      params['lon'] = String(emprise.lon);
    }
    if (emprise.rayon_km != null) params['rayon_km'] = String(emprise.rayon_km);
    return params;
  }

  /** Foyers vus par satellite. `fixes` joint les sources fixes (usines), toujours marquées. */
  foyersActifs(emprise: EmpriseVeille = {}, fixes = false): Observable<FoyersActifs> {
    const params = this.params(emprise);
    if (fixes) params['fixes'] = '1';
    return this.http.get<FoyersActifs>(`${this.api}/foyers-actifs/`, { params });
  }

  // ── Réglage de l'annonce des foyers, par institution ──

  alerteFeu(institutionId: string): Observable<ConfigurationAlerteFeu[]> {
    return this.http.get<ConfigurationAlerteFeu[]>(
      `${this.api}/configurations-alerte-feu/`, { params: { institution: institutionId } });
  }

  creerAlerteFeu(data: { institution: string; actif: boolean; rayon_km: number }): Observable<ConfigurationAlerteFeu> {
    return this.http.post<ConfigurationAlerteFeu>(`${this.api}/configurations-alerte-feu/`, data);
  }

  modifierAlerteFeu(id: number, data: Partial<ConfigurationAlerteFeu>): Observable<ConfigurationAlerteFeu> {
    return this.http.patch<ConfigurationAlerteFeu>(`${this.api}/configurations-alerte-feu/${id}/`, data);
  }

  // ── Réglage de l'annonce de vigilance, par institution ──

  alerteVigilance(institutionId: string): Observable<ConfigurationAlerteVigilance[]> {
    return this.http.get<ConfigurationAlerteVigilance[]>(
      `${this.api}/configurations-alerte-vigilance/`, { params: { institution: institutionId } });
  }

  creerAlerteVigilance(data: { institution: string; actif: boolean; couleur_min: number }): Observable<ConfigurationAlerteVigilance> {
    return this.http.post<ConfigurationAlerteVigilance>(`${this.api}/configurations-alerte-vigilance/`, data);
  }

  modifierAlerteVigilance(id: number, data: Partial<ConfigurationAlerteVigilance>): Observable<ConfigurationAlerteVigilance> {
    return this.http.patch<ConfigurationAlerteVigilance>(`${this.api}/configurations-alerte-vigilance/${id}/`, data);
  }
}
