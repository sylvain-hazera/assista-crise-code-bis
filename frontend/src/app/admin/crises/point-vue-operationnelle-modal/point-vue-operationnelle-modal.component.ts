import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { PointOperationnel, VueOperationnelle } from '../../../shared/models/point-operationnel.model';

/** Vue opérationnelle d'un centre : équipes le tenant (par spécialité) et équipes de terrain
 * qu'il ravitaille — effectif et matériel de chacune — plus les civils actuellement accueillis. */
@Component({
  selector: 'app-point-vue-operationnelle-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './point-vue-operationnelle-modal.component.html',
  styleUrl: './point-vue-operationnelle-modal.component.scss'
})
export class PointVueOperationnelleModalComponent implements OnInit {
  @Input({ required: true }) point!: PointOperationnel;
  @Output() closed = new EventEmitter<void>();

  data: VueOperationnelle | null = null;
  loading = true;

  constructor(private pointOperationnelService: PointOperationnelService) {}

  ngOnInit(): void {
    this.pointOperationnelService.getVueOperationnelle(this.point.id).subscribe(data => {
      this.data = data;
      this.loading = false;
    });
  }

  close(): void {
    this.closed.emit();
  }
}
