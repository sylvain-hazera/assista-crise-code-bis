import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';

import { DeclarationSecuriteService } from '../../services/declaration-securite.service';
import { DeclarationSecurite } from '../../shared/models/declaration-securite.model';

@Component({
  selector: 'app-mes-declarations-securite',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './mes-declarations-securite.component.html',
  styleUrl: './mes-declarations-securite.component.scss',
})
export class MesDeclarationsSecuriteComponent implements OnInit {

  declarations: DeclarationSecurite[] = [];
  isLoading = true;
  errorMessage = '';

  constructor(
    private declarationSecuriteService: DeclarationSecuriteService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.declarationSecuriteService.mesDeclarations().subscribe({
      next: (declarations) => {
        this.declarations = declarations;
        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = "Impossible de charger vos déclarations. Vous devez être connecté.";
        this.isLoading = false;
      },
    });
  }

  headcount(d: DeclarationSecurite): number {
    return d.nombre_adultes + d.nombre_enfants;
  }

  fmtDate(d: string | null | undefined): string {
    if (!d) return '—';
    return new Date(d).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  goToDeclare(): void {
    this.router.navigate(['/other-declaration']);
  }

  goBack(): void {
    this.router.navigate(['/accueil']);
  }
}
