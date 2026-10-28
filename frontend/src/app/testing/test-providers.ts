import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';

/**
 * Le socle dont tout test de cette application a besoin.
 *
 * Les 68 fichiers de test générés par le CLI configuraient un `TestBed` vide. Comme presque
 * tout ici injecte `HttpClient` — un service d'API, un composant qui en dépend —, 29 d'entre
 * eux échouaient sur une erreur d'injecteur. Personne ne l'avait vu : `angular.json` ne
 * référençait pas `karma.conf.js`, donc le lanceur sans bac à sable n'était pas enregistré et
 * la suite ne démarrait pas du tout (voir Dockerfile.test).
 *
 * Un helper partagé plutôt que trois lignes répétées dans chaque fichier : le jour où un
 * nouveau fournisseur devient nécessaire partout (animations, locale, un intercepteur), il
 * s'ajoute ici et non dans soixante-huit endroits.
 *
 * `provideHttpClientTesting` APRÈS `provideHttpClient` : il remplace le gestionnaire réel par
 * le contrôleur de test, et l'ordre inverse laisserait les requêtes partir pour de vrai — un
 * test qui appelle le réseau est un test qui échoue au hasard.
 */
export function fournisseursDeTest() {
  return [
    provideHttpClient(),
    provideHttpClientTesting(),
    // Beaucoup de composants injectent Router ne serait-ce que pour un lien : un routeur vide
    // suffit et évite d'avoir à le deviner fichier par fichier.
    provideRouter([]),
    // `provideRouter` ne fournit PAS ActivatedRoute à un composant créé directement par
    // TestBed : elle n'existe que dans le contexte d'une route réellement activée. Un double
    // minimal évite d'avoir à monter un harnais de routage pour un test qui veut seulement
    // vérifier qu'un écran se construit.
    { provide: ActivatedRoute, useValue: routeFactice() },
  ];
}

/** Une route activée vide, sous les deux formes que les composants lisent : l'instantané
 * (`snapshot.paramMap.get('id')`) et les flux (`params.subscribe`). Fournir l'une sans l'autre
 * ne rate qu'un composant sur deux. */
function routeFactice() {
  const vide = convertToParamMap({});
  return {
    snapshot: { paramMap: vide, queryParamMap: vide, params: {}, queryParams: {}, data: {} },
    paramMap: of(vide),
    queryParamMap: of(vide),
    params: of({}),
    queryParams: of({}),
    data: of({}),
  };
}
