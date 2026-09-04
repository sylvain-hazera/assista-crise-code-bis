import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';

import { BesoinService } from '../../services/besoin.service';
import { Besoin } from '../../shared/models/besoin.model';

@Component({
  selector: 'app-besoins',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './besoins.component.html'
})
export class BesoinsComponent implements OnInit {

  besoins: Besoin[] = [];

  constructor(private besoinService: BesoinService) {}

  ngOnInit(): void {
    this.besoinService.getAll().subscribe(data => {
      this.besoins = data;
    });
  }
}
