import { Component, OnInit, OnDestroy, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, takeUntil, forkJoin } from 'rxjs';
import { 
  GouvApiService, 
  Departement, 
  Commune, 
  RisqueCommune,
  DicrimResponse,
  TimResponse
} from '../../core/services/gouv-api.service';

@Component({
  selector: 'app-guide',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './guide.component.html',
  styleUrl: './guide.component.scss'
})
export class GuideComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  // Données des listes déroulantes
  departements: Departement[] = [];
  communes: Commune[] = [];

  // Valeurs sélectionnées
  selectedDepartement: Departement | null = null;
  selectedCommune: Commune | null = null;

  // Recherche autocomplete
  departementSearchTerm: string = '';
  communeSearchTerm: string = '';
  filteredDepartements: Departement[] = [];
  filteredCommunes: Commune[] = [];
  showDepartementDropdown: boolean = false;
  showCommuneDropdown: boolean = false;

  // Résultats de l'API GéoRisques
  risqueData: RisqueCommune | null = null;
  dicrimData: DicrimResponse | null = null;
  timData: TimResponse | null = null;
  isLoading: boolean = false;
  errorMessage: string = '';
  apiUrl: string = ''; // URL de l'API pour débogage

  constructor(private gouvApiService: GouvApiService) {}

  ngOnInit(): void {
    this.loadDepartements();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  /**
   * Ferme les dropdowns quand on clique en dehors
   */
  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    
    // Vérifier si le clic est à l'intérieur d'un conteneur autocomplete
    if (!target.closest('.autocomplete-container')) {
      this.showDepartementDropdown = false;
      this.showCommuneDropdown = false;
    }
  }

  /**
   * Charge la liste des départements au démarrage
   */
  private loadDepartements(): void {
    this.isLoading = true;
    this.gouvApiService.getDepartements()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (departements) => {
          this.departements = departements.sort((a, b) => a.nom.localeCompare(b.nom));
          this.isLoading = false;
        },
        error: (error) => {
          console.error('Erreur lors du chargement des départements:', error);
          this.errorMessage = 'Impossible de charger les départements';
          this.isLoading = false;
        }
      });
  }

  /**
   * Filtre les départements selon le terme de recherche
   */
  onDepartementSearchChange(): void {
    const term = this.departementSearchTerm.toLowerCase().trim();
    
    if (term.length === 0) {
      this.filteredDepartements = [];
      this.showDepartementDropdown = false;
      return;
    }

    this.filteredDepartements = this.departements
      .filter(dept => 
        dept.nom.toLowerCase().includes(term) || 
        dept.code.includes(term)
      )
      .slice(0, 10); // Limiter à 10 résultats
    
    this.showDepartementDropdown = this.filteredDepartements.length > 0;
  }

  /**
   * Sélectionne un département
   */
  selectDepartement(departement: Departement): void {
    this.selectedDepartement = departement;
    this.departementSearchTerm = `${departement.code} - ${departement.nom}`;
    this.showDepartementDropdown = false;
    this.filteredDepartements = [];
    
    // Réinitialiser la commune
    this.selectedCommune = null;
    this.communeSearchTerm = '';
    this.communes = [];
    this.filteredCommunes = [];
    this.risqueData = null;
    this.errorMessage = '';

    // Charger les communes
    this.loadCommunes(departement.code);
  }

  /**
   * Charge les communes d'un département
   */
  private loadCommunes(codeDepartement: string): void {
    this.isLoading = true;
    this.gouvApiService.getCommunesByDepartement(codeDepartement)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (communes) => {
          this.communes = communes.sort((a, b) => a.nom.localeCompare(b.nom));
          this.isLoading = false;
        },
        error: (error) => {
          console.error('Erreur lors du chargement des communes:', error);
          this.errorMessage = 'Impossible de charger les communes';
          this.isLoading = false;
        }
      });
  }

  /**
   * Filtre les communes selon le terme de recherche
   */
  onCommuneSearchChange(): void {
    const term = this.communeSearchTerm.toLowerCase().trim();
    
    if (term.length === 0) {
      this.filteredCommunes = [];
      this.showCommuneDropdown = false;
      return;
    }

    this.filteredCommunes = this.communes
      .filter(commune => 
        commune.nom.toLowerCase().includes(term) ||
        commune.codesPostaux.some(cp => cp.includes(term))
      )
      .slice(0, 10); // Limiter à 10 résultats
    
    this.showCommuneDropdown = this.filteredCommunes.length > 0;
  }

  /**
   * Sélectionne une commune
   */
  selectCommune(commune: Commune): void {
    this.selectedCommune = commune;
    this.communeSearchTerm = `${commune.nom} (${commune.codesPostaux[0]})`;
    this.showCommuneDropdown = false;
    this.filteredCommunes = [];
    
    // Charger les risques
    this.loadRisques(commune.code);
  }

  /**
   * Charge les risques d'une commune
   */
  private loadRisques(codeInsee: string): void {
    this.risqueData = null;
    this.dicrimData = null;
    this.timData = null;
    this.errorMessage = '';
    this.isLoading = true;

    // Construire et afficher l'URL de l'API
    this.apiUrl = `https://georisques.gouv.fr/api/v1/gaspar/risques?code_insee=${codeInsee}`;
    console.log('=== TEST API GÉORISQUES ===');
    console.log('URL risques:', this.apiUrl);
    console.log('URL DICRIM:', `https://georisques.gouv.fr/api/v1/gaspar/dicrim?code_insee=${codeInsee}`);
    console.log('URL TIM (PCS):', `https://georisques.gouv.fr/api/v1/gaspar/tim?code_insee=${codeInsee}`);
    console.log('Code INSEE:', codeInsee);
    console.log('=============================');

    // Charger toutes les données en parallèle
    forkJoin({
      risques: this.gouvApiService.getRisquesByCommune(codeInsee),
      dicrim: this.gouvApiService.getDicrimByCommune(codeInsee),
      tim: this.gouvApiService.getTimByCommune(codeInsee)
    })
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (results) => {
          console.log('Données complètes reçues:', results);
          
          // Risques
          if (results.risques.data && results.risques.data.length > 0) {
            this.risqueData = results.risques.data[0];
            console.log('Risques - Commune:', this.risqueData.libelle_commune);
            console.log('Risques - Nombre:', this.risqueData.risques_detail?.length || 0);
          }

          // DICRIM
          this.dicrimData = results.dicrim;
          if (results.dicrim.data && results.dicrim.data.length > 0) {
            console.log('DICRIM trouvé - Année:', results.dicrim.data[0].annee_publication);
          } else {
            console.log('Pas de DICRIM disponible');
          }

          // TIM (PCS)
          this.timData = results.tim;
          if (results.tim.data && results.tim.data.length > 0) {
            console.log('TIM (PCS) trouvé - Date:', results.tim.data[0].date_transmission);
          } else {
            console.log('Pas de TIM (PCS) disponible');
          }

          if (!this.risqueData) {
            this.errorMessage = 'Aucune donnée de risque disponible pour cette commune';
          }
          
          this.isLoading = false;
        },
        error: (error) => {
          console.error('Erreur lors du chargement des données:', error);
          this.errorMessage = 'Impossible de charger les données';
          this.isLoading = false;
        }
      });
  }

  /**
   * Copie l'URL de l'API dans le presse-papiers
   */
  copyApiUrl(): void {
    if (this.apiUrl) {
      navigator.clipboard.writeText(this.apiUrl).then(() => {
        alert('URL copiée dans le presse-papiers !');
      }).catch(err => {
        console.error('Erreur lors de la copie:', err);
        // Fallback: afficher l'URL dans une alerte
        prompt('Copiez cette URL:', this.apiUrl);
      });
    }
  }

  /**
   * Vérifie si la commune a un DICRIM
   */
  hasDICRIM(): boolean {
    return !!(this.dicrimData?.data && this.dicrimData.data.length > 0);
  }

  /**
   * Récupère l'année de publication du DICRIM
   */
  getDicrimYear(): string {
    if (this.hasDICRIM() && this.dicrimData?.data[0]) {
      return this.dicrimData.data[0].annee_publication;
    }
    return '';
  }

  /**
   * Vérifie si la commune a un PCS (via TIM)
   */
  hasPCS(): boolean {
    return !!(this.timData?.data && this.timData.data.length > 0);
  }

  /**
   * Récupère la date de transmission du TIM (PCS)
   */
  getTimDate(): string {
    if (this.hasPCS() && this.timData?.data[0]) {
      return this.timData.data[0].date_transmission;
    }
    return '';
  }

  /**
   * Ouvre la page GéoRisques pour la commune
   */
  openGeorisquesPage(): void {
    if (this.selectedCommune && this.risqueData) {
      // Format: /mes-risques/connaitre-les-risques-pres-de-chez-moi/rapport2/{code_insee}/{nom-commune}/commune/{code_postal}
      const codePostal = this.selectedCommune.codesPostaux[0] || '';
      const nomCommune = this.risqueData.libelle_commune
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '') // Retirer les accents
        .replace(/\s+/g, '-') // Remplacer espaces par tirets
        .replace(/[^a-z0-9-]/g, ''); // Garder seulement lettres, chiffres et tirets
      
      const url = `https://www.georisques.gouv.fr/mes-risques/connaitre-les-risques-pres-de-chez-moi/rapport2/${this.selectedCommune.code}/${nomCommune}/commune/${codePostal}`;
      window.open(url, '_blank');
    }
  }

  /**
   * Ouvre le site de la mairie
   */
  openMairieSite(): void {
    if (this.risqueData) {
      const query = encodeURIComponent(`mairie ${this.risqueData.libelle_commune}`);
      const url = `https://www.google.com/search?q=${query}`;
      window.open(url, '_blank');
    }
  }
}
