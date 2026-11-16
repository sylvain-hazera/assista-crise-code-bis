import { DOCUMENT } from '@angular/common';
import { Injectable, inject } from '@angular/core';
import { Meta, Title } from '@angular/platform-browser';
import { NavigationEnd, Router } from '@angular/router';
import { combineLatest } from 'rxjs';
import { filter, map, startWith } from 'rxjs/operators';
import { BrandingService } from '../services/branding.service';
import fiche from './referencement.json';

interface Marque { nom: string; slogan: string; description: string; }
interface Page { chemin: string; titre: string; description: string; }

const MARQUES: Record<string, Marque> = fiche.marques;
const PAGES: Page[] = fiche.pages;

export interface EnTete {
  titre: string;
  description: string;
  /** Adresse canonique, ou `null` quand la page ne doit pas être indexée. */
  canonique: string | null;
}

/** L'adresse d'une page sans ses paramètres, `/accueil` valant la racine — même règle que la
 * variable `$seo_chemin` du serveur web (scripts/generer-referencement.mjs). */
export function cheminDe(url: string): string {
  const chemin = url.split(/[?#]/)[0].replace(/\/+$/, '') || '/';
  return chemin === '/accueil' ? '/' : chemin;
}

/** Ce que l'en-tête de la page doit dire, pour une adresse, un hôte et un nom de marque.
 *
 * Mêmes règles que le serveur web, qui pose ces balises AVANT que le site ne démarre (un lien
 * partagé ou un moteur sans JavaScript ne lit que cela). Le site les tient ensuite à jour à
 * chaque changement de page. Les deux lisent `referencement.json`.
 *
 * `nomDeLaMarque` vient de l'API (marque blanche) et ne sert que pour un hôte absent de la
 * fiche : un satellite, ou un domaine partenaire pas encore déclaré. */
export function enTeteDe(url: string, hote: string, nomDeLaMarque: string): EnTete {
  const reference = MARQUES[hote];
  const marque = reference ?? { ...MARQUES[fiche.marque_par_defaut], nom: nomDeLaMarque };
  const chemin = cheminDe(url);
  const page = PAGES.find((p) => p.chemin === chemin);

  if (!page) {
    return { titre: marque.nom, description: marque.description, canonique: null };
  }
  return {
    titre: chemin === '/' ? `${marque.nom} — ${marque.slogan}` : `${page.titre} — ${marque.nom}`,
    description: page.description || marque.description,
    // Seuls les hôtes d'une marque sont proposés aux moteurs : le même site servi sous une
    // adresse de secours ferait doublon.
    canonique: reference ? `https://${hote}${chemin}` : null,
  };
}

/** Tient à jour le titre de l'onglet, la description et l'adresse canonique à chaque
 * changement de page ou de marque. Démarré une fois par AppComponent. */
@Injectable({ providedIn: 'root' })
export class ReferencementService {
  private titre = inject(Title);
  private meta = inject(Meta);
  private router = inject(Router);
  private branding = inject(BrandingService);
  private document = inject(DOCUMENT);
  private demarre = false;

  demarrer(): void {
    if (this.demarre) return;
    this.demarre = true;
    const adresse$ = this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    );
    combineLatest([adresse$, this.branding.branding$]).subscribe(([url, branding]) => {
      this.appliquer(enTeteDe(url, this.document.location.hostname, branding.nom_affichage));
    });
  }

  appliquer(enTete: EnTete): void {
    this.titre.setTitle(enTete.titre);
    this.meta.updateTag({ name: 'description', content: enTete.description });
    this.meta.updateTag({ property: 'og:title', content: enTete.titre });
    this.meta.updateTag({ property: 'og:description', content: enTete.description });

    let lien = this.document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (enTete.canonique) {
      if (!lien) {
        lien = this.document.createElement('link');
        lien.rel = 'canonical';
        this.document.head.appendChild(lien);
      }
      lien.href = enTete.canonique;
      this.meta.updateTag({ property: 'og:url', content: enTete.canonique });
      this.meta.removeTag('name="robots"');
    } else {
      lien?.remove();
      this.meta.removeTag('property="og:url"');
      // Le serveur web le dit déjà par en-tête à l'ouverture de la page ; ceci couvre la
      // navigation interne, où aucune nouvelle page n'est demandée au serveur.
      this.meta.updateTag({ name: 'robots', content: 'noindex, nofollow' });
    }
  }
}
